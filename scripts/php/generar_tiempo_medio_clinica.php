<?php
/**
 * ============================================================================
 *  Nombre:       gen_media_horas_por_cliente_y_dia.php
 *  Propósito:    Generar un JSON con la media diaria de horas (ajustada por reglas
 *                de negocio) entre la creación de un caso y el PRIMER informe del
 *                caso, agregada por cliente y día de creación del caso.
 *
 *  Descripción:
 *    - Extrae, para cada cliente y día (DATE(casos.created_at)), la media de horas
 *      entre casos.created_at y el PRIMER informes.created_at de cada caso
 *      (se usa MIN(informes.created_at) por caso).
 *    - Aplica reglas de negocio:
 *         * Si el caso entró Jueves o Viernes y la diferencia > 48h, restar 48h.
 *         * Si el caso entró Miércoles y la diferencia > 72h, restar 48h.
 *    - Excluye urgencias: solo casos con ca.urgencia_abierto IS NULL.
 *    - Solo se computan casos con informe y con informe.created_at >= caso.created_at.
 *
 *  Tablas implicadas:
 *    - casos (id_caso, cliente_id, created_at, urgencia_abierto, ...)
 *    - clientes (id_cliente, empresa, ...)
 *    - informes (caso_id, created_at, ...)
 *
 *  Entradas (CLI):
 *    - Arg1: fecha_inicio  (YYYY-MM-DD)  -> incluida
 *    - Arg2: fecha_fin     (YYYY-MM-DD)  -> exclusiva
 *    Ejemplos:
 *      php gen_media_horas_por_cliente_y_dia.php 2024-01-01 2025-01-01
 *      php gen_media_horas_por_cliente_y_dia.php $(date -d '90 days ago' +%F) $(date -d 'tomorrow' +%F)
 *
 *  Salida:
 *    - Archivo JSON (array plano) en el mismo directorio:
 *        media_horas_por_cliente_y_dia.json
 *    - Estructura de cada objeto:
 *        {
 *          "id_cliente": "42",
 *          "empresa": "Albeitar 24h S.L.",
 *          "caso_creado": "2024-01-07",
 *          "casos_del_dia": "3",
 *          "media_horas_ajustada_dia": "21.67",
 *          "fecha_inicio": "2024-01-01",
 *          "fecha_fin_exclusiva": "2025-01-01"
 *        }
 *
 *  Reglas y supuestos:
 *    - PRIMER informe por caso: MIN(informes.created_at).
 *    - Diferencia en horas = TIMESTAMPDIFF(SECOND, caso.created_at, primer_informe.created_at)/3600.
 *    - Ajustes de negocio aplicados sobre la diferencia ya calculada (ver arriba).
 *    - Se ignoran casos sin informe (al usar JOIN con subconsulta de informes).
 *    - Tipos de fecha/hora en BD: se asume DATETIME/TIMESTAMP válidos.
 *    - Zona horaria: se usa la del servidor MySQL/PHP (ajústala si procede).
 *
 *  Seguridad:
 *    - Recomendado cargar credenciales desde variables de entorno:
 *        DB_HOST, DB_USER, DB_PASS, DB_NAME
 *      (este script admite ambas: entorno o valores por defecto).
 *
 *  Rendimiento (sugerencias de índice):
 *    CREATE INDEX idx_casos_created_cliente_urg ON casos (created_at, cliente_id, urgencia_abierto);
 *    CREATE INDEX idx_informes_caso_created     ON informes (caso_id, created_at);
 *
 *  Cron (ejemplos):
 *    # Cada madrugada a las 02:05 para todo 2024
 *    5 2 * * * /usr/bin/php /ruta/gen_media_horas_por_cliente_y_dia.php 2024-01-01 2025-01-01
 *
 *  Autor:        (tu nombre o equipo)
 *  Versión:      1.0.0
 *  Última mod.:  2025-09-29
 * ============================================================================
 */

// Mostrar errores (desactiva en producción si lo prefieres)
ini_set('display_errors', 1);
ini_set('display_startup_errors', 1);
error_reporting(E_ALL);

