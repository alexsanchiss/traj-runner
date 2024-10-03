from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import asyncio

app = FastAPI()

# Define el modelo de datos que se espera recibir
class MissionPlan(BaseModel):
    name: str
    fileType: str
    geoFence: dict
    groundStation: str
    mission: dict
    rallyPoints: dict
    version: int

async def wait_for_file(file_path: str, timeout: int = 200) -> str:
    """Espera hasta que el archivo exista en la ruta especificada o hasta que se alcance el tiempo de espera."""
    for _ in range(timeout):
        if os.path.exists(file_path):
            return file_path
        await asyncio.sleep(1)  # Espera 1 segundo antes de volver a comprobar
    raise HTTPException(status_code=404, detail=f"Archivo {file_path} no encontrado dentro del tiempo de espera.")

@app.post("/upload_plan/")
async def upload_plan(plan: MissionPlan):
    """Guarda el JSON recibido como un archivo .plan en la carpeta especificada y espera el archivo CSV."""
    # Generar el nombre del archivo .plan
    plan_name = f"{plan.name}.plan"
    plan_file_path = os.path.join("/home/asanmar4/PythonPruebas/Planes", plan_name)

    # Guardar el archivo .plan
# Guardar el archivo .plan
    try:
        with open(plan_file_path, 'w') as f:
            f.write(plan.json())
    except Exception as e:
        print(f"Error al guardar el archivo: {str(e)}")  # Añadir impresión de error
        raise HTTPException(status_code=500, detail=f"Error al guardar el archivo: {str(e)}")


    # Esperar el archivo CSV
    csv_file_path = os.path.join("/home/asanmar4/PythonPruebas/Trayectorias", f"{plan.name}_log.csv")
    
    try:
        await wait_for_file(csv_file_path)  # Espera a que el archivo CSV esté disponible
        return {"message": f"Archivo guardado como {plan_name}", "csv_file": csv_file_path}
    except HTTPException as e:
        raise e

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)