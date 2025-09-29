<?php

// Mostrar errores
ini_set('display_errors', 1);
ini_set('display_startup_errors', 1);
error_reporting(E_ALL);

// Configuración de la base de datos

$servername = "";
$username = "";
$password = "";
$database = "";

// Crear conexión
$conn = new mysqli($servername, $username, $password, $database);

// Verificar conexión
if ($conn->connect_error) {
    die("Conexión fallida: " . $conn->connect_error);
}

// Asegurar codificación UTF-8
$conn->set_charset("utf8mb4");

// Consulta SQL para calcular el tiempo medio de respuesta excluyendo sábados y domingos
$sql = "SELECT 
    u.nombre AS asignado_nombre,
    COUNT(c.id_caso) AS total_casos,
    ROUND(AVG(
        (SELECT SUM(
            CASE 
                WHEN WEEKDAY(DATE_ADD(c.created_at, INTERVAL n DAY)) < 5 THEN 24 ELSE 0 
            END
        ) 
        FROM (
            SELECT 0 AS n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 
            UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11 UNION SELECT 12 UNION SELECT 13
            UNION SELECT 14 UNION SELECT 15 UNION SELECT 16 UNION SELECT 17 UNION SELECT 18 UNION SELECT 19 UNION SELECT 20
            UNION SELECT 21 UNION SELECT 22 UNION SELECT 23 UNION SELECT 24 UNION SELECT 25 UNION SELECT 26 UNION SELECT 27
            UNION SELECT 28 UNION SELECT 29 UNION SELECT 30 UNION SELECT 31 UNION SELECT 32 UNION SELECT 33 UNION SELECT 34
        ) days
        WHERE DATE_ADD(c.created_at, INTERVAL n DAY) <= c.updated_voc_at
        )
    ), 2) AS tiempo_medio_horas
FROM casos c
LEFT JOIN usuarios u ON c.asignado_a = u.id
WHERE c.created_at BETWEEN '2024-01-01' AND '2025-04-30 23:59:59'
AND c.updated_voc_at IS NOT NULL  
AND c.urgencia_abierto IS NULL
AND WEEKDAY(c.created_at) < 5
GROUP BY u.nombre  
ORDER BY total_casos DESC;";

$result = $conn->query($sql);

// Comprobar si la consulta falló
if (!$result) {
    die("Error en la consulta SQL: " . $conn->error);
}

// Convertir resultado a array con codificación correcta
$datos = [];

while ($row = $result->fetch_assoc()) {
    $utf8_row = array_map(function($value) {
        return is_string($value) ? mb_convert_encoding($value, 'UTF-8', 'auto') : $value;
    }, $row);
    $datos[] = $utf8_row;
}

// Guardar copia para depuración
file_put_contents(__DIR__ . '/debug_tiempo_respuesta.txt', print_r($datos, true));

// Verificar si hay datos
if (empty($datos)) {
    die("La consulta no devolvió resultados.");
}

// Convertir a JSON
$json = json_encode($datos, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);

if ($json === false) {
    die("Error al convertir a JSON: " . json_last_error_msg());
}

// Guardar en un archivo JSON
$filename = __DIR__ . '/tiempo_medio_respuesta.json';

if (file_put_contents($filename, $json) === false) {
    die("Error al guardar el archivo JSON.");
}

echo "Archivo JSON generado correctamente en: $filename";

?>
