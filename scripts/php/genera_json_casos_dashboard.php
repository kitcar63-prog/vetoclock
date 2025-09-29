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

// Asegurarse de que la conexión use UTF-8
$conn->set_charset("utf8mb4");

// Configurar nombres de meses en español
if (!$conn->query("SET lc_time_names = 'es_ES'")) {
    echo "Advertencia: no se pudo establecer lc_time_names a 'es_ES'.<br>";
}

// Consulta SQL
$sql = "SELECT 
    dg.nombre AS nombre_grupo,
    cl.empresa, 
    DATE_FORMAT(c.fecha, '%Y-%m') AS mes_anio,
    COUNT(DISTINCT c.id_caso) AS total_casos,
    COALESCE(u.nombre, 'No asignado') AS nombre_usuario,
    CASE 
        WHEN c.urgencia_abierto IS NOT NULL THEN 'URGENCIA'
        ELSE 'NORMAL'
    END AS tipo_urgencia,
    c.tipo_locale,
    SUM(c.coste) AS total_coste,
    SUM(c.precio) AS total_precio,
    (SUM(c.precio) - SUM(c.coste)) AS margen
FROM grupos_dashboard gd
JOIN dashboard_grupos dg ON gd.grupo_dashboard_id = dg.id
JOIN clientes cl ON gd.id_cliente = cl.id_cliente
JOIN casos c ON c.cliente_id = cl.id_cliente
LEFT JOIN usuarios u ON c.asignado_a = u.id
WHERE estado IN ('Abierto', 'Cerrado')  
GROUP BY cl.empresa, dg.nombre, mes_anio, u.nombre, tipo_urgencia, c.tipo_locale
ORDER BY mes_anio DESC, dg.nombre, cl.empresa;";


$result = $conn->query($sql);

// Comprobar si la consulta falló
if (!$result) {
    die("Error en la consulta SQL: " . $conn->error);
}

// Convertir resultado a array y asegurar UTF-8
$datos = [];

while ($row = $result->fetch_assoc()) {
    // Convertimos todos los valores del array a UTF-8
    $utf8_row = array_map(function($value) {
        return is_string($value) ? mb_convert_encoding($value, 'UTF-8', 'auto') : $value;
    }, $row);
    $datos[] = $utf8_row;
}

// Guardar copia para depuración
file_put_contents(__DIR__ . '/debug_datos.txt', print_r($datos, true));

// Verificar si hay datos
if (empty($datos)) {
    die("La consulta se ejecutó correctamente pero no devolvió resultados.");
}

// Convertir a JSON
$json = json_encode($datos, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);

if ($json === false) {
    die("Error al convertir a JSON: " . json_last_error_msg());
}

// Ruta del archivo
$filename = __DIR__ . '/casos_dashboard.json';

// Verificar si se puede escribir
if (!is_writable(__DIR__)) {
    die("No se puede escribir en el directorio: " . __DIR__);
}

// Guardar archivo
if (file_put_contents($filename, $json) === false) {
    die("Error al guardar el archivo JSON.");
}

echo "Archivo JSON generado correctamente en: $filename";

?>
