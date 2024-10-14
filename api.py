from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse
import os
import asyncio

app = FastAPI()

# Diccionario para almacenar las señales de que los CSVs están listos
csv_ready_events = {}
current_dir = os.path.dirname(os.path.abspath(__file__))

# Verificar si la carpeta Planes existe, si no, crearla
planes_dir = os.path.join(current_dir, 'Planes')
if not os.path.exists(planes_dir):
    os.makedirs(planes_dir)
    print(f"Carpeta 'Planes' creada en: {planes_dir}")

# Define el modelo de datos que se espera recibir
class MissionPlan(BaseModel):
    name: str
    fileType: str
    geoFence: dict
    groundStation: str
    mission: dict
    rallyPoints: dict
    version: int

@app.post("/upload_plan/")
async def upload_plan(plan: MissionPlan):
    """Guarda el JSON recibido como un archivo .plan y espera hasta que el CSV esté listo."""
    plan_name = f"{plan.name}.plan"
    plan_file_path = os.path.join(f"{current_dir}/Planes", plan_name)

    # Guardar el archivo .plan
    try:
        with open(plan_file_path, 'w') as f:
            f.write(plan.json())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar el archivo: {str(e)}")

    # Inicializar un evento asyncio para esperar la señal de que el CSV está listo
    if plan.name not in csv_ready_events:
        csv_ready_events[plan.name] = asyncio.Event()

    # Esperar hasta que se haga el POST en /csv_ready/{mission_name}
    await csv_ready_events[plan.name].wait()

    # Una vez que el CSV esté listo, devolver el archivo CSV
    csv_file_path = os.path.join(f"{current_dir}/Trayectorias", f"{plan.name}_log.csv")
    
    if os.path.exists(csv_file_path):
        response = FileResponse(path=csv_file_path, media_type='text/csv', filename=f"{plan.name}_log.csv")
        
        # Enviar el archivo CSV y luego eliminarlo
        try:
            return response
        finally:
            os.remove(csv_file_path)  # Eliminar el archivo CSV después de enviarlo
    else:
        raise HTTPException(status_code=404, detail="CSV no encontrado.")

@app.post("/csv_ready/{mission_name}")
async def csv_ready_notification(mission_name: str, csv_data: dict):
    """Endpoint para recibir la notificación de que el CSV está listo."""
    csv_file_path = csv_data.get("csv_file")
    
    if os.path.exists(csv_file_path):
        if mission_name in csv_ready_events:
            csv_ready_events[mission_name].set()  # Desbloquear la espera en /upload_plan
        return {"message": f"CSV para {mission_name} está listo."}
    else:
        raise HTTPException(status_code=404, detail="CSV no encontrado.")
