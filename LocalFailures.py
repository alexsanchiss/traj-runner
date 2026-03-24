import os
import json
import asyncio
import itertools

current_dir = os.path.dirname(os.path.abspath(__file__))

UNITS = [
    "SENSOR_GYRO", "SENSOR_ACCEL", "SENSOR_MAG", "SENSOR_BARO", "SENSOR_GPS",
    "SENSOR_OPTICAL_FLOW", "SENSOR_VIO", "SENSOR_DISTANCE_SENSOR", "SENSOR_AIRSPEED",
    "SYSTEM_BATTERY", "SYSTEM_MOTOR", "SYSTEM_SERVO", "SYSTEM_AVOIDANCE",
    "SYSTEM_RC_SIGNAL", "SYSTEM_MAVLINK_SIGNAL"
]

TYPES = [
    "OFF", "STUCK", "GARBAGE", "WRONG", "SLOW", "DELAYED", "INTERMITTENT"
]

# Genera todas las combinaciones posibles (ej. ("SENSOR_GYRO", "OFF"), etc.)
FAILURES_TO_TEST = list(itertools.product(UNITS, TYPES))

def extract_home_position(mission_path):
    with open(mission_path, 'r') as f:
        mission_json = json.load(f)
        
    planned_home_position = mission_json["mission"].get("plannedHomePosition", None)
    
    if planned_home_position is not None:
        return planned_home_position[0], planned_home_position[1], planned_home_position[2]
    raise ValueError("No se encontró la posición planificada en el archivo de misión.")

async def run_px4(home_lat, home_lon, home_alt):
    command = ["make", "px4_sitl", "gazebo-classic"]
    env = os.environ.copy()
    env.update({
        "PX4_SIM_SPEED_FACTOR": "50",
        "PX4_HOME_LON": str(home_lon),
        "PX4_HOME_ALT": str(home_alt),
        "PX4_HOME_LAT": str(home_lat),
        "HEADLESS": "1"
    })
    
    px4_dir = os.path.expanduser("../PX4-Autopilot")
    
    process = await asyncio.create_subprocess_exec(
        *command, 
        stdout=asyncio.subprocess.PIPE, 
        stderr=asyncio.subprocess.STDOUT, 
        env=env, 
        stdin=asyncio.subprocess.PIPE, 
        cwd=px4_dir
    )
    return process

async def monitor_px4_and_run(process, mission_name, unit, f_type):
    print("Esperando a que PX4 esté listo...")
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        decoded_line = line.decode().strip()
        
        if "Ready for takeoff!" in decoded_line:
            print(f"Iniciando MAVSDK para {mission_name} con fallo {unit} - {f_type}...")
            mavsdk_command = ["python3", f"{current_dir}/CargarEjecutarFailure.py", mission_name, unit, f_type]
            mavsdk_process = await asyncio.create_subprocess_exec(*mavsdk_command)
            await mavsdk_process.wait() 
            
            print("Cerrando PX4...")
            process.stdin.write(b'shutdown\n')
            await process.stdin.drain()
            await process.wait()
            break

async def process_all_plans_with_failures():
    planes_dir = os.path.join(current_dir, "Planes")
    trayectorias_dir = os.path.join(current_dir, "Trayectorias")
    
    os.makedirs(planes_dir, exist_ok=True)
    os.makedirs(trayectorias_dir, exist_ok=True)

    archivos_plan = [f for f in os.listdir(planes_dir) if f.endswith('.plan')]
    
    if not archivos_plan:
        print("No hay archivos .plan en el directorio /Planes.")
        return

    for archivo in archivos_plan:
        mission_name = archivo.replace('.plan', '')
        mission_path = os.path.join(planes_dir, archivo)
        home_lat, home_lon, home_alt = extract_home_position(mission_path)
        
        for unit, f_type in FAILURES_TO_TEST:
            print(f"\n--- Procesando: {mission_name} | Fallo: {unit} ({f_type}) ---")
            try:
                px4_process = await run_px4(home_lat, home_lon, home_alt)
                await monitor_px4_and_run(px4_process, mission_name, unit, f_type)
                print(f"--- Finalizado: {mission_name} | Fallo: {unit} ({f_type}) ---")
            except Exception as e:
                print(f"Error procesando {mission_name} con fallo {unit}-{f_type}: {e}")

if __name__ == "__main__":
    asyncio.run(process_all_plans_with_failures())