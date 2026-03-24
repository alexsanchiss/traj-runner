import os
import json
import asyncio
import itertools
import sys
import signal
import re
import subprocess

current_dir = os.path.dirname(os.path.abspath(__file__))

# Extraído directamente del código fuente de PX4 (simulator_mavlink.cpp)
SUPPORTED_FAILURES = [
    ("SENSOR_GPS", "OFF"),
    ("SENSOR_ACCEL", "OFF"),
    ("SENSOR_ACCEL", "STUCK"),
    ("SENSOR_GYRO", "OFF"),
    ("SENSOR_GYRO", "STUCK"),
    ("SENSOR_MAG", "OFF"),
    ("SENSOR_MAG", "STUCK"),
    ("SENSOR_BARO", "OFF"),
    ("SENSOR_BARO", "STUCK"),
    ("SENSOR_AIRSPEED", "OFF"),
    ("SENSOR_AIRSPEED", "WRONG"),
    ("SENSOR_VIO", "OFF")
]

FAILURES_TO_TEST = SUPPORTED_FAILURES

def extract_home_position(mission_path):
    with open(mission_path, 'r') as f:
        mission_json = json.load(f)
        
    planned_home_position = mission_json["mission"].get("plannedHomePosition", None)
    
    if planned_home_position is not None:
        return planned_home_position[0], planned_home_position[1], planned_home_position[2]
    raise ValueError("No se encontró la posición planificada en el archivo de misión.")

async def run_px4(home_lat, home_lon, home_alt):
    sim_speed_factor = os.getenv("SIM_SPEED_FACTOR", "50")
    headless = os.getenv("HEADLESS", "1")
    world_speed_factor = float(os.getenv("WORLD_SPEED_FACTOR", "50"))
    command = ["make", "px4_sitl", "gz_x500", f"SIM_SPEED_FACTOR={sim_speed_factor}"]

    px4_dir = os.path.expanduser("../PX4-Autopilot")
    worlds_dir = os.path.join(px4_dir, "Tools/simulation/gz/worlds")
    custom_world_path = os.path.join(worlds_dir, "custom_mission_world.sdf")
    
    try:
        with open(os.path.join(worlds_dir, "default.sdf"), 'r') as f:
            world_xml = f.read()
            
        world_xml = re.sub(r'<latitude_deg>[^<]*</latitude_deg>', f'<latitude_deg>{home_lat}</latitude_deg>', world_xml)
        world_xml = re.sub(r'<longitude_deg>[^<]*</longitude_deg>', f'<longitude_deg>{home_lon}</longitude_deg>', world_xml)
        world_xml = re.sub(r'<elevation>[^<]*</elevation>', f'<elevation>{home_alt}</elevation>', world_xml)

        # En gz_x500 la velocidad efectiva depende de la física del mundo, no de PX4_SIM_SPEED_FACTOR.
        base_max_step_size = 0.004
        base_real_time_update_rate = 250.0
        world_real_time_update_rate = max(1.0, base_real_time_update_rate * world_speed_factor)
        world_xml = re.sub(r'<max_step_size>[^<]*</max_step_size>', f'<max_step_size>{base_max_step_size}</max_step_size>', world_xml, count=1)
        world_xml = re.sub(r'<real_time_update_rate>[^<]*</real_time_update_rate>', f'<real_time_update_rate>{world_real_time_update_rate:.3f}</real_time_update_rate>', world_xml, count=1)
        # El real_time_factor actúa como límite superior (throttling). Si se deja en 1.0, Gazebo frena para no superar tiempo real.
        # Se debe establecer al mismo factor deseado (o 0 para "lo más rápido posible").
        world_xml = re.sub(r'<real_time_factor>[^<]*</real_time_factor>', f'<real_time_factor>{world_speed_factor}</real_time_factor>', world_xml, count=1)
        world_xml = world_xml.replace('<world name="default">', '<world name="custom_mission_world">')

        # ACTUALIZACION: Aumentar el tamaño del plano de suelo (ground_plane) para cubrir al menos 10km de radio.
        # Asegurando colisión en 20km x 20km.
        world_xml = world_xml.replace('<size>1 1</size>', '<size>20000 20000</size>')
        world_xml = world_xml.replace('<size>500 500</size>', '<size>20000 20000</size>')

        with open(custom_world_path, 'w') as f:
            f.write(world_xml)
    except Exception as e:
        print(f"Error modificando el default.sdf: {e}")

    env = os.environ.copy()
    env.update({
        "HEADLESS": headless,
        "SIM_SPEED_FACTOR": str(sim_speed_factor),
        "PX4_SIM_SPEED_FACTOR": str(sim_speed_factor),
        "PX4_HOME_LON": str(home_lon),
        "PX4_HOME_ALT": str(home_alt),
        "PX4_HOME_LAT": str(home_lat),
        "PX4_GZ_WORLD": "custom_mission_world"
    })

    print(f"-- Lanzando PX4 con SIM_SPEED_FACTOR={sim_speed_factor} (compat), WORLD_SPEED_FACTOR={world_speed_factor}")
    print(f"-- Mundo custom physics: max_step_size=0.004, real_time_update_rate={world_real_time_update_rate:.3f}")
    
    process = await asyncio.create_subprocess_exec(
        *command, 
        stdout=asyncio.subprocess.PIPE, 
        stderr=asyncio.subprocess.STDOUT, 
        env=env, 
        stdin=asyncio.subprocess.PIPE, 
        cwd=px4_dir
    )
    return process

