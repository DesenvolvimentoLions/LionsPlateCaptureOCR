import pyautogui
import time

print("Mova o mouse para capturar as coordenadas. Pressione 'Ctrl + C' para sair.\n")
282, 2171.
try:
    while True:
        x, y = pyautogui.position()  # Obtém a posição atual do cursor
        print(f"Posição do Mouse -> X: {x}, Y: {y}", end="\r", flush=True)  # Atualiza a linha no terminal
        time.sleep(0.1)  # Pequeno delay para evitar sobrecarga de CPU
except KeyboardInterrupt:
    print("\nMonitoramento encerrado!")
