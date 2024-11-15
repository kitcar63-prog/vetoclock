# Este programa lee todos los casos del día anterior, cuyos enlaces dicom, sean por dropbox.
# antes de ejecutar, reactivar el entorno en el terminal: source myenv/bin/activate


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

# Conexión a la base de datos
connection = mysql.connector.connect(**db_config)
cursor = connection.cursor()

# Obtener la fecha de ayer en el formato adecuado
ayer = datetime.now() - timedelta(days=1)
fecha_ayer = ayer.strftime('%Y-%m-%d')

# Consulta SQL para obtener un máximo de 5 registros de ayer que empiecen con "https://www.dropbox.com"
query = """
    SELECT `id_caso`, `enlacedicom`, `created_at`
    FROM `casostac`
    WHERE DATE(`created_at`) = %s
    AND `enlacedicom` LIKE 'https://www.dropbox.com%%'
    LIMIT 5;
"""
cursor.execute(query, (fecha_ayer,))

# Ruta de la carpeta de Descargas
download_base_dir = os.path.expanduser("~/Downloads")

# Procesar cada registro
for id_caso, enlacedicom, created_at in cursor.fetchall():
    # Crear una carpeta para cada caso en Descargas
    caso_dir = os.path.join(download_base_dir, str(id_caso))
    os.makedirs(caso_dir, exist_ok=True)
    print(f"\nCreando carpeta: {caso_dir}")

    # Modificar `dl=0` a `dl=1` en el enlace para permitir la descarga directa
    download_url = enlacedicom.replace('dl=0', 'dl=1')
    print(f"URL modificada para descarga: {download_url}")

    # Extraer el nombre del archivo ZIP desde la URL `enlacedicom`
    parsed_url = urlparse(enlacedicom)
    filename = os.path.basename(parsed_url.path)  # Esto toma el último componente de la ruta como nombre de archivo
    print(f"Nombre del archivo ZIP extraído de enlacedicom: {filename}")

    # Definir la ruta completa donde se guardará el archivo con el nombre exacto
    file_path = os.path.join(caso_dir, filename)

    # Descargar el archivo enlacedicom en la carpeta del caso
    try:
        response = requests.get(download_url, stream=True)
        if response.status_code == 200:
            with open(file_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            print(f"Archivo descargado correctamente en: {file_path}")
        else:
            print(f"Error al descargar el archivo para el caso {id_caso}. Código de estado:", response.status_code)
    except Exception as e:
        print(f"Error al descargar el archivo para el caso {id_caso}: {e}")

# Cerrar la conexión a la base de datos
cursor.close()
connection.close()
