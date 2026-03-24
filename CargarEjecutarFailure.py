#!/usr/bin/env python3

import asyncio
import csv
import json
import math
import time
import sys
import os

try:
    from mavsdk import System
except ImportError:
    print("MAVSDK not found. Please install it.")
    sys.exit(1)

global current_lat, current_lon, current_alt, last_lat, last_lon, last_alt, inic_alt
current_lat = None
current_lon = None
current_alt = None
last_lat = None
last_lon = None
last_alt = None
inic_alt = None

current_dir = os.path.dirname(os.path.abspath(__file__))

async def attempt_takeoff(drone):
    max_attempts = 5
    attempt = 0
    while attempt < max_attempts:
        try:
            print(f"-- Intento {attempt + 1} de armar y despegar el dron")
            await drone.action.arm()
            await drone.mission_raw.start_mission()

            start_time = time.time()
            await asyncio.sleep(2)
            
            async for in_air in drone.telemetry.in_air():
                if in_air:
                    print("-- El dron ha despegado!")
                    return
                elif time.time() - start_time > 10: 
                    print("-- El dron no parece haber despegado. Reintentando...")
                    break
        except Exception as e:
            print(f"Error en intento de despegue: {e}")

        attempt += 1
        await asyncio.sleep(2)

    raise RuntimeError("No se pudo armar y despegar el dron después de varios intentos.")

async def inject_failure_on_cruise(drone, unit_str, f_type_str):
    """Espera a que el dron esté en el aire, da un margen para el crucero e inyecta el fallo."""
    print("-- Esperando a que el dron esté en el aire para inyectar fallo...")
    async for in_air in drone.telemetry.in_air():
        if in_air:
            break
            
    # Tiempo de espera para que el dron alcance la altitud de crucero hacia el primer WP
    await asyncio.sleep(8)
    
    print(f"-- Inyectando fallo (vía MAVLink Shell / NSH): {unit_str} - {f_type_str}")
    try:
        # Formateo del comando de consola: "failure <unit> <type>[-i <instance>]"
        unit_shell = unit_str.replace("SENSOR_", "").replace("SYSTEM_", "").lower()
        type_shell = f_type_str.lower()
        
        # Mapeo de casos especiales si los nombres de shell no son directos
        if unit_shell == "accel": unit_shell = "accel"
        elif unit_shell == "gyro": unit_shell = "gyro"
        elif unit_shell == "mag": unit_shell = "mag"
        elif unit_shell == "baro": unit_shell = "baro"
        elif unit_shell == "airspeed": unit_shell = "airspeed"
        elif unit_shell == "vio": unit_shell = "vio"
        
        shell_cmd = f"failure {unit_shell} {type_shell}"
        print(f"   => Ejecutando comando NSH: {shell_cmd}")
        
        await drone.shell.send(shell_cmd + '\n')
        
        await asyncio.sleep(1)
        print("-- Fallo inyectado correctamente vía Shell")
    except Exception as e:
        print(f"Error crítico enviando comando por Shell: {e}")

async def log_odometry(drone, writer):
    global current_lat, current_lon, current_alt, last_lat, last_lon, last_alt, inic_alt
    first_near_goal_time = None
    last_logged_second = None
    print("-- Grabando datos de los sensores")

    umbral_espera_s = 20.0

    async for odom in drone.telemetry.odometry():
        sim_time_us = odom.time_usec
        sim_time_s = sim_time_us / 1e6

        current_second = math.floor(sim_time_s)
        # Loguear solo si hemos cambiado de segundo entero (aprox 1Hz)
        if last_logged_second is not None and current_second == last_logged_second:
            continue
        last_logged_second = current_second

        writer.writerow({
            'SimTime': round(sim_time_s, 1),
            'Lat': round(current_lat, 7) if current_lat else None,
            'Lon': round(current_lon, 7) if current_lon else None,
            'Alt': round(current_alt - inic_alt, 2) if current_alt and inic_alt else None,
            'qw': round(odom.q.w, 4),
            'qx': round(odom.q.x, 4),
            'qy': round(odom.q.y, 4),
            'qz': round(odom.q.z, 4),
            'Vx': round(odom.velocity_body.x_m_s, 2),
            'Vy': round(odom.velocity_body.y_m_s, 2),
            'Vz': round(odom.velocity_body.z_m_s, 2),
        })

        if current_lat is not None and current_lon is not None and current_alt is not None and inic_alt is not None and last_lat is not None:
            near_goal = (
                abs(current_lat - last_lat) < 0.0001 and
                abs(current_lon - last_lon) < 0.0001 and
                abs((current_alt - inic_alt) - (last_alt if last_alt else 0)) < 2.0 
            )
            
            if near_goal:
                if first_near_goal_time is None:
                    first_near_goal_time = sim_time_s
                elif (sim_time_s - first_near_goal_time) >= umbral_espera_s:
                    print("-- El plan de vuelo o fallo ha terminado por inactividad física aparente.")
                    return
            else:
                first_near_goal_time = None

