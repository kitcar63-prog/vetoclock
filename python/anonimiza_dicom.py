import pydicom
import zipfile
import os
import shutil

def descomprimir_zip(ruta_zip, carpeta_destino):
    with zipfile.ZipFile(ruta_zip, 'r') as zip_ref:
        zip_ref.extractall(carpeta_destino)
    print(f"Descomprimido en: {carpeta_destino}")

def anonimizar_dicom_en_carpeta(carpeta):
    for root, dirs, files in os.walk(carpeta):
        for file in files:
            if file.lower().endswith(".dcm"):
                ruta_dicom = os.path.join(root, file)
                dicom_data = pydicom.dcmread(ruta_dicom)
                
                # Anonimizar datos sensibles
                etiquetas_a_eliminar = [
                    "PatientID", "PatientName", "PatientBirthDate", "PatientSex", "InstitutionName",
                    "ReferringPhysicianName", "StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate",
                    "StudyTime", "SeriesTime", "AcquisitionTime", "ContentTime", "AccessionNumber",
                    "OtherPatientIDs", "OtherPatientNames"
                ]
                for etiqueta in etiquetas_a_eliminar:
                    if etiqueta in dicom_data:
                        dicom_data.data_element(etiqueta).value = "ANONYMIZED"

                # Guardar el archivo DICOM anonimizado
                dicom_data.save_as(ruta_dicom)
                print(f"Anonimizado: {ruta_dicom}")

def comprimir_carpeta(carpeta_origen, archivo_zip_destino):
    with zipfile.ZipFile(archivo_zip_destino, 'w') as zipf:
        for root, dirs, files in os.walk(carpeta_origen):
            for file in files:
                ruta_completa = os.path.join(root, file)
                zipf.write(ruta_completa, os.path.relpath(ruta_completa, carpeta_origen))
    print(f"Archivo ZIP creado en: {archivo_zip_destino}")

# Ejemplo de uso
ruta_zip = "ruta/al/archivo.zip"
carpeta_temporal = "ruta/al/carpeta_temporal"
archivo_zip_anonimizado = "ruta/al/archivo_anonimizado.zip"

# Descomprimir, anonimizar y recomprimir
descomprimir_zip(ruta_zip, carpeta_temporal)
anonimizar_dicom_en_carpeta(carpeta_temporal)
comprimir_carpeta(carpeta_temporal, archivo_zip_anonimizado)

# Limpiar carpeta temporal
shutil.rmtree(carpeta_temporal)
