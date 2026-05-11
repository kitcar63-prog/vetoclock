import base64
import io
import anthropic
from PIL import Image
import config

MODEL = "claude-opus-4-7"


def _get_client():
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _imagen_a_base64(img) -> str:
    if isinstance(img, (bytes, bytearray)):
        return base64.standard_b64encode(img).decode("utf-8")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")


def _construir_prompt(caso: dict, casos_similares: list, hu_stats: list, n_cortes: int = 20, counts_zona: list = None) -> str:
    contexto = f"""Eres un asistente de imagen veterinaria. Tu función es producir una HOJA DE TRABAJO PRELIMINAR —
no un informe diagnóstico— para que un especialista la revise y valide sobre el estudio completo.

REGLAS DE LENGUAJE — OBLIGATORIAS:
1. DESCRIBE lo que observas. Nunca afirmes la AUSENCIA de algo que no puedas ver con certeza.
   ✗ PROHIBIDO: "no se identifica megaesófago", "se descarta neumotórax", "esófago normal"
   ✓ CORRECTO: "esófago: calibre aparente conservado en los cortes disponibles [VALORACIÓN LIMITADA — verificar en estudio completo]"
2. Marca cada observación con su nivel de visibilidad:
   [BIEN VISUALIZADO] — hallazgo claro en múltiples cortes con ventana adecuada
   [VALORACIÓN LIMITADA] — visible parcialmente, muestreo escaso, ventana subóptima o sin contraste
   [NO EVALUABLE] — fuera del campo de muestreo disponible
3. Nunca uses "descartado", "ausente" o "sin hallazgos" sin añadir "en los cortes disponibles".
4. Para cualquier estructura que requiera contraste para caracterización definitiva, indica siempre "estudio sin contraste — valoración limitada".

Paciente: {caso['especie']} ({caso.get('raza', '')}, {caso.get('edad', '')} años, {caso.get('peso', '')} kg).

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

IMPORTANTE: Se adjuntan cortes en DOS ventanas:
  - Primeros {n_cortes} cortes: ventana PULMÓN (W=1500, L=-600) — parénquima, bronquios, neumotórax
  - Siguientes {n_cortes} cortes: ventana TEJIDO BLANDO (W=400, L=40) — masas, mediastino, vasos, pleura

DISTRIBUCIÓN DE LOS {n_cortes} CORTES (igual en las 2 ventanas):
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

REFERENCIA RÁPIDA PARA EL ANÁLISIS:

MASAS HIPODENSAS: Si p10 entre -140 y -200 HU en varios cortes → LIPOMA SIMPLE probable [VALORACIÓN LIMITADA sin contraste].
  Solo indica "infiltrativo" si hay invasión franca visible de planos musculares. Septos finos no implican infiltración.

LINFONODOS — nombra cada grupo por separado:
  Axilares (fosa axilar, lateral al tórax) / Mediastínicos craneales (paratraqueales) / Mediastínicos caudales (carina).

HALLAZGOS A BUSCAR ACTIVAMENTE:
  - TORSIÓN LOBAR (urgencia quirúrgica): patrón vesicular + interrupción ABRUPTA del bronquio lobar. Lóbulo más frecuente en gatos: medio derecho.
  - NEUMOTÓRAX: gas libre dorsal (HU ~ -1000) sin trama vascular. Distinguir de enfisema subcutáneo y de aire intrabronquial.
  - MEGAESÓFAGO: esófago distendido con contenido aéreo/fluido, paredes finas. Causa frecuente de bronconeumonía recurrente. Buscar siempre.
  - ATELECTASIA VENTRAL: artefacto frecuente bajo anestesia. No confundir con lesión primaria.

LIMITACIONES INHERENTES A ESTE ESTUDIO (incluir en cada apartado correspondiente):
  - Estudio SIN CONTRASTE: no es posible valorar realce, permeabilidad vascular ni caracterización tisular definitiva.
  - Muestreo de {n_cortes} cortes de un volumen completo: hallazgos entre cortes pueden no estar representados.
  - Solo plano axial: sin reconstrucciones coronales/sagitales para evaluación morfológica 3D.

---

Analiza los cortes adjuntos y genera la HOJA DE TRABAJO siguiendo EXACTAMENTE esta estructura:

## 1. OBSERVACIONES POR SISTEMA

Para cada estructura indica el nivel entre corchetes y describe lo que observas. Usa terminología médica veterinaria.
Si no es claramente visible, escribe lo que se aprecia y marca [VALORACIÓN LIMITADA — verificar en estudio completo].
NUNCA escribas "normal", "sin hallazgos" o "no se identifica X" sin el qualifier "en los cortes disponibles".

**Parénquima pulmonar** — evalúa CADA lóbulo individualmente:
  Lóbulo craneal derecho / Lóbulo medio derecho / Lóbulo caudal derecho / Lóbulo craneal izquierdo / Lóbulo caudal izquierdo
  Busca: consolidaciones, bronquiectasias, vidrio deslustrado, nódulos, patrón vesicular, interrupción bronquial abrupta.

**Árbol traqueobronquial**: tráquea y continuidad de cada bronquio lobar hasta su lóbulo destino.

**Vascularización pulmonar** [VALORACIÓN LIMITADA — sin contraste]: describe calibre visible. No concluyas normalidad vascular.

**Espacio pleural**: gas libre (descripción, lateralidad), líquido (estimación HU si visible).
  Nota: valores p10 muy negativos pueden corresponder a aire intrabronquial, no a neumotórax — correlacionar con imagen.

**Mediastino**: linfonodos craneales y caudales por separado (tamaño, morfología visible). Colecciones, masas.

**Tiroides y entrada torácica** [VALORACIÓN LIMITADA — zona craneal con muestreo escaso]:
  Describe lo que se aprecia en los cortes craneales disponibles. No afirmes simetría si no es claramente visible.

**Esófago** [VALORACIÓN LIMITADA — sin contraste, muestreo variable]:
  Describe el calibre y contenido observado en cada zona (craneal/media/caudal al nivel de la carina).
  NO afirmes "sin megaesófago" — describe lo que ves e indica "verificar calibre real en estudio completo".

**Estructuras cardiovasculares** [VALORACIÓN LIMITADA — sin contraste]:
  Tamaño y morfología cardíaca visible. Pericardio. No evalúes función.

**Pared torácica y tejido subcutáneo**: simetría muscular, masas, colecciones. Distingue grasa fisiológica de lesión organizada.

**Caja torácica ósea**: costillas, esternebras y vértebras torácicas visibles. Lesiones líticas u osteoproliferativas.

## 2. PATRONES IDENTIFICADOS

Lista los patrones radiológicos que observas con su distribución y extensión. No hagas diagnósticos etiológicos — describe patrones.
Ejemplo correcto: "Consolidación multifocal de distribución craneoventral bilateral" o "Bronquiectasias cilíndricas bilaterales de predominio caudal"

## 3. PUNTOS DE VERIFICACIÓN PARA EL ESPECIALISTA

Lista ordenada de lo que el especialista debe verificar en el estudio completo, de mayor a menor relevancia clínica.
Formato: ⚠️ [Estructura] — [Qué verificar específicamente] — [Por qué es relevante en este caso]

Incluye SIEMPRE esófago, estructuras con [VALORACIÓN LIMITADA] y zonas con hallazgos detectados.

## 4. PREGUNTAS CLÍNICAS

2-4 preguntas abiertas que el especialista debe responder al revisar el estudio completo, basadas en los hallazgos preliminares y la clínica del paciente. Estas preguntas guían la revisión, no la concluyen."""

    return contexto


