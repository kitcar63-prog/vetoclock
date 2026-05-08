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
    # Exclude background air (< -500 HU) to measure actual tissue density
    tissue = arr[arr > -500]
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

    # Si el percentil 10 cae en rango graso, hay una zona hipodensa significativa (posible lipoma)
    if HU_GRASA_MIN <= p10 <= HU_GRASA_MAX:
        return f"ZONA GRASA DETECTADA (p10={p10:.0f} HU, media={mean_hu:.0f} HU) — compatible con lipoma/tejido adiposo"
    elif HU_GRASA_MIN <= mean_hu <= HU_GRASA_MAX:
        return f"TEJIDO GRASO ({mean_hu:.0f} HU) — compatible con lipoma/tejido adiposo"
    elif HU_AGUA_MIN <= mean_hu <= HU_AGUA_MAX:
        return f"DENSIDAD AGUA ({mean_hu:.0f} HU) — compatible con quiste/líquido"
    elif HU_TEJIDO_MIN <= mean_hu <= HU_TEJIDO_MAX:
        return f"TEJIDO BLANDO ({mean_hu:.0f} HU) — compatible con músculo/tejido blando"
    elif mean_hu > 100:
        return f"DENSIDAD ALTA ({mean_hu:.0f} HU) — compatible con hueso/calcificación"
    else:
        return f"DENSIDAD AIRE ({mean_hu:.0f} HU)"


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


def _dicom_to_pil(arr_hu: np.ndarray, window: str = "pulmon") -> Image.Image:
    if window == "mediastino":
        arr = _apply_windowing(arr_hu, WINDOW_CENTER_MEDIASTINO, WINDOW_WIDTH_MEDIASTINO)
    elif window == "grasa":
        arr = _apply_windowing(arr_hu, WINDOW_CENTER_GRASA, WINDOW_WIDTH_GRASA)
    else:
        arr = _apply_windowing(arr_hu, WINDOW_CENTER_PULMON, WINDOW_WIDTH_PULMON)

    img = Image.fromarray(arr).convert("RGB")
    img = img.resize((256, 256), Image.LANCZOS)
    return _add_orientation_markers(img)


def _normalizar_caracterizaciones(stats_lista: list) -> list:
    if not stats_lista:
        return stats_lista
    n_grasa = sum(1 for s in stats_lista if "ZONA GRASA DETECTADA" in s.get("caracterizacion", ""))
    if n_grasa / len(stats_lista) > 0.5:
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

        print(f"[DICOM] {len(series_meta)} series detectadas:")
        for uid, slices in series_meta.items():
            desc = getattr(slices[0][1], "SeriesDescription", "sin descripción")
            print(f"[DICOM]   UID={uid} | {len(slices)} slices | desc='{desc}'")

        # Usar la serie con más slices
        serie_principal_meta = max(series_meta.values(), key=len)
        desc_principal = getattr(serie_principal_meta[0][1], "SeriesDescription", "sin descripción")
        print(f"[DICOM] Serie seleccionada: {len(serie_principal_meta)} slices | '{desc_principal}'")

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
        zones = [
            (int(total * 0.10), int(total * 0.35)),
            (int(total * 0.35), int(total * 0.65)),
            (int(total * 0.65), int(total * 0.90)),
        ]
        counts = _calcular_counts(n_cortes, pesos)
        nombres_seleccionados = []
        for (start, end), count in zip(zones, counts):
            end = max(end, start + 1)
            indices = np.linspace(start, end - 1, count, dtype=int)
            nombres_seleccionados.extend([serie_ordenada[idx][0] for idx in indices])

        # Paso 2: cargar pixels solo de los cortes seleccionados
        print(f"[DICOM] Cargando pixels de {len(nombres_seleccionados)} cortes seleccionados...")
        seleccionados = []
        for nombre in nombres_seleccionados:
            try:
                with zf.open(nombre) as f:
                    ds = pydicom.dcmread(io.BytesIO(f.read()), force=True)
                    if hasattr(ds, "pixel_array"):
                        seleccionados.append(ds)
            except Exception:
                continue
        print(f"[DICOM] {len(seleccionados)} cortes con pixels cargados")

        # Construir series_info desde metadatos
        series = {uid: [ds for _, ds in slices] for uid, slices in series_meta.items()}

        hu_stats_lista = []
        imagenes_pulmon      = []
        imagenes_tejido      = []
        imagenes_grasa       = []

        for i, ds in enumerate(seleccionados):
            try:
                print(f"[DICOM] Procesando corte {i + 1}/{len(seleccionados)}...")
                arr_hu = _hu_array(ds)
                stats  = _hu_stats(arr_hu)
                stats["caracterizacion"] = _caracterizar_tejido(stats)
                hu_stats_lista.append(stats)

                imagenes_pulmon.append(_dicom_to_pil(arr_hu, "pulmon"))
                imagenes_tejido.append(_dicom_to_pil(arr_hu, "mediastino"))
                imagenes_grasa.append(_dicom_to_pil(arr_hu, "grasa"))
                print(f"[DICOM]   → media={stats['mean']} HU | p10={stats['p10']} HU | {stats['caracterizacion']}")
            except Exception as e:
                print(f"[DICOM]   ✗ Error en corte {i + 1}: {e}")
                continue

        hu_stats_lista = _normalizar_caracterizaciones(hu_stats_lista)
        print(f"[DICOM] Procesamiento completado: {len(imagenes_pulmon)} cortes OK")

    series_info = [
        {"uid": uid, "n_slices": len(sl), "desc": getattr(sl[0], "SeriesDescription", "sin descripción")}
        for uid, sl in series.items()
    ]

    return {
        "pulmon":        imagenes_pulmon,
        "tejido_blando": imagenes_tejido,
        "grasa":         imagenes_grasa,
        "series_info":   series_info,
        "hu_stats":      hu_stats_lista,
        "n_cortes":      len(imagenes_pulmon),
        "counts_zona":   counts_zona,
        "pesos_zona":    pesos,
    }
