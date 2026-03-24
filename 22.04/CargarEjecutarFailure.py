#!/usr/bin/env python3

import asyncio
import csv
import json
import math
import time
import sys
import os

from mavsdk import System
from mavsdk.failure import FailureUnit, FailureType

global current_lat, current_lon, current_alt, last_lat, last_lon, last_alt, inic_alt
current_lat = None
current_lon = None
current_alt = None
last_lat = None
last_lon = None
last_alt = None
inic_alt = None

current_dir = os.path.dirname(os.path.abspath(__file__))

async def run(mission_name, unit_str, f_type_str):
    try:
        global last_lat, last_lon, last_alt, inic_alt
        drone = System()
        await drone.connect(system_address="udp://:14540")

        print("Esperando a que el dron se conecte...")
        async for state in drone.core.connection_state():
            if state.is_connected:
                print("-- Conectado al dron!")
                break

        # Habilitar inyección de fallos en PX4
        await drone.param.set_param_int("SYS_FAILURE_EN", 1)

        mission_path = f"{current_dir}/Planes/{mission_name}.plan"
        with open(mission_path, 'r') as f:
            mission_json = json.load(f)

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
                last_lat = last_wp["params"][4]
                last_lon = last_wp["params"][5]
                last_alt = last_wp["params"][6]
                inic_alt = planned_home_position[2]

        mission = await drone.mission_raw.import_qgroundcontrol_mission(mission_path)
        await drone.mission_raw.upload_mission(mission.mission_items)

        if len(mission.rally_items) > 0:
            await drone.mission_raw.upload_rally_points(mission.rally_items)

        print("Esperando la estimación de posición global...")
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                print("-- Estimación de posición global OK")
                break

        await attempt_takeoff(drone)

        trayectorias_dir = f"{current_dir}/Trayectorias"
        os.makedirs(trayectorias_dir, exist_ok=True)
        
        # Nombrar el CSV incluyendo los datos del fallo inyectado
        csv_filename = f"{trayectorias_dir}/{mission_name}_{unit_str}_{f_type_str}_log.csv"
        
        with open(csv_filename, mode='w') as csv_file:
            fieldnames = ['SimTime', 'Lat', 'Lon', 'Alt', 'qw', 'qx', 'qy', 'qz', 'Vx', 'Vy', 'Vz']
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            inject_task = asyncio.create_task(inject_failure_on_cruise(drone, unit_str, f_type_str))
            gps_task = asyncio.create_task(log_gps(drone))
            odom_task = asyncio.create_task(log_odometry(drone, writer))

            # Esperamos a que termine log_odometry (fin de mision/aterrizaje)
            # Usamos wait para poder manejar excepciones o cancelaciones de manera segura
            done, pending = await asyncio.wait({odom_task, gps_task}, return_when=asyncio.FIRST_COMPLETED)

            print("-- Condición de fin detectada. Limpiando tareas...")

            # Cancelamos explícitamente todo lo que siga vivo
            tasks_to_cancel = [inject_task, gps_task, odom_task]
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
    max_attempts = 5
    attempt = 0
    while attempt < max_attempts:
        try:
            print(f"-- Intento {attempt + 1} de armar y despegar el dron")
            await drone.action.arm()
            await drone.mission_raw.start_mission()

            start_time = time.time()
            async for in_air in drone.telemetry.in_air():
                if in_air:
                    print("-- El dron ha despegado!")
                    return
                elif time.time() - start_time > 1:
                    print("-- El dron no ha despegado. Reintentando...")
                    break
        except Exception as e:
            print(f"Error en intento de despegue: {e}")

        attempt += 1
        await asyncio.sleep(1)

    raise RuntimeError("No se pudo armar y despegar el dron después de varios intentos.")

