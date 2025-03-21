import os
import time
import csv
import base64
import re
from datetime import datetime
from io import BytesIO
import threading
from queue import Queue

import cv2
import torch
import numpy as np
import requests
from PIL import Image

# ---------------------- Configurações Iniciais ----------------------
SAVE_DIR = "placas_detectadas"
os.makedirs(SAVE_DIR, exist_ok=True)

CSV_CARROS = "registros_carros.csv"
if not os.path.exists(CSV_CARROS):
    with open(CSV_CARROS, "w", newline="") as f:
        csv.writer(f).writerow(["Data", "Hora", "Camera", "Imagem"])

CSV_PLACAS = "placas_detectadas.csv"
if not os.path.exists(CSV_PLACAS):
    with open(CSV_PLACAS, "w", newline="") as f:
        csv.writer(f).writerow(["Data", "Hora", "Placa"])

# ---------------------- Função de OCR via Express ----------------------
def perform_ocr_from_base64(image_path):
    with open(image_path, "rb") as f:
        encoded_image = base64.b64encode(f.read()).decode("utf-8")
    url = "http://localhost:8082/ocr"
    payload = {"imageBase64": encoded_image}
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json()

# ---------------------- Pré-processamento da Imagem ----------------------
def melhorar_imagem(img):
    denoised = cv2.fastNlMeansDenoisingColored(img, None, h=10, hColor=10,
                                                templateWindowSize=7, searchWindowSize=21)
    gamma = 1.2
    look_up_table = np.array([np.clip(pow(i / 255.0, gamma) * 255.0, 0, 255)
                              for i in range(256)], dtype=np.uint8)
    gamma_corrected = cv2.LUT(denoised, look_up_table)
    gaussian = cv2.GaussianBlur(gamma_corrected, (0, 0), 3)
    sharp = cv2.addWeighted(gamma_corrected, 1.5, gaussian, -0.5, 0)
    return sharp

# ---------------------- Worker de Salvamento e OCR ----------------------
save_queue = Queue()
tentativas_placas = {}

def save_worker():
    while True:
        item = save_queue.get()
        if item is None:
            break
        camera_label, frame_copy, bbox, cam_number = item
        x1, y1, x2, y2 = bbox

        # Recorta e processa a região de interesse
        cropped = frame_copy[y1:y2, x1:x2]
        processed = melhorar_imagem(cropped)

        # Salva a imagem com timestamp
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"cam{cam_number}_{timestamp}.png"
        path = os.path.join(SAVE_DIR, filename)
        cv2.imwrite(path, processed)

        # Contabiliza tentativas para esta imagem
        tentativas_placas[path] = tentativas_placas.get(path, 0) + 1
        if tentativas_placas[path] > 2:
            print(f"⚠️ {filename}: Tentativas esgotadas. Pulando imagem.")
            save_queue.task_done()
            continue

        # Extração de placa via OCR
        try:
            ocr_data = perform_ocr_from_base64(path)
            placas = ocr_data.get("placas", [])
            if placas:
                placa = placas[0]
                now = datetime.now()
                with open(CSV_PLACAS, "a", newline="") as f:
                    csv.writer(f).writerow([now.strftime("%Y-%m-%d"),
                                            now.strftime("%H:%M:%S"), placa])
                print(f"📸 {now.strftime('%H:%M:%S')} | Placa detectada: {placa}")
                tentativas_placas.pop(path, None)
            else:
                print("Nenhuma placa extraída nesta imagem.")
        except Exception as e:
            print(f"Erro na extração da placa ({camera_label}): {e}")

        save_queue.task_done()

worker_thread = threading.Thread(target=save_worker, daemon=True)
worker_thread.start()

