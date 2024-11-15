from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

options = Options()
options.add_argument("--private")  # Modo incógnito en Firefox

driver = webdriver.Firefox(options=options)

try:
    wetransfer_link = "https://we.tl/tu-enlace-de-descarga"
    driver.get(wetransfer_link)
    time.sleep(5)  # Pausa para simular tiempo de lectura

    WebDriverWait(driver, 20).until(
        lambda driver: driver.current_url != wetransfer_link
    )
    print("La URL ha cambiado, la página de descarga está lista.")

    # Intentar hacer clic en el botón de descarga
    download_button = WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(@data-test, 'downloadButton')]"))
    )
    download_button.click()
    print("Botón de descarga encontrado y clicado.")

except Exception as e:
    print("Error:", e)
    driver.save_screenshot("estado_descarga_wetransfer.png")

finally:
    driver.quit()
