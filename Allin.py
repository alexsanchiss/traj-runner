import json
import os
import asyncio
import time

def extract_home_position(mission_path):
    """Extrae la posición del hogar desde el archivo de misión."""
    with open(mission_path, 'r') as f:
        mission_json = json.load(f)
        
    planned_home_position = mission_json["mission"].get("plannedHomePosition", None)
    
    if planned_home_position is not None:
        return planned_home_position[0], planned_home_position[1], planned_home_position[2]
    else:
        raise ValueError("No se encontró la posición planificada en el archivo de misión.")

async def monitor_px4_output(process, mission_name):
    """Monitorea la salida de PX4 en busca del mensaje 'Ready for takeoff!'."""
    while True:
        output = await process.stdout.readline()
        if output == b'' and process.returncode is not None:
            break
        if output:
            output_decoded = output.decode('utf-8').strip()
            print(output_decoded)
            if "Ready for takeoff!" in output_decoded:
                print("Mensaje detectado: Ready for takeoff!")
                await run_mavsdk_mission(mission_name)  # Pasa el mission_name
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
    mavsdk_command = ["python3", "/home/asanmar4/PythonPruebas/CargarEjecutar.py", mission_name]
    mavsdk_process = await asyncio.create_subprocess_exec(*mavsdk_command)
    await mavsdk_process.wait()  # Esperar a que el script MAVSDK termine
    print("MAVSDK misión finalizada. Cerrando procesos...")

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

async def process_mission_file(mission_path):
    """Procesa un archivo de misión, ejecutando PX4 y MAVSDK."""
    mission_name = os.path.basename(mission_path).replace('.plan', '')
    home_lat, home_lon, home_alt = extract_home_position(mission_path)
    print(f"Procesando misión: {mission_name}")
    print(f"Posición del hogar extraída: LAT={home_lat}, LON={home_lon}, ALT={home_alt}")

    # Cambiar al directorio PX4-Autopilot
    os.chdir(os.path.expanduser("~/PX4-Autopilot"))
    print("Cambiado al directorio: ~/PX4-Autopilot")

    # Ejecutar PX4
    px4_process = await run_px4(home_lat, home_lon, home_alt)

    # Monitorear la salida de PX4, pasando el mission_name
    await monitor_px4_output(px4_process, mission_name)

    # Borrar el archivo procesado
    os.remove(mission_path)
    print(f"Archivo procesado y eliminado: {mission_path}")

async def monitor_plan_directory():
    """Monitorea la carpeta de planes en busca de nuevos archivos."""
    watched_directory = '/home/asanmar4/PythonPruebas/Planes'
    processed_files = set()

    while True:
        # Listar todos los archivos .plan en el directorio
        mission_files = [f for f in os.listdir(watched_directory) if f.endswith('.plan')]
        print('Buscando actualizaciones...')
        # Procesar cada archivo que no ha sido procesado aún
        for mission_file in mission_files:
            if mission_file not in processed_files:
                mission_path = os.path.join(watched_directory, mission_file)
                await process_mission_file(mission_path)
                processed_files.add(mission_file)  # Marcar el archivo como procesado

        await asyncio.sleep(5)  # Esperar 5 segundos antes de volver a revisar

if __name__ == "__main__":
    try:
        asyncio.run(monitor_plan_directory())
    except Exception as e:
        print(f"Error en la ejecución principal: {e}")
