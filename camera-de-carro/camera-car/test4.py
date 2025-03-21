import requests
import base64

caminho_imagem = "C:/Users/joel.vitor/Documents/lions-projetos/camera-de-carro/placas_detectadas/cam1_20250318-124439.png"

with open(caminho_imagem, "rb") as image_file:
    encoded_image = base64.b64encode(image_file.read()).decode("utf-8")

url = "http://localhost:8082/ocr"

payload = {
    "imageBase64": encoded_image
}

try:
    response = requests.post(url, json=payload)
    response.raise_for_status()

    print("\nResposta do servidor: ")
    print(response.json())
except requests.exceptions.RequestException as e:
    print("Erro ao enviar a requisição: ", e)