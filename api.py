from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse
import os
import asyncio
import uvicorn
import requests
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
PORT = os.getenv("PORT", 8000)
UAS_PLANNER_IP = os.getenv("UAS_PLANNER_IP", "localhost")

app = FastAPI()

# Diccionario para almacenar las señales de que los CSVs están listos
csv_ready_events = {}
current_dir = os.path.dirname(os.path.abspath(__file__))

# Define el modelo de datos que se espera recibir
class MissionPlan(BaseModel):
    id: int  # ID del plan

@app.post("/upload_plan/")
async def upload_plan(plan: MissionPlan):
    """Guarda el JSON recibido como un archivo .plan y espera hasta que el CSV esté listo."""
    # Obtener el FlightPlan desde la API
    flight_plan = await obtener_file_content(int(plan.id))  # Asegúrate de convertir el ID a int

    # Guardar el archivo .plan usando el contenido del FlightPlan
    plan_name = f"{flight_plan['id']}.plan"  # Usar ID como nombre
    plan_file_path = os.path.join(f"{current_dir}/Planes", plan_name)

    # Guardar el archivo .plan
    try:
        os.makedirs(os.path.dirname(plan_file_path), exist_ok=True)  # Crear carpeta si no existe
        with open(plan_file_path, 'w') as f:
            f.write(flight_plan['fileContent'])  # Guardar el contenido como string
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar el archivo: {str(e)}")

    # Responder inmediatamente con 200 y "procesando"
    response = {"status": "procesando"}
    
    # Aquí se puede realizar el PUT para actualizar el estado del plan a "procesando"
    await update_plan_status(plan.id, "procesando")

    # Inicializar un evento asyncio para esperar la señal de que el CSV está listo
    if flight_plan['id'] not in csv_ready_events:
        csv_ready_events[flight_plan['id']] = asyncio.Event()

    # Esperar hasta que se haga el POST en /csv_ready/{mission_name}
    await csv_ready_events[flight_plan['id']].wait()

    # Una vez que el CSV esté listo, devolver el archivo CSV
    csv_file_path = os.path.join(f"{current_dir}/Trayectorias", f"{flight_plan['id']}_log.csv")
    
    if os.path.exists(csv_file_path):
        # Leer el contenido del CSV
        with open(csv_file_path, 'r') as csv_file:
            csv_content = csv_file.read()  # Leer el contenido del CSV

        # Realizar el PUT para actualizar el CSV en la base de datos
        await update_csv_result(plan.id, csv_content)  # Enviar el contenido completo del CSV
        return FileResponse(path=csv_file_path, media_type='text/csv', filename=f"{flight_plan['id']}_log.csv")
    else:
        raise HTTPException(status_code=404, detail="CSV no encontrado.")


async def obtener_file_content(id: int) -> dict:
    """Obtiene el contenido del plan de vuelo desde la API de UAS Planner."""
    try:
        response = requests.get(f"http://{UAS_PLANNER_IP}/api/flightPlans/{id}")
        
        if response.status_code == 200:
            flight_plan = response.json()  # Suponiendo que la respuesta es un JSON
            return flight_plan
        else:
            raise HTTPException(status_code=response.status_code, detail="Error al obtener el plan de vuelo.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al comunicarse con la API: {str(e)}")

async def update_plan_status(plan_id: int, status: str):
    """Actualizar el estado del plan de vuelo especificado en la API de UAS Planner."""
    try:
        response = requests.put(f"http://{UAS_PLANNER_IP}/api/flightPlans/{plan_id}", json={"status": status})
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Error al actualizar el estado del plan.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al comunicarse con la API: {str(e)}")

@app.post("/csv_ready/{mission_id}")
async def csv_ready_notification(mission_id: int, csv_data: dict):
    """Endpoint para recibir la notificación de que el CSV está listo."""
    csv_file_path = csv_data.get("csv_file")
    
    if os.path.exists(csv_file_path):
        if mission_id in csv_ready_events:
            csv_ready_events[mission_id].set()  # Desbloquear la espera en /upload_plan
        return {"message": f"CSV para {mission_id} está listo."}
    else:
        raise HTTPException(status_code=404, detail="CSV no encontrado.")

async def update_csv_result(id: int, csv_content: str):
    """Actualizar el CSV para el plan de vuelo especificado con el contenido completo."""
    # Realizar el PUT en la API de Next.js
    try:
        response = requests.put(f"http://{UAS_PLANNER_IP}/api/flightPlans/{id}", json={"csvResult": csv_content})
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Error al actualizar el CSV en la API.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al comunicarse con la API: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(PORT))