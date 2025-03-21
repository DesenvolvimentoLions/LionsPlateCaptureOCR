import time
import pyperclip
import pyautogui
from PIL import ImageGrab

while True:
    img = ImageGrab.grabclipboard()
    if img:
        print("Imagem detectada! Acionando OCR...")
        pyautogui.hotkey("win", "shift", "t")  # Aciona o Text Extractor
        time.sleep(1)  # Espera o OCR processar
        texto = pyperclip.paste()  # Captura o texto extraído
        print("Texto extraído:", texto)
    time.sleep(2)  # Verifica o clipboard a cada 2 segundos
