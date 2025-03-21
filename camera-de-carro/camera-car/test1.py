import time
import os
import csv
import pyperclip
import re  # Importar expressões regulares
from datetime import datetime
from PIL import Image
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
import pyautogui
import win32clipboard

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

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def extract_text_bing(image_path, driver):
    placa = None
    tentativas = 0  # Contador de tentativas
    while not placa and tentativas < 3:
        # Copia a imagem para o clipboard
        copy_image_to_clipboard(image_path)
        
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

def process_images_in_folder(folder_path, output_csv):
    # Cria ou abre o arquivo CSV para escrita
    with open(output_csv, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Data", "Hora", "Placa"])  # Cabeçalho do CSV

        # Configura o driver fora do loop para reutilizar a mesma instância
        driver = setup_driver()

        # Percorre todos os arquivos na pasta
        for filename in os.listdir(folder_path):
            if filename.endswith(".png"):
                image_path = os.path.join(folder_path, filename)
                print(f"Processando imagem: {image_path}")

                # Chama a função para extrair a placa da imagem
                placa = extract_text_bing(image_path, driver)

                # Se encontrou uma placa, escreve no CSV com a data e hora atuais
                if placa:
                    now = datetime.now()
                    data = now.strftime("%d/%m/%Y")  # Data atual
                    hora = now.strftime("%H:%M:%S")  # Hora atual
                    writer.writerow([data, hora, placa])  # Escreve a linha no CSV
                    print(f"Placa encontrada: {placa}")
                else:
                    print("Imagem ignorada após 3 tentativas sem sucesso.")

                # Aguarda um pouco antes de processar a próxima imagem
                time.sleep(2)

        # Fechar o navegador após o processamento de todas as imagens
        driver.quit()

if __name__ == "__main__":
    # Caminho para a pasta de imagens e para o arquivo CSV de saída
    folder_path = "C:/Users/joel.vitor/Documents/lions-projetos/camera-de-carro/placas_detectadas"
    output_csv = "placas_detectadas.csv"

    # Processa as imagens da pasta e cria o CSV
    process_images_in_folder(folder_path, output_csv)