def generar_informe(caso: dict, resultado_dicom: dict, casos_similares: list) -> str:
    imagenes_pulmon = resultado_dicom.get("pulmon", [])
    if not imagenes_pulmon:
        raise ValueError(
            "No hay imágenes DICOM disponibles. No se puede generar un informe sin cortes. "
            "Revisa que el DICOM se procesó correctamente."
        )

    hu_stats    = resultado_dicom.get("hu_stats", [])
    n_cortes    = resultado_dicom.get("n_cortes", 20)
    counts_zona = resultado_dicom.get("counts_zona", [7, 7, 6])
    prompt      = _construir_prompt(caso, casos_similares, hu_stats, n_cortes, counts_zona)

    content = [{"type": "text", "text": prompt}]

    # Enviamos solo ventana pulmón + tejido blando para reducir memoria
    for ventana, etiqueta in [("pulmon", "VENTANA PULMÓN"), ("tejido_blando", "VENTANA TEJIDO BLANDO")]:
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
        "text": "Por favor, genera la hoja de trabajo preliminar siguiendo exactamente la estructura indicada. Recuerda: describe lo que observas, marca el nivel de visibilidad de cada estructura, y nunca afirmes la ausencia de hallazgos sin el qualifier 'en los cortes disponibles'."
    })

    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    return response.content[0].text