async def inject_failure_on_cruise(drone, unit_str, f_type_str):
    """Espera a que el dron esté en el aire, da un margen para el crucero e inyecta el fallo."""
    async for in_air in drone.telemetry.in_air():
        if in_air:
            break
            
    # Tiempo de espera para que el dron alcance la altitud de crucero hacia el primer WP
    await asyncio.sleep(8)
    
    print(f"-- Inyectando fallo (vía MAVLink Shell / NSH): {unit_str} - {f_type_str}")
    try:
        # Formateo del comando de consola: "failure <unit> <type>[-i <instance>]"
        # unit_str viene como "SENSOR_GPS", lo mapeamos a "gps"
        unit_shell = unit_str.replace("SENSOR_", "").replace("SYSTEM_", "").lower()
        type_shell = f_type_str.lower()
        
        # El comando failure en px4 recibe "failure gps off" o "failure mag stuck"
        shell_cmd = f"failure {unit_shell} {type_shell}"
        
        # Mapeo de casos especiales si los nombres de shell no son directos
        if unit_shell == "accel": unit_shell = "accel"
        elif unit_shell == "gyro": unit_shell = "gyro"
        elif unit_shell == "mag": unit_shell = "mag"
        elif unit_shell == "baro": unit_shell = "baro"
        elif unit_shell == "airspeed": unit_shell = "airspeed"
        elif unit_shell == "vio": unit_shell = "vio"
        
        print(f"   => Ejecutando comando NSH: {shell_cmd}")
        
        # Se envía por el puerto de terminal NSH. Shell.send procesa el string puro
        await drone.shell.send(shell_cmd + '\n')
        
        # Le damos un pequeño margen para procesar el comando
        await asyncio.sleep(1)
        print("-- Fallo inyectado correctamente vía Shell")
    except Exception as e:
        print(f"Error crítico enviando comando por Shell: {e}")

async def log_odometry(drone, writer):
    first_near_goal_time = None
    last_logged_second = None
    print("-- Grabando datos de los sensores")

    umbral_espera_s = 20.0

    async for odom in drone.telemetry.odometry():
        sim_time_us = odom.time_usec
        sim_time_s = sim_time_us / 1e6

        current_second = math.floor(sim_time_s)
        if last_logged_second is not None and current_second == last_logged_second:
            continue
        last_logged_second = current_second

        writer.writerow({
            'SimTime': round(sim_time_s, 1),
            'Lat': round(current_lat, 7) if current_lat else None,
            'Lon': round(current_lon, 7) if current_lon else None,
            'Alt': round(current_alt - inic_alt, 2) if current_alt else None,
            'qw': round(odom.q.w, 4),
            'qx': round(odom.q.x, 4),
            'qy': round(odom.q.y, 4),
            'qz': round(odom.q.z, 4),
            'Vx': round(odom.velocity_body.x_m_s, 2),
            'Vy': round(odom.velocity_body.y_m_s, 2),
            'Vz': round(odom.velocity_body.z_m_s, 2),
        })

        if current_lat is not None and current_lon is not None and current_alt is not None and inic_alt is not None:
            # Calculo de altitud relativa
            rel_alt_current = current_alt - inic_alt
            
            # Condicion 1: Cerca del objetivo final (logica original)
            # Nota: la tolerancia de 0.01 grados es amplia (~1km), se mantiene por compatibilidad si asi se desea, 
            # pero para aterrizaje preciso se requieren otras condiciones.
            near_goal = (
                abs(current_lat - last_lat) < 0.01 and
                abs(current_lon - last_lon) < 0.01 and
                abs(rel_alt_current - (last_alt if last_alt else 0)) < 0.5
            )

            # Condicion 2: Aterrizaje o Crash (Peticion usuario)
            # Si estamos por debajo de 1m (o bajo tierra) y la velocidad horizontal es nula.
            vx = odom.velocity_body.x_m_s
            vy = odom.velocity_body.y_m_s
            # Velocidad horizontal
            vh = math.sqrt(vx*vx + vy*vy)
            
            # Si altitud relativa < 1.0m (o negativa) Y estamos quietos
            landed_or_stopped = (rel_alt_current < 1.0) and (vh < 0.1)
            
            # Condicion 3: Fallo catastrafico hundido bajo tierra
            # Si descendemos mas alla de -5m, cortamos para no simular eternamente caida al vacio
            underground_cutoff = rel_alt_current < -5.0

            if near_goal or landed_or_stopped or underground_cutoff:
                if first_near_goal_time is None:
                    first_near_goal_time = sim_time_s
                elif (sim_time_s - first_near_goal_time) >= umbral_espera_s:
                    print(f"-- Fin detectado (Goal={near_goal}, Landed/Stopped={landed_or_stopped}, Underground={underground_cutoff})")
                    return
            else:
                first_near_goal_time = None

async def log_gps(drone):
    global current_lat, current_lon, current_alt
    async for gps_info in drone.telemetry.position():
        current_lat = gps_info.latitude_deg
        current_lon = gps_info.longitude_deg
        current_alt = gps_info.absolute_altitude_m

async def main():
    if len(sys.argv) < 4:
        print("Uso: python3 CargarEjecutarFailure.py <mission_name> <failure_unit> <failure_type>")
        sys.exit(1)
        
    mission_name = sys.argv[1]
    unit_str = sys.argv[2]
    f_type_str = sys.argv[3]
    
    await run(mission_name, unit_str, f_type_str)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        print("Script finalizado.")