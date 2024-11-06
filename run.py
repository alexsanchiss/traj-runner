import os
import json
import asyncio
import requests
from dotenv import load_dotenv
import signal
import platform

# Cargar variables de entorno
load_dotenv()
UAS_PLANNER_IP = os.getenv("UAS_PLANNER_IP", "localhost")

# Obtener el nombre de la distro para asignarla como nombre de la máquina
machine_name = os.getenv("WSL_DISTRO_NAME", "default_distro_name")

# Configuración global
current_dir = os.path.dirname(os.path.abspath(__file__))
machine_id = None

# Funciones auxiliares para la base de datos
async def register_or_update_machine():
    """Registrar la máquina si no existe o actualizar su estado si ya existe."""
    global machine_id
    try:
        # Verificar si la máquina ya está registrada
        response = requests.get(f"http://{UAS_PLANNER_IP}/api/machines?name={machine_name}")

        if response.status_code == 200:
            # Máquina encontrada, actualizamos su estado a 'Disponible'
            machine_data = response.json()
            machine_id = machine_data["id"]
            await update_machine_status("Disponible")
            print(f"Máquina ya registrada. Estado actualizado a 'Disponible'. ID: {machine_id}")
        else:
            # Máquina no encontrada, la registramos
            response = requests.post(
                f"http://{UAS_PLANNER_IP}/api/machines",
                json={"name": machine_name, "status": "Disponible"}
            )
            if response.status_code == 200 or response.status_code == 201:
                machine_id = response.json().get("id")
                print(f"Máquina registrada con ID: {machine_id}")
            else:
                print("Error al registrar la máquina:", response.status_code)
    except Exception as e:
        print(f"Error de conexión al registrar/actualizar la máquina: {e}")

async def update_machine_status(status):
    """Actualizar el estado de la máquina en la base de datos."""
    if machine_id:
        try:
            requests.put(
                f"http://{UAS_PLANNER_IP}/api/machines/{machine_id}",
                json={"status": status}
            )
            print(f"Estado de la máquina actualizado a: {status}")
        except Exception as e:
            print(f"Error al actualizar el estado de la máquina: {e}")

async def update_plan_status(plan_id, status, csv_result=None):
    """Actualizar el estado del plan de vuelo y su CSV resultante."""
    try:
        data = {"status": status}
        if csv_result:
            data["csvResult"] = csv_result

        response = requests.put(
            f"http://{UAS_PLANNER_IP}/api/flightPlans/{plan_id}",
            json=data
        )
        if response.status_code == 200:
            print(f"Estado del plan {plan_id} actualizado a: {status}")
        else:
            print(f"Error al actualizar el plan: {response.status_code}")
    except Exception as e:
        print(f"Error al actualizar el plan {plan_id}: {e}")

def extract_home_position(mission_path):
    """Extrae la posición del hogar desde el archivo de misión."""
    with open(mission_path, 'r') as f:
        mission_json = json.load(f)
        
    planned_home_position = mission_json["mission"].get("plannedHomePosition", None)
    
    if planned_home_position is not None:
        return planned_home_position[0], planned_home_position[1], planned_home_position[2]
    else:
        raise ValueError("No se encontró la posición planificada en el archivo de misión.")

async def run_px4(home_lat, home_lon, home_alt):
    """Ejecuta el comando PX4 con las coordenadas de hogar y monitorea la salida."""
    command = [
        "make", "px4_sitl", "gazebo-classic"
    ]
    env = os.environ.copy()
    env.update({
        "PX4_SIM_SPEED_FACTOR": "50",
        "PX4_HOME_LON": str(home_lon),
        "PX4_HOME_ALT": str(home_alt),
        "PX4_HOME_LAT": str(home_lat)
    })
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env, stdin=asyncio.subprocess.PIPE
    )
    return process

async def monitor_px4_output(process, mission_name):
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        decoded_line = line.decode().strip()
        print(decoded_line)
        if "Ready for takeoff!" in decoded_line:
            print("Mensaje 'Ready for takeoff!' detectado")
            await run_mavsdk_mission(mission_name)
            await shutdown_px4(process)
            break