async def shutdown_px4(process):
    print("Cerrando PX4...")
    if process.returncode is not None:
        return

    if process.stdin is not None:
        try:
            process.stdin.write(b'shutdown\n')
            await process.stdin.drain()
        except Exception:
            pass

    try:
        await asyncio.wait_for(process.wait(), timeout=20)
        return
    except asyncio.TimeoutError:
        pass

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        if process.returncode is not None:
            return
        try:
            process.send_signal(sig)
        except ProcessLookupError:
            return
        wait_time = 8 if sig != signal.SIGKILL else 3
        try:
            await asyncio.wait_for(process.wait(), timeout=wait_time)
            return
        except asyncio.TimeoutError:
            continue

async def monitor_px4_and_run(process, mission_name, unit, f_type):
    print("Esperando a que PX4 esté listo...")
    startup_markers = (
        "Startup script returned successfully",
        "Ready for takeoff!",
        "INFO  [tone_alarm] home set",
        "INFO  [commander] Ready for takeoff",
    )
    timeout_s = 180
    loop = asyncio.get_running_loop()
    start = loop.time()

    while True:
        if (loop.time() - start) > timeout_s:
            raise TimeoutError("PX4 no quedó listo dentro del tiempo esperado.")

        line = await process.stdout.readline()
        if not line:
            raise RuntimeError("El proceso de PX4 terminó antes de estar listo.")
        decoded_line = line.decode().strip()
        print(decoded_line)
        
        if any(marker in decoded_line for marker in startup_markers):
            print(f"Iniciando MAVSDK para {mission_name} con fallo {unit} - {f_type}...")
            mavsdk_command = [sys.executable, f"{current_dir}/CargarEjecutarFailure.py", mission_name, unit, f_type]
            mavsdk_process = await asyncio.create_subprocess_exec(*mavsdk_command)
            await mavsdk_process.wait() 

            await shutdown_px4(process)
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

    max_failures_env = os.getenv("MAX_FAILURES_PER_PLAN")
    max_failures = int(max_failures_env) if max_failures_env else None

    for archivo in archivos_plan:
        mission_name = archivo.replace('.plan', '')
        mission_path = os.path.join(planes_dir, archivo)
        home_lat, home_lon, home_alt = extract_home_position(mission_path)
        failures_to_run = FAILURES_TO_TEST if max_failures is None else FAILURES_TO_TEST[:max_failures]
        
        for unit, f_type in failures_to_run:
            print(f"\n--- Procesando: {mission_name} | Fallo: {unit} ({f_type}) ---")
            try:
                subprocess.run("pkill -f 'px4|gz sim|gz-server|gz client'", shell=True, stderr=subprocess.DEVNULL)
                await asyncio.sleep(1)

                px4_process = await run_px4(home_lat, home_lon, home_alt)
                await monitor_px4_and_run(px4_process, mission_name, unit, f_type)
                
                subprocess.run("pkill -f 'px4|gz sim|gz-server|gz client'", shell=True, stderr=subprocess.DEVNULL)
                await asyncio.sleep(1)

                print(f"--- Finalizado: {mission_name} | Fallo: {unit} ({f_type}) ---")
            except Exception as e:
                print(f"Error procesando {mission_name} con fallo {unit}-{f_type}: {e}")
                subprocess.run("pkill -f 'px4|gz sim|gz-server|gz client'", shell=True, stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    asyncio.run(process_all_plans_with_failures())