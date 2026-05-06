import base64
import io
import anthropic
from PIL import Image
import config

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

MODEL = "claude-opus-4-7"


def _imagen_a_base64(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")


def _construir_prompt(caso: dict, casos_similares: list, hu_stats: list, n_cortes: int = 20, counts_zona: list = None) -> str:
    contexto = f"""Eres un especialista en diagnóstico por imagen veterinaria.
Vas a analizar un TC de región torácica de un {caso['especie']} ({caso.get('raza', '')}, {caso.get('edad', '')} años, {caso.get('peso', '')} kg).

MOTIVO DE CONSULTA Y PRESENTACIÓN CLÍNICA:
{caso.get('presentacion', 'No disponible')}

ANTECEDENTES:
{caso.get('antecedentes', 'No disponible')}

TRATAMIENTOS PREVIOS:
{caso.get('tratamientos', 'No disponible')}
"""

    if hu_stats:
        contexto += "\n\nESTADÍSTICAS DE DENSIDAD (Unidades Hounsfield) POR CORTE:\n"
        for i, s in enumerate(hu_stats, 1):
            contexto += (
                f"  Corte {i}: media={s['mean']} HU | p10={s['p10']} HU | p25={s['p25']} HU | "
                f"p75={s['p75']} HU | p90={s['p90']} HU | min={s['min']} | max={s['max']} | "
                f"{s['caracterizacion']}\n"
            )
        contexto += """
REFERENCIA DE DENSIDADES HU:
  - Aire: -1000 HU
  - Grasa/Tejido adiposo: -200 a -50 HU  ← LIPOMA si masa bien delimitada y sin realce
  - Agua/Quiste: -20 a +20 HU
  - Tejido blando/músculo: +20 a +80 HU
  - Sangre: +50 a +80 HU
  - Hueso esponjoso: +200 a +400 HU
  - Hueso cortical: +400 a +1000 HU

INTERPRETACIÓN DE PERCENTILES:
  - La media del corte mezcla todos los tejidos de la slice (músculo, grasa, vísceras).
  - El PERCENTIL 10 (p10) indica la densidad de la zona MÁS HIPODENSA del corte.
    Si p10 está entre -200 y -50 HU → hay tejido graso significativo en ese corte (posible lipoma).
  - El PERCENTIL 25 (p25) amplía esa zona hipodensa: si también cae en rango graso, la lesión es extensa.
  - Cuando p10 o p25 están en rango graso pero la media no, significa que la lesión grasa coexiste
    con tejido normal circundante — esto es el patrón típico de un LIPOMA encapsulado.

ORIENTACIÓN ANATÓMICA — MUY IMPORTANTE:
Las imágenes DICOM siguen la CONVENCIÓN RADIOLÓGICA estándar:
  - Lo que aparece a la DERECHA de la imagen = lado IZQUIERDO del paciente (marcado con "L")
  - Lo que aparece a la IZQUIERDA de la imagen = lado DERECHO del paciente (marcado con "R")
  Las imágenes tienen marcadores "R" y "L" en los bordes laterales para confirmarlo.
  Cuando describas lateralidad (masa izquierda/derecha, derrame izquierdo/derecho, etc.) usa SIEMPRE
  la lateralidad del PACIENTE, no la del observador.

IMPORTANTE: Se adjuntan cortes en TRES ventanas diferentes:
  - Primeros {n_cortes} cortes: ventana PULMÓN (W=1500, L=-600)
  - Siguientes {n_cortes} cortes: ventana TEJIDO BLANDO (W=400, L=40)
  - Últimos {n_cortes} cortes: ventana GRASA (W=400, L=-100) — clave para detectar lipomas
    En ventana grasa, un lipoma aparece brillante/blanco bien delimitado sobre fondo gris oscuro.

DISTRIBUCIÓN DE LOS {n_cortes} CORTES (igual en las 3 ventanas):
  - Cortes 1-{counts_zona[0]}: ZONA CRANEAL del tórax ({counts_zona[0]} cortes — entrada torácica, lóbulos craneales, linfonodos mediastínicos craneales)
  - Cortes {counts_zona[0]+1}-{counts_zona[0]+counts_zona[1]}: ZONA MEDIA del tórax ({counts_zona[1]} cortes — hilio pulmonar, corazón, carina, lóbulos medios)
  - Cortes {counts_zona[0]+counts_zona[1]+1}-{n_cortes}: ZONA CAUDAL del tórax ({counts_zona[2]} cortes — lóbulos caudales, diafragma)
  Muestreo adaptado al motivo de consulta para maximizar cobertura en las zonas de mayor interés clínico.
"""

    if casos_similares:
        contexto += "\n\nCASOS SIMILARES PREVIAMENTE DIAGNOSTICADOS (usa como referencia):\n"
        for i, c in enumerate(casos_similares, 1):
            contexto += f"""
--- CASO SIMILAR {i} ---
Paciente: {c['especie']}, {c.get('raza', '')}, {c.get('edad', '')} años
Presentación: {c.get('presentacion', '')}
Informe del especialista: {c.get('area_uno', '')}
"""

    contexto += """

GUÍA DE ANÁLISIS — presta atención especial a estos puntos:

MASAS HIPODENSAS (lipoma vs liposarcoma):
  - Si p10 está consistentemente entre -140 y -200 HU en varios cortes, clasificar como LIPOMA SIMPLE probable.
  - Solo elevar a "lipoma infiltrativo" o "liposarcoma" si hay invasión franca de planos musculares o márgenes francamente irregulares visibles en imagen.
  - Sin imágenes post-contraste disponibles, NO asumir infiltración por presencia de septos finos — los lipomas simples pueden tener septos fibróticos internos.

LINFONODOS — diferencia obligatoria:
  - Linfonodos AXILARES: en la fosa axilar, lateral al tórax, ipsilaterales a la masa.
  - Linfonodos MEDIASTÍNICOS CRANEALES: paratraqueales/prevasculares, en el mediastino craneal.
  - Linfonodos MEDIASTÍNICOS CAUDALES: en la bifurcación traqueal (carina).
  - Evalúa y nombra cada grupo por separado. No los confundas.

HALLAZGOS RESPIRATORIOS — busca activamente:
  - BRONQUIOMALACIA: colapso dinámico de bronquios lobulares (especialmente lóbulo craneal izquierdo). Se ve como estrechamiento o colapso del lumen bronquial.
  - ATELECTASIA VENTRAL: colapso/consolidación en regiones ventrales, frecuente en pacientes bajo anestesia general. No confundir con lesión primaria.
  - PATRÓN INTERSTICIAL difuso: puede ser artefacto de posición/anestesia.

PARED TORÁCICA Y MEDIASTINO — evalúa en ventana TEJIDO BLANDO:
  - Musculatura torácica (dorsal ancho, intercostales, pectorales, serrato): compara simetría bilateral, busca masas, colecciones o alteraciones focales.
  - Tejido subcutáneo: masas encapsuladas o colecciones. Distingue grasa fisiológica distribuida (sin efecto masa) de una lesión organizada.
  - Mediastino craneal y caudal: colecciones fluidas (0-20 HU = quiste/fluido), masas, estructuras con contorno propio. No omitas estructuras pequeñas con morfología definida.
  - Espacio pleural y pericárdico: confirma ausencia de derrame aunque sea mínimo.

ESTRUCTURAS ÓSEAS — evalúa en ventana TEJIDO BLANDO:
  - Costillas, esternebras y vértebras torácicas en el campo de estudio: lesiones osteolíticas, osteoproliferativas, irregularidades corticales o fracturas.
  - En estadiajes oncológicos, la ausencia de lesiones óseas torácicas es un hallazgo a reportar explícitamente.

Analiza los cortes del TC torácico que se adjuntan y genera un informe diagnóstico detallado siguiendo esta estructura:

1. DESCRIPCIÓN DE HALLAZGOS: Describe sistemáticamente lo que observas en cada uno de estos apartados:
   - Parénquima pulmonar: nódulos, masas, patrón intersticial, consolidaciones, aireación por lóbulos
   - Árbol traqueobronquial y vascularización pulmonar
   - Mediastino: linfonodos (craneales y caudales por separado), colecciones fluidas, quistes, masas
   - Pleura y cavidad pleural
   - Estructuras cardiovasculares (corazón, grandes vasos, pericardio)
   - Pared torácica: musculatura y tejido subcutáneo (simetría, masas, colecciones focales)
   - Caja torácica ósea: costillas, esternebras, vértebras torácicas visibles

2. INTERPRETACIÓN: Interpreta los hallazgos en el contexto clínico del paciente.

3. CONCLUSIONES: Resume los hallazgos principales y su probable significado clínico.

Sé preciso, usa terminología médica veterinaria apropiada, y basa tu diagnóstico en lo que realmente observas en las imágenes."""

    return contexto


def generar_informe(caso: dict, resultado_dicom: dict, casos_similares: list) -> str:
    hu_stats    = resultado_dicom.get("hu_stats", [])
    n_cortes    = resultado_dicom.get("n_cortes", 20)
    counts_zona = resultado_dicom.get("counts_zona", [7, 7, 6])
    prompt      = _construir_prompt(caso, casos_similares, hu_stats, n_cortes, counts_zona)

    content = [{"type": "text", "text": prompt}]

    for ventana, etiqueta in [("pulmon", "VENTANA PULMÓN"), ("tejido_blando", "VENTANA TEJIDO BLANDO"), ("grasa", "VENTANA GRASA")]:
        content.append({"type": "text", "text": f"\n--- {etiqueta} ---"})
        for img in resultado_dicom.get(ventana, []):
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": _imagen_a_base64(img),
                },
            })

    content.append({
        "type": "text",
        "text": "Por favor, genera el informe diagnóstico basándote en los cortes del TC y el contexto clínico."
    })

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    return response.content[0].text