async def log_gps(drone):
    global current_lat, current_lon, current_alt
    async for gps_info in drone.telemetry.position():
        current_lat = gps_info.latitude_deg
        current_lon = gps_info.longitude_deg
        current_alt = gps_info.absolute_altitude_m

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

        try:
            await drone.param.set_param_int("SYS_FAILURE_EN", 1)
        except:
            pass 

        mission_path = f"{current_dir}/Planes/{mission_name}.plan"
        print(f"Leyendo misión: {mission_path}")
        with open(mission_path, 'r') as f:
            mission_json = json.load(f)

        mission_items = mission_json["mission"]["items"]
        planned_home_position = mission_json["mission"].get("plannedHomePosition", None)

        if planned_home_position:
            inic_alt = planned_home_position[2]
            
        if mission_items:
            last_wp = mission_items[-1] 
            if last_wp["command"] == 20: 
                if planned_home_position:
                    last_lat = planned_home_position[0]
                    last_lon = planned_home_position[1]
                    last_alt = 0 
                else:
                    last_lat = last_wp["params"][4]
                    last_lon = last_wp["params"][5]
                    last_alt = last_wp["params"][6]
            else:
                last_lat = last_wp["params"][4]
                last_lon = last_wp["params"][5]
                last_alt = last_wp["params"][6]
        
        print("Importando misión al dron...")
        mission = await drone.mission_raw.import_qgroundcontrol_mission(mission_path)
        await drone.mission_raw.upload_mission(mission.mission_items)

        if hasattr(mission, 'rally_items') and len(mission.rally_items) > 0:
            await drone.mission_raw.upload_rally_points(mission.rally_items)

        print("Esperando la estimación de posición global...")
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                print("-- Estimación de posición global OK")
                break

        await attempt_takeoff(drone)

        trayectorias_dir = f"{current_dir}/Trayectorias"
        os.makedirs(trayectorias_dir, exist_ok=True)
        
        csv_filename = f"{trayectorias_dir}/{mission_name}_{unit_str}_{f_type_str}_log.csv"
        
        print(f"Iniciando log en: {csv_filename}")
        with open(csv_filename, mode='w', newline='') as csv_file:
            fieldnames = ['SimTime', 'Lat', 'Lon', 'Alt', 'qw', 'qx', 'qy', 'qz', 'Vx', 'Vy', 'Vz']
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            inject_task = asyncio.create_task(inject_failure_on_cruise(drone, unit_str, f_type_str))
            gps_task = asyncio.create_task(log_gps(drone))
            odom_task = asyncio.create_task(log_odometry(drone, writer))
            
            done, pending = await asyncio.wait([odom_task], return_when=asyncio.FIRST_COMPLETED)

            print("-- Finalizando tareas...")
            if not inject_task.done():
                inject_task.cancel()
            if not gps_task.done():
                gps_task.cancel()
            
            try:
                await inject_task
            except asyncio.CancelledError:
                pass
            try:
                await gps_task
            except asyncio.CancelledError:
                pass

    except asyncio.CancelledError:
        print("Todas las tareas han sido canceladas.")
    except Exception as e:
        print(f"Error en run: {e}")

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
    except KeyboardInterrupt:
        pass
