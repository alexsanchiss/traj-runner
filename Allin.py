import json
import os
import asyncio

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

async def main():
    mission_name = "UPV1"  # Aquí defines el nombre de la misión
    mission_path = f"/home/asanmar4/PythonPruebas/Planes/{mission_name}.plan"

    try:
        # Extraer la posición del hogar
        home_lat, home_lon, home_alt = extract_home_position(mission_path)
        print(f"Posición del hogar extraída: LAT={home_lat}, LON={home_lon}, ALT={home_alt}")

        # Cambiar al directorio PX4-Autopilot
        os.chdir(os.path.expanduser("~/PX4-Autopilot"))
        print("Cambiado al directorio: ~/PX4-Autopilot")

        # Ejecutar PX4
        px4_process = await run_px4(home_lat, home_lon, home_alt)

        # Monitorear la salida de PX4, pasando el mission_name
        await monitor_px4_output(px4_process, mission_name)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error en la ejecución principal: {e}")
