import requests

api_key = 'K89140021688957'
url = 'https://api.ocr.space/parse/image'
with open('placas_detectadas/cam2_20250317-142518.png', 'rb') as f:
    response = requests.post(url, files={ 'image': f }, data={ 'apikey': api_key })
result = response.json()
print(result['ParsedResults'][0]['ParsedText'])
