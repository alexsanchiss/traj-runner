#!/usr/bin/env python3

import asyncio
import csv
import json
from mavsdk import System
import time
import sys

# Variables globales para almacenar los datos de GPS y usarlos en el bucle de odometría
current_lat = None
current_lon = None
current_alt = None
last_lat = None
last_lon = None
last_alt = None

async def run(mission_name):  # Recibir el mission_name como argumento
    try:
        global last_lat, last_lon, last_alt
        # Conectar al dron
        drone = System()
        await drone.connect(system_address="udp://:14540")

        print("Esperando a que el dron se conecte...")
        async for state in drone.core.connection_state():
            if state.is_connected:
                print(f"-- Conectado al dron!")
                break

        # Leer el archivo JSON de la misión
        mission_path = f"/home/asanmar4/PythonPruebas/Planes/{mission_name}.plan"  # Usar mission_name del argumento
        with open(mission_path, 'r') as f:
            mission_json = json.load(f)

        # Extraer los waypoints y la posición de inicio
        mission_items = mission_json["mission"]["items"]
        planned_home_position = mission_json["mission"].get("plannedHomePosition", None)

        last_wp = mission_items[-1] if mission_items else None
        if last_wp and planned_home_position:
            if last_wp["command"] == 20:
                last_lat = planned_home_position[0]
                last_lon = planned_home_position[1]
                last_alt = planned_home_position[2]
            else:
                last_lat = last_wp["params"][4]  # Latitud del último waypoint
                last_lon = last_wp["params"][5]  # Longitud del último waypoint
                last_alt = last_wp["params"][6]  # Altitud del último waypoint

        # Subir la misión al dron usando MAVSDK
        mission = await drone.mission_raw.import_qgroundcontrol_mission(mission_path)
        await drone.mission_raw.upload_mission(mission.mission_items)

        if len(mission.rally_items) > 0:
            await drone.mission_raw.upload_rally_points(mission.rally_items)

        print("Misión cargada.")

        # Esperar a que el dron esté listo para volar
        print("Esperando la estimación de posición global...")
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                print("-- Estimación de posición global OK")
                break

        await attempt_takeoff(drone)

        # Crear el archivo CSV para registrar los datos
        with open('/home/asanmar4/PythonPruebas/Trayectorias/' + mission_name + '_log.csv', mode='w') as csv_file:
            fieldnames = ['SimTime', 'X', 'Y', 'Z', 'qw', 'qx', 'qy', 'qz', 'Vx', 'Vy', 'Vz', 'Lat', 'Lon', 'Alt']
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            tasks = [
                asyncio.create_task(log_odometry(drone, writer)),
                asyncio.create_task(log_gps(drone))
            ]

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            for task in pending:
                task.cancel()

    except asyncio.CancelledError:
        print("Todas las tareas han sido canceladas.")

async def attempt_takeoff(drone):
    """Intentar armar el dron y comenzar la misión, reintentando si es necesario."""
    max_attempts = 5
    attempt = 0
    while attempt < max_attempts:
        try:
            print(f"-- Intento {attempt + 1} de armar y despegar el dron")
            
            # Armar el dron
            await drone.action.arm()

            # Iniciar la misión
            await drone.mission_raw.start_mission()

            # Esperar a que el dron esté en el aire
            start_time = time.time()
            async for in_air in drone.telemetry.in_air():
                if in_air:
                    print("-- El dron ha despegado!")
                    return
                elif time.time() - start_time > 1:  # Si han pasado más de 1 segundo
                    print("-- El dron no ha despegado. Reintentando...")
                    break

        except Exception as e:
            print(f"Error en intento de despegue: {e}")

        attempt += 1
        await asyncio.sleep(1)  # Esperar un poco antes de reintentar

    raise RuntimeError("No se pudo armar y despegar el dron después de varios intentos.")

async def log_odometry(drone, writer):
    global current_lat, current_lon, current_alt, last_lat, last_lon, last_alt
    a = 1
    b = 0
    c = 1
    # Grabar datos de los sensores durante el vuelo
    print("-- Grabando datos de los sensores")

    # Crear un bucle para leer datos de odometría
    async for odom in drone.telemetry.odometry():
        sim_time_us = odom.time_usec
        sim_time_s = sim_time_us / 1e6  # Convertir a segundos
        x, y, z = odom.position_body.x_m, odom.position_body.y_m, odom.position_body.z_m
        vx, vy, vz = odom.velocity_body.x_m_s, odom.velocity_body.y_m_s, odom.velocity_body.z_m_s
        qw, qx, qy, qz = odom.q.w, odom.q.x, odom.q.y, odom.q.z  # Usamos cuaternión

        # Guardar los datos en el archivo CSV junto con la información GPS actual
        writer.writerow({
            'SimTime': sim_time_s, 'X': x, 'Y': y, 'Z': z,
            'qw': qw, 'qx': qx, 'qy': qy, 'qz': qz,
            'Vx': vx, 'Vy': vy, 'Vz': vz,
            'Lat': current_lat, 'Lon': current_lon, 'Alt': current_alt
        })

        # Comprobar si el dron ha aterrizado
        if current_lat is not None and current_lon is not None and current_alt is not None:
            a += 1
            if (b == 0 and abs(current_lat - last_lat) < 0.01 and abs(current_lon - last_lon) < 0.01 and abs(current_alt - last_alt) < 0.5 and a > 1000):
                b = 1
                c = a
            if b == 1 and (a - c) > 1000:
                print("-- El plan de vuelo ha terminado.")
                return  # Finalizar la función y el script cuando se cumplan las condiciones

async def log_gps(drone):
    global current_lat, current_lon, current_alt
    # Leer información de GPS y actualizar las variables globales
    async for gps_info in drone.telemetry.position():
        current_lat = gps_info.latitude_deg
        current_lon = gps_info.longitude_deg
        current_alt = gps_info.absolute_altitude_m

async def main():
    # Capturar el argumento de línea de comandos para el mission_name
    mission_name = sys.argv[1]
    await run(mission_name)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        print("Script finalizado.")