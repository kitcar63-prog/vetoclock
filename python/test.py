import mysql.connector
import requests
import os
from datetime import datetime, timedelta

# Configuración de la conexión a la base de datos
db_config = {
    'user': 'root',
    'password': '',
    'host': 'localhost',
    'database': 'BBDD'
}

try:
    # Conexión a la base de datos
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()

    # Obtener la fecha de ayer en el formato adecuado
    ayer = datetime.now() - timedelta(days=1)
    fecha_ayer = ayer.strftime('%Y-%m-%d')

    # Consulta SQL para obtener los registros de ayer que empiecen con "https://www.dropbox"
    query = """
        SELECT `id_caso`, `enlacedicom`, `created_at`
        FROM `casostac`
        WHERE DATE(`created_at`) = %s
        AND `enlacedicom` LIKE 'https://www.dropbox%%'
        LIMIT 5;
    """
    cursor.execute(query, (fecha_ayer,))

    # Procesar cada registro
    for id_caso, enlacedicom, created_at in cursor.fetchall():
        # Cambiar `dl=0` a `raw=1` en la URL para descarga directa
        download_url = enlacedicom.replace('?dl=0', '?raw=1')
        print(f"\nProbando descarga para el caso {id_caso}: {download_url}")

        try:
            # Realizar una solicitud para comprobar la conexión
            response = requests.get(download_url, stream=True, timeout=10)
            print(f"Código de estado de la respuesta: {response.status_code}")
            print(f"Tamaño del contenido: {len(response.content)} bytes")

            # Verificar si la respuesta es HTML
            content_type = response.headers.get("Content-Type", "")
            if "text/html" in content_type:
                print("La respuesta parece ser HTML en lugar del archivo.")
            else:
                print("La respuesta parece ser un archivo.")

            # Opcional: imprimir los primeros bytes del contenido para análisis
            print("Contenido inicial de la respuesta:", response.content[:100])

        except requests.exceptions.RequestException as e:
            print(f"Error al intentar acceder a la URL para el caso {id_caso}: {e}")

finally:
    # Cerrar la conexión a la base de datos
    if connection.is_connected():
        cursor.close()
        connection.close()
        print("Conexión a la base de datos cerrada.")
