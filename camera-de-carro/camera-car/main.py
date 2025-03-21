import os
import time
import csv
import pyperclip
import re  # Expressões regulares
from datetime import datetime
from PIL import Image
from io import BytesIO
import cv2
import torch
import numpy as np
import threading
from queue import Queue
import requests
import pyautogui
import win32clipboard

# ---------------------- Selenium Imports ----------------------
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
# --------------------------------------------------------------

import tempfile

# Diretórios e arquivos CSV
save_dir = "placas_detectadas"
if not os.path.exists(save_dir):
    os.makedirs(save_dir)

csv_carros = "registros_carros.csv"
if not os.path.exists(csv_carros):
    with open(csv_carros, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Data", "Hora", "Camera", "Imagem"])

csv_placas = "registros_placas.csv"
if not os.path.exists(csv_placas):
    with open(csv_placas, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Data", "Hora", "Placa"])

# ---------------------- Funções Selenium (Extração de Placa) ----------------------
def copy_image_to_clipboard(image_path):
    image = Image.open(image_path)
    output = BytesIO()
    image.convert("RGB").save(output, "BMP")
    data = output.getvalue()[14:]  # Remove o header BMP
    output.close()
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
    win32clipboard.CloseClipboard()

def setup_driver():
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Evitar detecção de automação
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Criar um diretório de perfil temporário para evitar conflito
    temp_profile = tempfile.mkdtemp()
    options.add_argument(f"--user-data-dir={temp_profile}")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def extract_text_bing(image_path):
    placa = None
    tentativas = 0  # Contador de tentativas
    while not placa and tentativas < 3:
        # Copia a imagem para o clipboard
        copy_image_to_clipboard(image_path)

        driver = setup_driver()
        
        driver.maximize_window()

        # Acessa o Bing Visual Search
        driver.get("https://www.bing.com/visualsearch")
        time.sleep(2)

        # Aceita o cookie (se aparecer)
        try:
            driver.find_element(By.XPATH, "//a[contains(text(),'Aceitar')]").click()
        except Exception as e:
            print("Botão de cookies não encontrado ou já aceito.")

        # Encontra a área de colagem e cola a imagem copiada (CTRL+V)
        body = driver.find_element(By.ID, "vsk_pastearea")
        actions = ActionChains(driver)
        actions.click(body).key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL).perform()

        time.sleep(6)  # Aguarda o processamento da imagem

        # Clica na aba que mostra o resultado do OCR
        try:
            driver.find_element(By.XPATH, "//span[contains(text(),'Texto')]").click()
        except Exception as e:
            print("Não foi possível clicar na aba de texto/OCR.")

        time.sleep(4)

        # Clica no botão "Copiar texto" que está representado pelo div
        try:
            copy_btn = driver.find_element(By.XPATH, "//div[contains(@class, 'text_copy_btn')]")
            copy_btn.click()
            time.sleep(2)  # Aguarda a atualização do clipboard
        except Exception as e:
            print("Erro ao clicar no botão 'Copiar texto':", e)
            return None

        # Lê o conteúdo copiado da área de transferência
        clipboard_text = pyperclip.paste()
        print("Conteúdo copiado do clipboard:", clipboard_text)

        # Verifica se o texto contém um horário no formato "dd/mm/yyyy hh mm ss"
        horario_pattern = re.compile(r'\b\d{2}/\d{2}/\d{4} \d{2} \d{2} \d{2}\b')
        if horario_pattern.search(clipboard_text):
            print("Horário encontrado no texto da placa. Ignorando esta placa e passando para a próxima imagem.")
            return None

        # Separa o texto em tokens alfanuméricos
        tokens = re.findall(r'\w+', clipboard_text)
        candidate = None

        # Primeiro, tenta encontrar um token único com 6 a 8 caracteres que contenha números
        for token in tokens:
            if 6 <= len(token) <= 8 and re.search(r'\d', token):
                candidate = token
                break

        # Se não encontrou, tenta juntar pares de tokens consecutivos
        if candidate is None and len(tokens) >= 2:
            for i in range(len(tokens)-1):
                combined = tokens[i] + tokens[i+1]
                if 6 <= len(combined) <= 8 and re.search(r'\d', combined):
                    candidate = combined
                    break

        if candidate:
            # Se o candidato tiver 8 caracteres, verifique se ao remover o primeiro caractere ainda há números.
            if len(candidate) == 8 and re.search(r'\d', candidate[1:]):
                candidate = candidate[1:]
            # Se a placa resultante tiver 6 ou 7 caracteres, aceite-a.
            if 6 <= len(candidate) <= 7:
                placa = candidate
                return placa
            else:
                print("Texto extraído não se enquadra no tamanho esperado. Tentando novamente...")
        else:
            print("Nenhuma placa válida encontrada. Tentando novamente...")

        tentativas += 1  # Incrementa a contagem de tentativas
        time.sleep(2)  # Atraso antes da próxima tentativa

    print("Número máximo de tentativas atingido. Ignorando esta imagem.")
    return None  # Retorna None se não encontrar uma placa válida após 3 tentativas
# --------------------------------------------------------------------------------

# --------------------- Worker para salvar imagens e extrair placa ---------------------
save_queue = Queue()
tentativas_placas = {}  # Dicionário para contar tentativas por imagem

def save_worker():
    plate_driver = setup_driver()  # Cria o driver Selenium apenas uma vez

    while True:
        item = save_queue.get()
        if item is None:
            break
        camera_label, frame_copy, bbox, cam_number = item
        x1, y1, x2, y2 = bbox

        # Recorta e processa a imagem da detecção
        cropped = frame_copy[y1:y2, x1:x2]
        processed = melhorar_imagem(cropped)

        # Salva a imagem com timestamp
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"cam{cam_number}_{timestamp}.png"
        path = os.path.join(save_dir, filename)
        cv2.imwrite(path, processed)

        # Contador de tentativas
        if path not in tentativas_placas:
            tentativas_placas[path] = 0
        tentativas_placas[path] += 1

        # Se já tentou 2 vezes, descarta
        if tentativas_placas[path] > 2:
            print(f"⚠️ {filename}: Tentativas esgotadas. Passando para o próximo.")
            save_queue.task_done()
            continue

        # --- Extração de placa via Selenium ---
        try:
            placa = extract_text_bing(path, plate_driver)  # Chama a função para extrair a placa
            if placa:
                now = datetime.now()

                # Salva no CSV
                with open(csv_placas, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), placa])

                # Exibe a placa detectada no console
                print(f"📸 {now.strftime('%H:%M:%S')} | Placa detectada: {placa}")

                # Remove do dicionário (placa extraída com sucesso)
                del tentativas_placas[path]

        except Exception as e:
            print(f"Erro na extração da placa ({camera_label}): {str(e)}")

        save_queue.task_done()

    plate_driver.quit()  