// -------------------- Parámetros --------------------
// Uso CLI: php gen_media_horas_por_cliente_y_dia.php 2024-01-01 2025-01-01
$tz    = new DateTimeZone('Europe/Madrid');
$f_ini = $argv[1] ?? '2024-01-01'; // incluido
// Fin EXCLUSIVO: si no se indica, por defecto = AYER
if (isset($argv[2])) {
    $f_fin = $argv[2];
} else {
    $f_fin = (new DateTime('yesterday', $tz))->format('Y-m-d'); // exclusivo
}
// -------------------- Conexión BD --------------------
// Intenta leer de variables de entorno y, si no existen, usa los valores por defecto.
$servername = getenv('DB_HOST') ?: "";
$username   = getenv('DB_USER') ?: "";
$password   = getenv('DB_PASS') ?: "";
$database   = getenv('DB_NAME') ?: "";

$conn = new mysqli($servername, $username, $password, $database);
if ($conn->connect_error) {
    die("Conexión fallida: " . $conn->connect_error);
}
$conn->set_charset("utf8mb4");

// (opcional) nombres de meses en español; no afecta al cálculo
$conn->query("SET lc_time_names = 'es_ES'");

// -------------------- SQL --------------------
$sql = "
SELECT
  cl.id_cliente,
  cl.empresa,
  DATE(ca.opened_at) AS caso_creado,        -- día del caso
  COUNT(*) AS casos_del_dia,                 -- nº de casos con informe ese día
  ROUND(
    AVG(
      CASE
        WHEN WEEKDAY(ca.opened_at) IN (3, 4)  -- Jue/Vie
             AND TIMESTAMPDIFF(SECOND, ca.opened_at, ui.created_at) > 48*3600
          THEN (TIMESTAMPDIFF(SECOND, ca.opened_at, ui.created_at) - 48*3600) / 3600
        WHEN WEEKDAY(ca.opened_at) = 2        -- Mié
             AND TIMESTAMPDIFF(SECOND, ca.opened_at, ui.created_at) > 72*3600
          THEN (TIMESTAMPDIFF(SECOND, ca.opened_at, ui.created_at) - 48*3600) / 3600
        ELSE TIMESTAMPDIFF(SECOND, ca.opened_at, ui.created_at) / 3600
      END
    )
  , 2) AS media_horas_ajustada_dia
FROM casos ca
JOIN clientes cl ON cl.id_cliente = ca.cliente_id
JOIN (
  SELECT caso_id, MIN(created_at) AS created_at   -- PRIMER informe del caso
  FROM informes
  GROUP BY caso_id
) ui ON ui.caso_id = ca.id_caso
WHERE ca.opened_at >= ?
  AND ca.opened_at <  ?
  AND ca.urgencia_abierto IS NULL
  AND ui.created_at >= ca.opened_at
GROUP BY cl.id_cliente, cl.empresa, DATE(ca.opened_at)
ORDER BY cl.empresa, caso_creado
";

// -------------------- Ejecutar --------------------
$stmt = $conn->prepare($sql);
if (!$stmt) {
    die("Error al preparar la consulta: " . $conn->error);
}
$stmt->bind_param('ss', $f_ini, $f_fin);

if (!$stmt->execute()) {
    die("Error al ejecutar la consulta: " . $stmt->error);
}

$res = $stmt->get_result();

// -------------------- Construir JSON (array plano) --------------------
$datos = [];
while ($row = $res->fetch_assoc()) {
    // Asegurar UTF-8 y convertir a strings para homogeneizar con tus otros JSON
    $empresa = is_string($row['empresa']) ? mb_convert_encoding($row['empresa'], 'UTF-8', 'auto') : $row['empresa'];

    $datos[] = [
        "id_cliente"               => (string)$row["id_cliente"],
        "empresa"                  => (string)$empresa,
        "caso_creado"              => (string)$row["caso_creado"], // YYYY-MM-DD
        "casos_del_dia"            => (string)$row["casos_del_dia"],
        "media_horas_ajustada_dia" => number_format((float)$row["media_horas_ajustada_dia"], 2, '.', ''),
        // Rango usado (útil para el dashboard)
        "fecha_inicio"             => (string)$f_ini,
        "fecha_fin_exclusiva"      => (string)$f_fin
    ];
}

// -------------------- Guardar archivo --------------------
$filename = __DIR__ . '/media_horas_por_cliente_y_dia.json';

$json = json_encode($datos, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
if ($json === false) {
    die("Error al convertir a JSON: " . json_last_error_msg());
}

if (!is_writable(__DIR__)) {
    die("No se puede escribir en el directorio: " . __DIR__);
}

if (file_put_contents($filename, $json) === false) {
    die("Error al guardar el archivo JSON.");
}

echo "OK: JSON generado en $filename\n";

// -------------------- Cerrar --------------------
$stmt->close();
$conn->close();
