import requests
import os

# URL de Dropbox con el parámetro `dl=1` para descarga directa
download_url = "https://www.dropbox.com/scl/fi/frm6kys82493et2j79wyn/Apata_Teo.zip?rlkey=9arus073w689sjvdq3zderga9&e=1&st=l9lob3xm&dl=1"

# Ruta donde se guardará el archivo
download_path = os.path.expanduser("~/Downloads/Apata_Teo.zip")

try:
    # Realizar la solicitud de descarga
    response = requests.get(download_url, stream=True)
    
    # Verificar si la solicitud fue exitosa
    if response.status_code == 200:
        with open(download_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        print(f"Archivo descargado correctamente en: {download_path}")
    else:
        print("Error al descargar el archivo. Código de estado:", response.status_code)
except Exception as e:
    print("Error al intentar descargar el archivo:", e)
