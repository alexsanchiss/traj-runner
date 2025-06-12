import os
import json
import asyncio
import requests
import aiomysql
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
UAS_PLANNER_DB = os.getenv("UAS_PLANNER_DB", "localhost")
DB_USER = os.getenv("DB_USER", "asanmar4")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "upps")

# Obtener el nombre de la distro para asignarla como nombre de la máquina
machine_name = os.getenv("WSL_DISTRO_NAME", "holamundo")

# Configuración global
current_dir = os.path.dirname(os.path.abspath(__file__))
machine_id = None

async def connect_to_db():
    try:
        conn = await aiomysql.connect(
            host=UAS_PLANNER_DB,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            autocommit=True
        )
        print("Conexión a la base de datos establecida.")
        return conn
    except Exception as e:
        print(f"Error al conectar con la base de datos: {e}")
        raise

# Funciones auxiliares para la base de datos

async def register_or_update_machine(conn):
    global machine_id
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("INSERT INTO machine (name, status) VALUES (%s, %s)", (machine_name, "Disponible"))
            await cur.execute("SELECT LAST_INSERT_ID()")
            machine_id = (await cur.fetchone())["LAST_INSERT_ID()"]
            print(f"Máquina registrada con ID: {machine_id}")
    except Exception as e:
        print(f"Error al registrar la máquina: {e}")

async def update_machine_status(conn, status):
    if machine_id:
        try:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE machine SET status = %s WHERE id = %s", (status, machine_id))
                print(f"Estado de la máquina actualizado a: {status}")
        except Exception as e:
            print(f"Error al actualizar el estado de la máquina: {e}")

async def update_plan_status(conn, plan_id, status, csv_result):
    try:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE flightPlan SET status = %s, csvResult = %s WHERE id = %s", (status, 1, plan_id))
            await cur.execute("""
                INSERT INTO csvResult (id, csvResult) VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE csvResult = %s
            """, (plan_id, csv_result, csv_result))
            print(f"Estado del plan {plan_id} actualizado a: {status}")
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
        "make", "px4_sitl", "gazebo-classic_standard_vtol"
    ]
    env = os.environ.copy()
    env.update({
        "PX4_SIM_SPEED_FACTOR": "1",
        "PX4_HOME_LON": str(home_lon),
        "PX4_HOME_ALT": str(home_alt),
        "PX4_HOME_LAT": str(home_lat)
    })
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env, stdin=asyncio.subprocess.PIPE
    )
    return process

async def monitor_px4_output(process, mission_name):
    print("Esperando a que PX4 esté listo...")
    while True:
        try:
            line = await process.stdout.readline()
            print(line)
            if not line:
                if process.returncode is not None:
                    print("El proceso PX4 terminó antes de que apareciera 'Ready for takeoff!'")
                    break
                continue
            decoded_line = line.decode().strip()
            print(decoded_line)
            if "Ready for takeoff!" in decoded_line:
                print("Mensaje 'Ready for takeoff!' detectado")
                await run_mavsdk_mission(mission_name)
                await shutdown_px4(process)
                break
        except Exception as e:
            print(f"Error al monitorear la salida de PX4: {e}")
            break
            
async def shutdown_px4(process):
    """Envia el comando de cierre a PX4."""
    print("Enviando comando de shutdown a PX4...")
    process.stdin.write(b'shutdown\n')  # Escribir el comando de cierre
    await process.stdin.drain()  # Asegurarse de que se envíe
    await process.wait()  # Esperar a que se complete el proceso

async def run_mavsdk_mission(mission_name):
    """Ejecuta el script de MAVSDK en un nuevo proceso."""
    mavsdk_command = ["python3", f"{current_dir}/CargarEjecutarAMQP.py", str(mission_name)]
    mavsdk_process = await asyncio.create_subprocess_exec(*mavsdk_command)
    await mavsdk_process.wait()  # Esperar a que el script MAVSDK termine
    print("MAVSDK misión finalizada. Cerrando procesos...")


async def process_flight_plan(conn, plan):
    plan_id = plan["id"]

    if not os.path.exists(f"{current_dir}/Planes"):
        os.makedirs(f"{current_dir}/Planes")
    if not os.path.exists(f"{current_dir}/Trayectorias"):
        os.makedirs(f"{current_dir}/Trayectorias")
    with open(f"{current_dir}/Trayectorias/{plan_id}_log.csv", 'w') as file:
        pass
    print(f"Archivo en blanco creado en: {current_dir}/Trayectorias/{plan_id}_log.csv")

    mission_path = os.path.join(current_dir, "Planes", f"{plan_id}.plan")
    
    # Guardar el archivo del plan de vuelo
    try:
        with open(mission_path, 'w') as f:
            f.write(plan["fileContent"])
        print(f"Archivo del plan de vuelo guardado: {mission_path}")
    except Exception as e:
        print(f"Error al guardar el archivo del plan: {e}")
        await update_machine_status(conn, "Error")
        return

    # Procesar el plan de vuelo
    home_lat, home_lon, home_alt = extract_home_position(mission_path)
    print(home_lat, home_lon, home_alt)
    try:
        os.chdir(os.path.expanduser("../PX4-Autopilot"))
        px4_process = await run_px4(home_lat, home_lon, home_alt)
        await monitor_px4_output(px4_process, plan_id)
    except Exception as e:
        print(f"Error en el procesamiento: {e}")
        await update_machine_status(conn, "Error")
        return

    # Leer el resultado CSV y actualizar el plan
    csv_result = await read_csv_result(plan_id)
    await update_plan_status(conn, plan_id, "procesado", csv_result)

    # Borrar archivos temporales
    os.remove(mission_path)
    os.remove(f"{current_dir}/Trayectorias/{plan_id}_log.csv")
    print(f"Archivo procesado y eliminado: {mission_path}")

    # Actualizar estado de la máquina a "Disponible"
    await update_machine_status(conn, "Disponible")

async def read_csv_result(plan_id):
    """Leer el archivo CSV procesado para actualizar el plan de vuelo."""
    csv_path = os.path.join(current_dir, "Trayectorias", f"{plan_id}_log.csv")
    with open(csv_path, 'r') as csv_file:
        csv_content = csv_file.read()
    return csv_content

# Monitorear planes de vuelo
async def monitor_flight_plan(conn):
    while True:
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT * FROM flightPlan WHERE machineAssignedId = %s AND status = %s", (machine_id, "procesando"))
                plans = await cur.fetchall()
                
                for plan in plans:
                    await process_flight_plan(conn, plan)

            await asyncio.sleep(5)  # Pausa entre verificaciones
        except Exception as e:
            print(f"Error al monitorear los planes de vuelo: {e}")
            await asyncio.sleep(5)

async def main():
    conn = await connect_to_db()
    await register_or_update_machine(conn)
    await monitor_flight_plan(conn)

if __name__ == "__main__":
    asyncio.run(main())