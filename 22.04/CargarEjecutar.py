#!/usr/bin/env python3

import asyncio
import csv
import json
import math
from mavsdk import System
import time
import sys
import os

# Variables globales para almacenar los datos de GPS y usarlos en el bucle de odometría
current_lat = None
current_lon = None
current_alt = None
last_lat = None
last_lon = None
last_alt = None
inic_alt = None

current_dir = os.path.dirname(os.path.abspath(__file__))

async def run(mission_name):  # Recibir el mission_name como argumento
    try:
        global last_lat, last_lon, last_alt, inic_alt
        # Conectar al dron
        drone = System()
        await drone.connect(system_address="udp://:14540")

        print("Esperando a que el dron se conecte...")
        async for state in drone.core.connection_state():
            if state.is_connected:
                print(f"-- Conectado al dron!")
                break

        # Leer el archivo JSON de la misión
        mission_path = f"{current_dir}/Planes/{mission_name}.plan"  # Usar mission_name del argumento
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
                inic_alt = 0
            else:
                last_lat = last_wp["params"][4]  # Latitud del último waypoint
                last_lon = last_wp["params"][5]  # Longitud del último waypoint
                last_alt = last_wp["params"][6]  # Altitud del último waypoint
                inic_alt = planned_home_position[2]

        # Subir la misión al dron usando MAVSDK
        mission = await drone.mission_raw.import_qgroundcontrol_mission(mission_path)
        await drone.mission_raw.upload_mission(mission.mission_items)

        if len(mission.rally_items) > 0:
            await drone.mission_raw.upload_rally_points(mission.rally_items)

        print(f"Misión {mission_name} cargada.")

        # Esperar a que el dron esté listo para volar
        print("Esperando la estimación de posición global...")
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                print("-- Estimación de posición global OK")
                break

        await attempt_takeoff(drone)

        # Crear el archivo CSV para registrar los datos
        trayectorias_dir = f"{current_dir}/Trayectorias"
        if not os.path.exists(trayectorias_dir):
            os.makedirs(trayectorias_dir)
        with open(f'{current_dir}/Trayectorias/' + mission_name + '_log.csv', mode='w') as csv_file:
            fieldnames = ['SimTime', 'Lat', 'Lon', 'Alt', 'qw', 'qx', 'qy', 'qz', 'Vx', 'Vy', 'Vz']
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            odom_task = asyncio.create_task(log_odometry(drone, writer))
            gps_task = asyncio.create_task(log_gps(drone))
            
            # Esperamos a que termine log_odometry (fin de mision/aterrizaje)
            # Usamos wait para poder manejar excepciones o cancelaciones de manera segura
            done, pending = await asyncio.wait({odom_task, gps_task}, return_when=asyncio.FIRST_COMPLETED)

            print("-- Condición de fin detectada. Limpiando tareas...")

            # Cancelamos explícitamente todo lo que siga vivo
            tasks_to_cancel = [gps_task, odom_task]
            for task in tasks_to_cancel:
                if not task.done():
                    task.cancel()
            
            # Esperamos a que se completen las cancelaciones para evitar errores como "Event Loop Closed"
            # return_exceptions=True silencia CancelledError
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            print("-- Tareas cerradas correctamente.")

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
    first_near_goal_time = None
    last_logged_second = None
    # Grabar datos de los sensores durante el vuelo
    print("-- Grabando datos de los sensores")

    umbral_espera_s = 20.0

    # Crear un bucle para leer datos de odometría
    async for odom in drone.telemetry.odometry():
        sim_time_us = odom.time_usec
        sim_time_s = sim_time_us / 1e6  # Convertir a segundos

        # Limitar el registro a 1 Hz según segundo simulado.
        current_second = math.floor(sim_time_s)
        if last_logged_second is not None and current_second == last_logged_second:
            continue
        last_logged_second = current_second

        vx, vy, vz = odom.velocity_body.x_m_s, odom.velocity_body.y_m_s, odom.velocity_body.z_m_s
        qw, qx, qy, qz = odom.q.w, odom.q.x, odom.q.y, odom.q.z  # Usamos cuaternión

        # Logging robusto de quaterniones (4 decimales para no perder info como 0.9 vs 1.0)
        writer.writerow({
            'SimTime': round(sim_time_s, 1),
            'Lat': round(current_lat, 7) if current_lat else None,
            'Lon': round(current_lon, 7) if current_lon else None,
            'Alt': round(current_alt - inic_alt, 2) if current_alt else None,
            'qw': round(qw, 4),
            'qx': round(qx, 4),
            'qy': round(qy, 4),
            'qz': round(qz, 4),
            'Vx': round(vx, 2),
            'Vy': round(vy, 2),
            'Vz': round(vz, 2)
        })

        # Comprobar si el dron ha aterrizado
        if current_lat is not None and current_lon is not None and current_alt is not None and inic_alt is not None:
            # Calculo de altitud relativa
            rel_alt_current = current_alt - inic_alt
            
            # Condicion 1: Cerca del objetivo final (logica original)
            near_goal = (
                abs(current_lat - last_lat) < 0.01 and
                abs(current_lon - last_lon) < 0.01 and
                abs(rel_alt_current - (last_alt if last_alt else 0)) < 0.5
            )

            # Condicion 2: Aterrizaje o Crash (velocidad horizontal nula cerca del suelo)
            vh = math.sqrt(vx*vx + vy*vy)
            landed_or_stopped = (rel_alt_current < 1.0) and (vh < 0.1)
            
            # Condicion 3: Fallo catastrafico hundido bajo tierra (-5m)
            underground_cutoff = rel_alt_current < -5.0

            if near_goal or landed_or_stopped or underground_cutoff:
                if first_near_goal_time is None:
                    first_near_goal_time = sim_time_s
                elif (sim_time_s - first_near_goal_time) >= umbral_espera_s:
                    print(f"-- Fin detectado (Goal={near_goal}, Landed/Stopped={landed_or_stopped}, Underground={underground_cutoff})")
                    return  # Finalizar la función y el script
            else:
                first_near_goal_time = None

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