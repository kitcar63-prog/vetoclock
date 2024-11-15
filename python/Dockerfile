# Usa una imagen de Python con Selenium y Chrome
FROM selenium/standalone-chrome:latest

# Copia tu script a la imagen
COPY descarga_wetransfer.py /descarga_wetransfer.py

# Instala las dependencias necesarias
RUN pip install undetected-chromedriver

# Comando para ejecutar el script
CMD ["python3", "/descarga_wetransfer.py"]
