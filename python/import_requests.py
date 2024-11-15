import mysql.connector
import requests
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

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

    # Ruta base de Descargas
    download_base_dir = os.path.expanduser("~/Downloads")

    # Procesar cada registro
    for id_caso, enlacedicom, created_at in cursor.fetchall():
        # Crear una carpeta para cada caso en Descargas
        caso_dir = os.path.join(download_base_dir, str(id_caso))
        os.makedirs(caso_dir, exist_ok=True)
        print(f"\nCreando carpeta para el caso {id_caso} en: {caso_dir}")
        print(f"URL de Dropbox inicial: {enlacedicom}")

        # Cambiar `dl=0` a `raw=1` en la URL para descarga directa
        download_url = enlacedicom.replace('?dl=0', '?raw=1')

        try:
            # Descargar el archivo desde Dropbox
            response = requests.get(download_url, stream=True, timeout=10)
            response.raise_for_status()

            # Intentar obtener el nombre del archivo desde el encabezado `Content-Disposition`
            filename = None
            content_disposition = response.headers.get("Content-Disposition")
            if content_disposition:
                # Extraer el nombre del archivo del encabezado
                filename = content_disposition.split("filename=")[-1].strip('"')
                print(f"Nombre del archivo obtenido desde Content-Disposition: {filename}")
            if not filename:
                # Si no se encuentra el nombre, usar el nombre de la URL
                parsed_url = urlparse(download_url)
                filename = os.path.basename(parsed_url.path)
                print(f"Nombre del archivo obtenido desde la URL: {filename}")

            # Definir la ruta completa donde se guardará el archivo
            file_path = os.path.join(caso_dir, filename)

            # Guardar el archivo en la ubicación especificada
            with open(file_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            print(f"Archivo descargado correctamente en: {file_path}")

        except requests.exceptions.RequestException as e:
            print(f"Error al intentar descargar el archivo para el caso {id_caso}: {e}")
            # Registro en un log de errores
            with open("download_errors.log", "a") as log_file:
                log_file.write(f"{datetime.now()} - Error en caso {id_caso}: {e}\n")
        except Exception as e:
            print(f"Error inesperado para el caso {id_caso}: {e}")

finally:
    # Cerrar la conexión a la base de datos
    if connection.is_connected():
        cursor.close()
        connection.close()
        print("Conexión a la base de datos cerrada.")