# ---------------------- Classe para Captura de Stream ----------------------
class CameraStream:
    def __init__(self, rtsp_url, camera_name, frame_width=1280, frame_height=720):
        self.rtsp_url = rtsp_url
        self.camera_name = camera_name
        self.cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
        if not self.cap.isOpened():
            print(f"[ERRO] Falha ao abrir {camera_name}")
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
            placeholder = np.zeros((720, 1280, 3), dtype=np.uint8)
            cv2.putText(placeholder, f"Sem conexão {self.camera_name}", (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return placeholder

    def stop(self):
        self.running = False
        self.thread.join()
        self.cap.release()

# ---------------------- Configurações e Parâmetros ----------------------
rtsp_url1 = "rtsp://desenvolvedo:eliseu22@192.168.10.45:554/cam/realmonitor?channel=1&subtype=0&transport=tcp"
rtsp_url2 = "rtsp://desenvolvedo:eliseu22@192.168.10.48:554/cam/realmonitor?channel=1&subtype=0&transport=tcp"

cam1 = CameraStream(rtsp_url1, "Cam 1")
cam2 = CameraStream(rtsp_url2, "Cam 2")

# Configurações de exibição das janelas
cv2.namedWindow("Video - Cam 1", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Video - Cam 1", 1280, 720)
cv2.namedWindow("Video - Cam 2", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Video - Cam 2", 1280, 720)

# Regiões de Interesse (ROIs)
roi_cam1 = np.array([[1162, 340], [1896, 655], [1676, 994], [735, 418]])
roi_cam2 = np.array([[396, 537], [1217, 361], [1622, 586], [506, 979]])

# Carrega o modelo YOLO
model = torch.hub.load("ultralytics/yolov5", "yolov5s")
model.conf = 0.4
device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)

def is_in_roi(x1, y1, x2, y2, roi):
    center = ((x1 + x2) / 2, (y1 + y2) / 2)
    return cv2.pointPolygonTest(roi, center, False) >= 0

# ---------------------- Loop Principal ----------------------
def main():
    detection_interval = 5  # segundos entre detecções
    last_detection_time_cam1 = 0
    last_detection_time_cam2 = 0

    while True:
        frame1 = cam1.read()
        frame2 = cam2.read()

        # Aplica o ROI apenas nas imagens exibidas nas janelas, não na imagem que será salva
        display_frame1 = frame1.copy()
        display_frame2 = frame2.copy()

        # Desenha as linhas do ROI apenas para visualização
        cv2.polylines(display_frame1, [roi_cam1], True, (0, 0, 255), 2)
        cv2.polylines(display_frame2, [roi_cam2], True, (0, 0, 255), 2)

        current_time = time.time()

        # Função para processar cada câmera
        def process_cam(frame, frame_copy, roi, last_detection_time, cam_number, camera_label):
            if current_time - last_detection_time < detection_interval:
                return last_detection_time
            frame_small = cv2.resize(frame_copy, (640, 480))
            results = model(frame_small)
            preds = results.xyxy[0]
            if preds is not None and preds.shape[0] > 0:
                for pred in preds:
                    conf = float(pred[4].item())
                    cls = int(pred[5].item())
                    if cls == 2 and conf > 0.4:
                        h_orig, w_orig = frame.shape[:2]
                        h_small, w_small = frame_small.shape[:2]
                        scale_x = w_orig / w_small
                        scale_y = h_orig / h_small
                        x1 = int(pred[0].item() * scale_x)
                        y1 = int(pred[1].item() * scale_y)
                        x2 = int(pred[2].item() * scale_x)
                        y2 = int(pred[3].item() * scale_y)
                        if is_in_roi(x1, y1, x2, y2, roi):
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            save_queue.put((camera_label, frame_copy, (x1, y1, x2, y2), cam_number))
                            return current_time
            return last_detection_time

        # Processa cada câmera e atualiza o tempo da última detecção
        last_detection_time_cam1 = process_cam(frame1, frame1.copy(), roi_cam1,
                                               last_detection_time_cam1, 1, "Cam 1")
        last_detection_time_cam2 = process_cam(frame2, frame2.copy(), roi_cam2,
                                               last_detection_time_cam2, 2, "Cam 2")

        # Exibe as imagens com os ROIs (para visualização)
        cv2.imshow("Video - Cam 1", display_frame1)
        cv2.imshow("Video - Cam 2", display_frame2)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    # Finaliza as capturas e o worker
    cam1.stop()
    cam2.stop()
    cv2.destroyAllWindows()
    save_queue.put(None)
    worker_thread.join()

if __name__ == "__main__":
    main()
