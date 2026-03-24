import os
import json
import asyncio
import sys
import signal

current_dir = os.path.dirname(os.path.abspath(__file__))

# Lista verificada en ../PX4-Autopilot/src/modules/simulation/simulator_mavlink/SimulatorMavlink.cpp
# Unidades/tipos aceptados por inject_failure(...) en esta versión.
SUPPORTED_FAILURES = [
    ("SENSOR_GYRO", "OK"),
    ("SENSOR_GYRO", "OFF"),
    ("SENSOR_GYRO", "STUCK"),
    ("SENSOR_GYRO", "GARBAGE"),
    ("SENSOR_ACCEL", "OFF"),
    ("SENSOR_ACCEL", "OK"),
    ("SENSOR_ACCEL", "STUCK"),
    ("SENSOR_ACCEL", "GARBAGE"),
    ("SENSOR_MAG", "OK"),
    ("SENSOR_MAG", "OFF"),
    ("SENSOR_MAG", "STUCK"),
    ("SENSOR_MAG", "GARBAGE"),
    ("SENSOR_BARO", "OK"),
    ("SENSOR_BARO", "OFF"),
    ("SENSOR_BARO", "STUCK"),
    ("SENSOR_BARO", "GARBAGE"),
    ("SYSTEM_MOTOR", "OK"),
    ("SYSTEM_MOTOR", "OFF")
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
    # Intentamos encontrar px4-autopilot
    px4_dir = os.path.expanduser("~/traj-runner/PX4-Autopilot") 
    if not os.path.exists(px4_dir):
        # Fallback a home directo
        px4_dir = os.path.expanduser("~/PX4-Autopilot")
    
    if not os.path.exists(px4_dir):
        # Fallback relativo
        px4_dir = os.path.abspath(os.path.join(current_dir, "../PX4-Autopilot"))

    if not os.path.exists(px4_dir):
         print(f"ADVERTENCIA: No se encuentra PX4-Autopilot en {px4_dir}. Asumiendo que estamos DENTRO de PX4 o similar.")
         px4_dir = "." # Peligroso, pero intentamos

    # Comando para Gazebo Classic en Ubuntu 20.04
    command = ["make", "px4_sitl", "gazebo-classic"]
    
    sim_speed_factor = os.getenv("SIM_SPEED_FACTOR", "50")
    headless = os.getenv("HEADLESS", "1")
    env = os.environ.copy()
    env.update({
        "PX4_SIM_SPEED_FACTOR": str(sim_speed_factor),
        "PX4_HOME_LON": str(home_lon),
        "PX4_HOME_ALT": str(home_alt),
        "PX4_HOME_LAT": str(home_lat),
        "HEADLESS": headless
    })
    
    print(f"Lanzando PX4 desde {px4_dir}...")
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
        await asyncio.wait_for(process.wait(), timeout=10)
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
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
            return
        except asyncio.TimeoutError:
            continue

async def monitor_px4_and_run(process, mission_name, unit, f_type):
    print("Esperando a que PX4 esté listo...")
    startup_markers = [
        "Startup script returned successfully",
        "Ready for takeoff!", 
        "home set",
        "Armed by external command"
    ]
    # Aumentamos timeout por si compila
    timeout_s = 300 
    loop = asyncio.get_running_loop()
    start = loop.time()

    px4_ready = False
    
    # Leemos línea a línea asíncronamente
    while True:
        if (loop.time() - start) > timeout_s:
            print("Timeout esperando a PX4.")
            break

        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
        except asyncio.TimeoutError:
            if px4_ready:
                break # Si ya estaba listo y deja de hablar, asumimos que sigue corriendo
            continue # Si no, seguimos esperando

        if not line:
            print("PX4 se cerró inesperadamente.")
            break
            
        decoded_line = line.decode('utf-8', errors='ignore').strip()
        # print(f"[PX4] {decoded_line}") # Descomentar para debug detallado

        if any(m in decoded_line for m in startup_markers):
            if not px4_ready:
                print(f"PX4 detectado listo ({decoded_line}). Iniciando script de misión...")
                px4_ready = True
                
                # Ejecutar script de misión
                # Llamada a Singular CargarEjecutarFailure.py
                mavsdk_script = os.path.join(current_dir, "CargarEjecutarFailure.py")
                mavsdk_cmd = [sys.executable, mavsdk_script, mission_name, unit, f_type]
                
                print(f"Ejecutando: {' '.join(mavsdk_cmd)}")
                mavsdk_proc = await asyncio.create_subprocess_exec(*mavsdk_cmd)
                await mavsdk_proc.wait()
                
                print("Script de misión finalizado. Cerrando simulación.")
                await shutdown_px4(process)
                return

async def run_single_mission(mission_name, unit, f_type):
    planes_dir = os.path.join(current_dir, "Planes")
    mission_path = os.path.join(planes_dir, f"{mission_name}.plan")
    
    if not os.path.exists(mission_path):
        print(f"No existe el plan {mission_path}")
        return

    home_lat, home_lon, home_alt = extract_home_position(mission_path)
    
    px4_process = await run_px4(home_lat, home_lon, home_alt)
    try:
        await monitor_px4_and_run(px4_process, mission_name, unit, f_type)
    except Exception as e:
        print(f"Excepción controlando PX4: {e}")
        await shutdown_px4(px4_process)

async def main():
    planes_dir = os.path.join(current_dir, "Planes")
    if not os.path.exists(planes_dir):
        print("Crea un directorio 'Planes' con archivos .plan")
        return

    archivos_plan = [f for f in os.listdir(planes_dir) if f.endswith('.plan')]
    if not archivos_plan:
        print("No hay planes en 'Planes/'")
        return

    for plan_file in archivos_plan:
        mission_name = plan_file.replace(".plan", "")
        for unit, f_type in FAILURES_TO_TEST:
            print(f"==================================================")
            print(f" PLAN: {mission_name} | FALLO: {unit} {f_type}")
            print(f"==================================================")
            await run_single_mission(mission_name, unit, f_type)
            await asyncio.sleep(2) # Pausa entre simulaciones

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