async def shutdown_px4(process):
    """Envia el comando de cierre a PX4."""
    print("Enviando comando de shutdown a PX4...")
    process.stdin.write(b'shutdown\n')  # Escribir el comando de cierre
    await process.stdin.drain()  # Asegurarse de que se envíe
    await process.wait()  # Esperar a que se complete el proceso

async def run_mavsdk_mission(mission_name):
    """Ejecuta el script de MAVSDK en un nuevo proceso."""
    mavsdk_command = ["python3", f"{current_dir}/CargarEjecutar.py", str(mission_name)]
    mavsdk_process = await asyncio.create_subprocess_exec(*mavsdk_command)
    await mavsdk_process.wait()  # Esperar a que el script MAVSDK termine
    print("MAVSDK misión finalizada. Cerrando procesos...")


async def process_flight_plan(plan):
    """Procesa el plan de vuelo asignado."""
    plan_id = plan["id"]
    mission_path = os.path.join(current_dir, "Planes", f"{plan_id}.plan")
    
    # Guardar el archivo del plan de vuelo
    try:
        with open(mission_path, 'w') as f:
            f.write(plan["fileContent"])
        print(f"Archivo del plan de vuelo guardado: {mission_path}")
    except Exception as e:
        print(f"Error al guardar el archivo del plan: {e}")
        await update_machine_status("Error")
        return

    # Ejecutar el procesamiento del plan
    home_lat, home_lon, home_alt = extract_home_position(mission_path)
    print(home_lat, home_lon, home_alt)
    try:
        os.chdir(os.path.expanduser("~/PX4-Autopilot"))
        px4_process = await run_px4(home_lat, home_lon, home_alt)
        await monitor_px4_output(px4_process, plan_id)
    except Exception as e:
        print(f"Error en el procesamiento: {e}")
        await update_machine_status("Error")
        return

    # Actualizar estado del plan a "procesado"
    csv_result = await read_csv_result(plan_id)
    await update_plan_status(plan_id, "procesado", csv_result)
    
    # Borrar archivos temporales
    os.remove(mission_path)
    os.remove(f"{current_dir}/Trayectorias/{plan_id}_log.csv")
    print(f"Archivo procesado y eliminado: {mission_path}")

    # Actualizar estado de la máquina a "Disponible"
    await update_machine_status("Disponible")

async def read_csv_result(plan_id):
    """Leer el archivo CSV procesado para actualizar el plan de vuelo."""
    csv_path = os.path.join(current_dir, "Trayectorias", f"{plan_id}_log.csv")
    with open(csv_path, 'r') as csv_file:
        csv_content = csv_file.read()
    return csv_content

async def monitor_flight_plans():
    """Monitorea la base de datos y procesa un plan si está asignado a esta máquina."""
    while True:
        try:
            # Solicitar planes de vuelo
            response = requests.get(f"http://{UAS_PLANNER_IP}/api/flightPlans")
            if response.status_code == 200:
                plans = response.json()
                
                # Buscar un plan asignado a esta máquina
                for plan in plans:
                    if plan["machineAssignedName"] == machine_name and plan["status"] == "procesando":
                        # Procesar el plan de vuelo
                        await process_flight_plan(plan)
                        
                        # Esperar 5 segundos antes de verificar por un nuevo plan
                        await asyncio.sleep(5)
                        break  # Salir del ciclo for para evitar escuchar nuevos planes hasta que se complete el actual
            else:
                print(f"Error al obtener los planes de vuelo: {response.status_code}")
            await asyncio.sleep(5)  # Esperar entre cada solicitud
        except Exception as e:
            print(f"Error al monitorear los planes de vuelo: {e}")
            await asyncio.sleep(5)  # Esperar en caso de error para evitar sobrecarga de solicitudes

async def main():
    await register_or_update_machine()
    await monitor_flight_plans()

if __name__ == "__main__":
    asyncio.run(main())