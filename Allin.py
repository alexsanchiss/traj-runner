import json
import os
import asyncio
import requests

current_dir = os.path.dirname(os.path.abspath(__file__))

# Verificar si la carpeta Planes existe, si no, crearla
planes_dir = os.path.join(current_dir, 'Planes')
if not os.path.exists(planes_dir):
    os.makedirs(planes_dir)
    print(f"Carpeta 'Planes' creada en: {planes_dir}")

async def notify_csv_ready(mission_name):
    csv_file_path = f"{current_dir}/Trayectorias/{mission_name}_log.csv"
    url = f"http://localhost:8000/csv_ready/{mission_name}"
    
    # Envía una notificación a la API
    try:
        response = requests.post(url, json={"csv_file": csv_file_path})
        if response.status_code == 200:
            print(f"Notificación enviada: {mission_name} CSV listo.")
        else:
            print(f"Error al notificar: {response.status_code}")
    except Exception as e:
        print(f"Error al conectar con la API: {e}")

# Resto del código sigue igual...