worker_thread = threading.Thread(target=save_worker, daemon=True)
worker_thread.start()
# -------------------------------------------------------------------------------------

# ------------------ Função para melhorar a imagem ------------------
def melhorar_imagem(img):
    denoised = cv2.fastNlMeansDenoisingColored(img, None, h=10, hColor=10, templateWindowSize=7, searchWindowSize=21)
    gamma = 1.2
    look_up_table = np.empty((1, 256), np.uint8)
    for i in range(256):
        look_up_table[0, i] = np.clip(pow(i / 255.0, gamma) * 255.0, 0, 255)
    gamma_corrected = cv2.LUT(denoised, look_up_table)
    gaussian = cv2.GaussianBlur(gamma_corrected, (0, 0), 3)
    sharp = cv2.addWeighted(gamma_corrected, 1.5, gaussian, -0.5, 0)
    return sharp
# ---------------------------------------------------------------------

# ---------------------- Classe para captura de stream ----------------------
class CameraStream:
    def __init__(self, rtsp_url, camera_name, frame_width=1280, frame_height=720):
        self.rtsp_url = rtsp_url
        self.camera_name = camera_name
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
        if not self.cap.isOpened():
            print(f"[ERRO] Falha ao abrir {self.camera_name}")
        self.frame = None
        self.running = True
        self.lock = threading.Lock()
        self.fail_count = 0
        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()
    
    def update(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
                self.fail_count = 0
            else:
                self.fail_count += 1
                print(f"[DEBUG] {self.camera_name}: Falha na captura ({self.fail_count}/5)")
                self.cap.release()
                time.sleep(2)
                self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                if self.fail_count >= 5:
                    print(f"[DEBUG] {self.camera_name}: Tentando reconexão...")
    
    def read(self):
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()
            else:
                placeholder = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(placeholder, f"Sem conexão {self.camera_name}", (50, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                return placeholder
    
    def stop(self):
        self.running = False
        self.thread.join()
        self.cap.release()
# --------------------------------------------------------------------------

# ---------------------- Configurações e ROIs ----------------------
rtsp_url1 = "rtsp://desenvolvedo:eliseu22@192.168.10.45:554/cam/realmonitor?channel=1&subtype=0&transport=tcp"
rtsp_url2 = "rtsp://desenvolvedo:eliseu22@192.168.10.48:554/cam/realmonitor?channel=1&subtype=0&transport=tcp"

cam1 = CameraStream(rtsp_url1, "Cam 1")
cam2 = CameraStream(rtsp_url2, "Cam 2")

cv2.namedWindow("Video - Cam 1", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Video - Cam 1", 1280, 720)
cv2.namedWindow("Video - Cam 2", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Video - Cam 2", 1280, 720)

roi_cam1 = np.array([
    [1162, 340],
    [1896, 655],
    [1676, 994],
    [735, 418],
])
roi_cam2 = np.array([
    [396, 537],
    [1217, 361],
    [1622, 586],
    [506, 979],
])
# --------------------------------------------------------------------

# ---------------------- Modelo YOLO ----------------------
model = torch.hub.load("ultralytics/yolov5", "yolov5s")
model.conf = 0.4
device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)
# -------------------------------------------------------

# ---------------------- Função para verificar se o centro está no ROI ----------------------
def is_in_roi(x1, y1, x2, y2, roi):
    center = ((x1 + x2) / 2, (y1 + y2) / 2)
    return cv2.pointPolygonTest(roi, center, False) >= 0
# -------------------------------------------------------------------------------------------

# ---------------------- Loop principal ----------------------
detection_interval = 5  # segundos entre detecções
last_detection_time_cam1 = 0
last_detection_time_cam2 = 0

while True:
    frame1 = cam1.read()
    frame2 = cam2.read()

    cv2.polylines(frame1, [roi_cam1], isClosed=True, color=(0, 0, 255), thickness=2)
    cv2.polylines(frame2, [roi_cam2], isClosed=True, color=(0, 0, 255), thickness=2)

    current_time = time.time()

   # Processamento para Cam 1
    if current_time - last_detection_time_cam1 >= detection_interval:
        frame1_copy = frame1.copy()
        frame1_small = cv2.resize(frame1_copy, (640, 480))
        results1 = model(frame1_small)
        preds1 = results1.xyxy[0]
    
    if preds1 is not None and preds1.shape[0] > 0:
        for pred in preds1:
            conf = float(pred[4].item())
            cls = int(pred[5].item())
            if cls == 2 and conf > 0.4:
                h_orig, w_orig = frame1.shape[:2]
                h_small, w_small = frame1_small.shape[:2]
                scale_x = w_orig / w_small
                scale_y = h_orig / h_small
                x1 = int(pred[0].item() * scale_x)
                y1 = int(pred[1].item() * scale_y)
                x2 = int(pred[2].item() * scale_x)
                y2 = int(pred[3].item() * scale_y)
                if is_in_roi(x1, y1, x2, y2, roi_cam1):
                    # Desenha o retângulo na imagem para visualização
                    cv2.rectangle(frame1, (x1, y1), (x2, y2), (0, 255, 0), 2)

                    # Salva a imagem sem o ROI
                    frame1_copy_without_roi = frame1_copy.copy()
                    save_queue.put(("Cam 1", frame1_copy_without_roi, (x1, y1, x2, y2), 1))

                    last_detection_time_cam1 = current_time
                    break

# Processamento para Cam 2
    if current_time - last_detection_time_cam2 >= detection_interval:
        frame2_copy = frame2.copy()
        frame2_small = cv2.resize(frame2_copy, (640, 480))
        results2 = model(frame2_small)
        preds2 = results2.xyxy[0]

    if preds2 is not None and preds2.shape[0] > 0:
        for pred in preds2:
            conf = float(pred[4].item())
            cls = int(pred[5].item())
            if cls == 2 and conf > 0.4:
                h_orig, w_orig = frame2.shape[:2]
                h_small, w_small = frame2_small.shape[:2]
                scale_x = w_orig / w_small
                scale_y = h_orig / h_small
                x1 = int(pred[0].item() * scale_x)
                y1 = int(pred[1].item() * scale_y)
                x2 = int(pred[2].item() * scale_x)
                y2 = int(pred[3].item() * scale_y)
                if is_in_roi(x1, y1, x2, y2, roi_cam2):
                    # Desenha o retângulo na imagem para visualização
                    cv2.rectangle(frame2, (x1, y1), (x2, y2), (0, 255, 0), 2)

                    # Salva a imagem sem o ROI
                    frame2_copy_without_roi = frame2_copy.copy()
                    save_queue.put(("Cam 2", frame2_copy_without_roi, (x1, y1, x2, y2), 2))

                    last_detection_time_cam2 = current_time
                    break

    cv2.imshow("Video - Cam 1", frame1)
    cv2.imshow("Video - Cam 2", frame2)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cam1.stop()
cam2.stop()
cv2.destroyAllWindows()

# Encerra o worker e espera ele finalizar
save_queue.put(None)
worker_thread.join()