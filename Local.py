import os
import json
import asyncio

current_dir = os.path.dirname(os.path.abspath(__file__))

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
        "PX4_HOME_LAT": str(home_lat)
    })
    
    px4_dir = os.path.expanduser("../PX4-Autopilot")
    
    process = await asyncio.create_subprocess_exec(
        *command, 
        stdout=asyncio.subprocess.PIPE, 
        stderr=asyncio.subprocess.STDOUT, # Corrección: Redirige stderr a stdout
        env=env, 
        stdin=asyncio.subprocess.PIPE, 
        cwd=px4_dir
    )
    return process

async def monitor_px4_and_run(process, mission_name):
    print("Esperando a que PX4 esté listo...")
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        decoded_line = line.decode().strip()
        print(decoded_line)
        
        if "Ready for takeoff!" in decoded_line:
            print("Iniciando MAVSDK...")
            mavsdk_command = ["python3", f"{current_dir}/CargarEjecutar.py", mission_name]
            mavsdk_process = await asyncio.create_subprocess_exec(*mavsdk_command)
            await mavsdk_process.wait() 
            
            print("Cerrando PX4...")
            process.stdin.write(b'shutdown\n')
            await process.stdin.drain()
            await process.wait()
            break

async def process_all_plans():
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
        
        print(f"\n--- Procesando: {mission_name} ---")
        
        try:
            home_lat, home_lon, home_alt = extract_home_position(mission_path)
            px4_process = await run_px4(home_lat, home_lon, home_alt)
            await monitor_px4_and_run(px4_process, mission_name)
            print(f"--- Finalizado: {mission_name} ---")
        except Exception as e:
            print(f"Error procesando {mission_name}: {e}")

if __name__ == "__main__":
    asyncio.run(process_all_plans())