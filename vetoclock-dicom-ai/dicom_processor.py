import boto3
import zipfile
import io
import os
import tempfile
from urllib.parse import urlparse
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image, ImageDraw, ImageFont

import config

# Windowing para tórax
WINDOW_CENTER_PULMON     = -600
WINDOW_WIDTH_PULMON      = 1500
WINDOW_CENTER_MEDIASTINO = 40
WINDOW_WIDTH_MEDIASTINO  = 400
WINDOW_CENTER_GRASA      = -100
WINDOW_WIDTH_GRASA       = 400

# Rangos HU para caracterización tisular
HU_GRASA_MIN    = -200
HU_GRASA_MAX    = -50
HU_AGUA_MIN     = -20
HU_AGUA_MAX     = 20
HU_TEJIDO_MIN   = 20
HU_TEJIDO_MAX   = 80


def _s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=config.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
        region_name=config.AWS_REGION,
        config=boto3.session.Config(signature_version="s3v4"),
    )


def _url_to_s3_key(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path.lstrip("/")


def _apply_windowing(pixel_array: np.ndarray, center: int, width: int) -> np.ndarray:
    low  = center - width / 2
    high = center + width / 2
    arr  = np.clip(pixel_array, low, high)
    arr  = ((arr - low) / (high - low) * 255).astype(np.uint8)
    return arr


def _hu_array(ds: pydicom.Dataset) -> np.ndarray:
    arr = ds.pixel_array.astype(np.float32)
    slope     = float(getattr(ds, "RescaleSlope", 1))
    intercept = float(getattr(ds, "RescaleIntercept", 0))
    return arr * slope + intercept


def _hu_stats(arr: np.ndarray) -> dict:
    # Exclude only scanner background (< -900 HU), keep lung air (-900 to -300 HU)
    tissue = arr[arr > -900]
    if tissue.size == 0:
        tissue = arr
    return {
        "min":  round(float(tissue.min()), 1),
        "max":  round(float(tissue.max()), 1),
        "mean": round(float(tissue.mean()), 1),
        "std":  round(float(tissue.std()), 1),
        "p10":  round(float(np.percentile(tissue, 10)), 1),
        "p25":  round(float(np.percentile(tissue, 25)), 1),
        "p75":  round(float(np.percentile(tissue, 75)), 1),
        "p90":  round(float(np.percentile(tissue, 90)), 1),
    }


def _caracterizar_tejido(stats: dict) -> str:
    mean_hu = stats["mean"]
    p10     = stats["p10"]
    p25     = stats["p25"]

    # Pulmón bien aireado: media muy negativa
    if mean_hu < -500:
        return f"PULMÓN AIREADO ({mean_hu:.0f} HU) — parénquima con buena ventilación"
    # Pulmón parcialmente aireado / consolidado
    if -500 <= mean_hu < -300:
        return f"PULMÓN PARCIALMENTE AIREADO ({mean_hu:.0f} HU) — posible consolidación o derrame"
    # Neumotórax si p10 muy bajo
    if p10 < -800:
        return f"POSIBLE NEUMOTÓRAX (p10={p10:.0f} HU) — gas libre pleural a verificar en imagen"
    # Lipoma: p10 en rango graso
    if HU_GRASA_MIN <= p10 <= HU_GRASA_MAX:
        return f"ZONA GRASA DETECTADA (p10={p10:.0f} HU, media={mean_hu:.0f} HU) — compatible con lipoma/tejido adiposo"
    elif HU_GRASA_MIN <= mean_hu <= HU_GRASA_MAX:
        return f"TEJIDO GRASO ({mean_hu:.0f} HU) — compatible con lipoma/tejido adiposo"
    elif HU_AGUA_MIN <= mean_hu <= HU_AGUA_MAX:
        return f"DENSIDAD AGUA/FLUIDO ({mean_hu:.0f} HU) — compatible con quiste, derrame o líquido libre"
    elif HU_TEJIDO_MIN <= mean_hu <= HU_TEJIDO_MAX:
        return f"TEJIDO BLANDO ({mean_hu:.0f} HU) — compatible con músculo/tejido blando"
    elif mean_hu > 100:
        return f"DENSIDAD ALTA ({mean_hu:.0f} HU) — compatible con hueso/calcificación/contraste"
    else:
        return f"DENSIDAD INTERMEDIA ({mean_hu:.0f} HU)"


def _add_orientation_markers(img: Image.Image) -> Image.Image:
    draw = ImageDraw.Draw(img)
    w, h = img.size
    font_size = max(14, w // 25)
    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:
        font = ImageFont.load_default()
    y_pos = h // 2 - font_size // 2
    # Convención radiológica: R del paciente = izquierda imagen, L del paciente = derecha imagen
    draw.text((4, y_pos), "R", fill=(255, 255, 0), font=font)
    draw.text((w - font_size - 2, y_pos), "L", fill=(255, 255, 0), font=font)
    return img


IMG_SIZE = 400   # px — balance calidad/memoria (10-15× menos RAM que PIL sin comprimir)


def _dicom_to_jpeg(arr_hu: np.ndarray, window: str = "pulmon") -> bytes:
    if window == "mediastino":
        arr = _apply_windowing(arr_hu, WINDOW_CENTER_MEDIASTINO, WINDOW_WIDTH_MEDIASTINO)
    elif window == "grasa":
        arr = _apply_windowing(arr_hu, WINDOW_CENTER_GRASA, WINDOW_WIDTH_GRASA)
    else:
        arr = _apply_windowing(arr_hu, WINDOW_CENTER_PULMON, WINDOW_WIDTH_PULMON)

    img = Image.fromarray(arr).convert("RGB")
    img = img.resize((IMG_SIZE, IMG_SIZE), Image.LANCZOS)
    img = _add_orientation_markers(img)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _normalizar_caracterizaciones(stats_lista: list) -> list:
    """Si >50% de cortes muestran ZONA GRASA, es panículo adiposo global, no lipoma focal."""
    if not stats_lista:
        return stats_lista
    n_grasa = sum(1 for s in stats_lista if "ZONA GRASA DETECTADA" in s.get("caracterizacion", ""))
    if len(stats_lista) > 0 and n_grasa / len(stats_lista) > 0.5:
        for s in stats_lista:
            if "ZONA GRASA DETECTADA" in s.get("caracterizacion", ""):
                s["caracterizacion"] = (
                    f"Grasa subcutánea fisiológica (p10={s['p10']:.0f} HU, media={s['mean']:.0f} HU) "
                    f"— patrón global del panículo adiposo torácico, no lesión focal"
                )
    return stats_lista


def _pesos_por_motivo(presentacion: str, antecedentes: str = "") -> list[float]:
    texto = f"{presentacion or ''} {antecedentes or ''}".lower()

    craneal_kw    = ['axila', 'axilar', 'cervical', 'cuello', 'craneal', 'esternal',
                     'nódulo', 'braquial', 'tiroides', 'entrada torácica', 'ganglio',
                     'mediastino craneal', 'masa cervico', 'linfonodo craneal']
    caudal_kw     = ['diafragma', 'caudal', 'efusión', 'derrame', 'neumotórax',
                     'hepático', 'hígado', 'pleural', 'lóbulo caudal']
    oncologico_kw = ['osteosarcoma', 'sarcoma', 'neoplasia', 'tumor', 'metástasis',
                     'estadiaje', 'linfoma', 'carcinoma', 'osteolítica', 'neoplásico',
                     'maligno', 'estadificación', 'lesión ósea']

    craneal_hits  = sum(1 for k in craneal_kw if k in texto)
    caudal_hits   = sum(1 for k in caudal_kw  if k in texto)
    es_oncologico = any(k in texto for k in oncologico_kw)

    if craneal_hits > caudal_hits and craneal_hits > 0:
        return [0.50, 0.30, 0.20]   # prioridad craneal
    elif caudal_hits > craneal_hits and caudal_hits > 0:
        return [0.20, 0.30, 0.50]   # prioridad caudal
    elif es_oncologico:
        return [0.40, 0.35, 0.25]   # estadiaje oncológico: leve sesgo craneal
    else:
        return [1/3, 1/3, 1/3]      # distribución uniforme


def _calcular_counts(n: int, pesos: list) -> list[int]:
    counts = [max(2, round(n * p)) for p in pesos]
    diff   = n - sum(counts)
    counts[pesos.index(max(pesos))] += diff
    return counts


def _seleccionar_cortes(datasets: list, n: int = 20, pesos: list = None) -> list:
    if len(datasets) <= n:
        return datasets

    if pesos is None:
        pesos = [1/3, 1/3, 1/3]

    def z_pos(ds):
        try:
            return float(ds.ImagePositionPatient[2])
        except Exception:
            return 0.0

    datasets = sorted(datasets, key=z_pos)
    total = len(datasets)

    zones = [
        (int(total * 0.10), int(total * 0.35)),
        (int(total * 0.35), int(total * 0.65)),
        (int(total * 0.65), int(total * 0.90)),
    ]
    counts = _calcular_counts(n, pesos)

    selected = []
    for (start, end), count in zip(zones, counts):
        end = max(end, start + 1)
        indices = np.linspace(start, end - 1, count, dtype=int)
        selected.extend([datasets[idx] for idx in indices])

    return selected


CACHE_DIR = Path(__file__).parent / ".dicom_cache"


def descargar_y_procesar(enlace_dicom: str, n_cortes: int = 20, presentacion: str = "", antecedentes: str = "") -> dict:
    key       = _url_to_s3_key(enlace_dicom)
    cache_file = CACHE_DIR / Path(key).name

    CACHE_DIR.mkdir(exist_ok=True)

    if not cache_file.exists():
        s3 = _s3_client()
        print(f"[S3] Descargando — Bucket: {config.S3_BUCKET} | Key: {key}")
        obj = s3.get_object(Bucket=config.S3_BUCKET, Key=key)
        with open(cache_file, "wb") as f:
            for chunk in obj["Body"].iter_chunks(chunk_size=8 * 1024 * 1024):
                f.write(chunk)
        print(f"[CACHE] ZIP guardado en: {cache_file}")
    else:
        print(f"[CACHE] Usando ZIP local: {cache_file}")

    with zipfile.ZipFile(cache_file) as zf:
        archivos_dcm = [
            f for f in zf.namelist()
            if not f.startswith("__MACOSX")
            and not os.path.basename(f).startswith(".")
            and (f.lower().endswith(".dcm") or "." not in os.path.basename(f))
        ]
        print(f"[DICOM] {len(archivos_dcm)} archivos encontrados en el ZIP")

        if not archivos_dcm:
            raise ValueError(f"No se encontraron archivos DICOM en {enlace_dicom}")

        # Paso 1: leer solo metadatos para obtener posición Z y separar series
        meta_list = []
        for nombre in archivos_dcm:
            try:
                with zf.open(nombre) as f:
                    ds = pydicom.dcmread(io.BytesIO(f.read()), force=True, stop_before_pixels=True)
                    meta_list.append((nombre, ds))
            except Exception:
                continue

        print(f"[DICOM] {len(meta_list)} slices con metadatos leídos")

        if not meta_list:
            raise ValueError("No se pudieron leer los archivos DICOM")

        # Separar series por SeriesInstanceUID usando solo metadatos
        series_meta = {}
        for nombre, ds in meta_list:
            uid = getattr(ds, "SeriesInstanceUID", "sin_uid")
            series_meta.setdefault(uid, []).append((nombre, ds))
        del meta_list  # liberar memoria: metadatos ya indexados en series_meta

        print(f"[DICOM] {len(series_meta)} series detectadas:")
        for uid, slices in series_meta.items():
            desc = getattr(slices[0][1], "SeriesDescription", "sin descripción")
            print(f"[DICOM]   UID={uid} | {len(slices)} slices | desc='{desc}'")

        # Seleccionar la serie con cortes más finos (mayor resolución diagnóstica)
        # Excluir scouts/localizadores (< 10 slices); entre candidatas, priorizar menor SliceThickness
        def _serie_score(slices):
            if len(slices) < 10:
                return (99, 0)   # penalizar scouts
            ds = slices[0][1]
            thickness = float(getattr(ds, "SliceThickness", 99))
            return (thickness, -len(slices))  # menor thickness primero, más slices en empate

        serie_principal_meta = min(series_meta.values(), key=_serie_score)
        desc_principal  = getattr(serie_principal_meta[0][1], "SeriesDescription", "sin descripción")
        thickness_print = float(getattr(serie_principal_meta[0][1], "SliceThickness", "?"))
        print(f"[DICOM] Serie seleccionada: {len(serie_principal_meta)} slices | {thickness_print}mm | '{desc_principal}'")

        pesos       = _pesos_por_motivo(presentacion, antecedentes)
        counts_zona = _calcular_counts(n_cortes, pesos)
        print(f"[DICOM] Muestreo adaptado — pesos craneal/medio/caudal: {pesos} → {counts_zona} cortes")

        # Seleccionar cortes usando metadatos (posición Z)
        def z_pos_meta(item):
            try:
                return float(item[1].ImagePositionPatient[2])
            except Exception:
                return 0.0

        serie_ordenada = sorted(serie_principal_meta, key=z_pos_meta)
        total = len(serie_ordenada)

        # Detectar zona torácica: muestrear ~20 slices para encontrar dónde hay pulmón
        n_muestras = min(20, total)
        indices_muestra = np.linspace(0, total - 1, n_muestras, dtype=int)
        fracciones_pulmon = []
        for idx in indices_muestra:
            nombre = serie_ordenada[idx][0]
            try:
                with zf.open(nombre) as f:
                    ds = pydicom.dcmread(io.BytesIO(f.read()), force=True)
                    if hasattr(ds, "pixel_array"):
                        arr = ds.pixel_array.astype(np.float32)
                        slope = float(getattr(ds, "RescaleSlope", 1))
                        intercept = float(getattr(ds, "RescaleIntercept", 0))
                        arr_hu = arr * slope + intercept
                        fraccion = float(np.mean(arr_hu < -300))
                        fracciones_pulmon.append((idx, fraccion))
                        del arr, arr_hu  # liberar pixels de muestreo
                    else:
                        fracciones_pulmon.append((idx, 0.0))
                    del ds
            except Exception:
                fracciones_pulmon.append((idx, 0.0))

        con_pulmon = [(idx, f) for idx, f in fracciones_pulmon if f >= 0.05]
        if con_pulmon:
            idx_torax_ini = con_pulmon[0][0]
            idx_torax_fin = con_pulmon[-1][0]
            margen = max(5, (idx_torax_fin - idx_torax_ini) // 10)
            idx_torax_ini = max(0, idx_torax_ini - margen)
            idx_torax_fin = min(total - 1, idx_torax_fin + margen)
            print(f"[DICOM] Zona torácica detectada: slices {idx_torax_ini}–{idx_torax_fin} de {total}")
        else:
            idx_torax_ini, idx_torax_fin = 0, total - 1
            print(f"[DICOM] No se detectó zona torácica clara, usando rango completo")

        rango = idx_torax_fin - idx_torax_ini + 1
        zones = [
            (idx_torax_ini + int(rango * 0.10), idx_torax_ini + int(rango * 0.35)),
            (idx_torax_ini + int(rango * 0.35), idx_torax_ini + int(rango * 0.65)),
            (idx_torax_ini + int(rango * 0.65), idx_torax_ini + int(rango * 0.90)),
        ]
        counts = _calcular_counts(n_cortes, pesos)
        nombres_seleccionados = []
        for (start, end), count in zip(zones, counts):
            end = max(end, start + 1)
            indices = np.linspace(start, end - 1, count, dtype=int)
            nombres_seleccionados.extend([serie_ordenada[idx][0] for idx in indices])

        # Construir series_info desde metadatos antes de liberar series_meta
        series_info_local = [
            {"uid": uid, "n_slices": len(slices), "desc": getattr(slices[0][1], "SeriesDescription", "sin descripción")}
            for uid, slices in series_meta.items()
        ]
        del series_meta  # liberar todos los Dataset de metadatos

        # Paso 2: cargar pixels, procesar y convertir a JPEG bytes inmediatamente
        print(f"[DICOM] Procesando {len(nombres_seleccionados)} cortes seleccionados...")
        hu_stats_lista   = []
        imagenes_pulmon  = []
        imagenes_tejido  = []
        imagenes_grasa   = []
        errores_pixel    = {}

        for i, nombre in enumerate(nombres_seleccionados):
            try:
                with zf.open(nombre) as f:
                    ds = pydicom.dcmread(io.BytesIO(f.read()), force=True)
                try:
                    arr_hu = _hu_array(ds)
                    del ds  # liberar Dataset inmediatamente tras extraer HU array
                    stats  = _hu_stats(arr_hu)
                    stats["caracterizacion"] = _caracterizar_tejido(stats)
                    hu_stats_lista.append(stats)

                    # Convertir a JPEG bytes en lugar de PIL Images (~50KB vs ~470KB por imagen)
                    imagenes_pulmon.append(_dicom_to_jpeg(arr_hu, "pulmon"))
                    imagenes_tejido.append(_dicom_to_jpeg(arr_hu, "mediastino"))
                    imagenes_grasa.append(_dicom_to_jpeg(arr_hu, "grasa"))
                    del arr_hu  # liberar array numpy tras generar los 3 JPEGs
                    print(f"[DICOM] Corte {i+1}/{len(nombres_seleccionados)}: media={stats['mean']} HU | {stats['caracterizacion']}")
                except Exception as e_px:
                    clave = type(e_px).__name__
                    errores_pixel[clave] = str(e_px)
                    try:
                        del ds
                    except Exception:
                        pass
            except Exception as e_read:
                errores_pixel[type(e_read).__name__] = str(e_read)

        if errores_pixel:
            for tipo, msg in errores_pixel.items():
                print(f"[DICOM] ✗ Error decodificando pixels — {tipo}: {msg}")

        hu_stats_lista = _normalizar_caracterizaciones(hu_stats_lista)
        print(f"[DICOM] Procesamiento completado: {len(imagenes_pulmon)} cortes OK")

    return {
        "pulmon":        imagenes_pulmon,
        "tejido_blando": imagenes_tejido,
        "grasa":         imagenes_grasa,
        "series_info":   series_info_local,
        "hu_stats":      hu_stats_lista,
        "n_cortes":      len(imagenes_pulmon),
        "counts_zona":   counts_zona,
        "pesos_zona":    pesos,
    }
