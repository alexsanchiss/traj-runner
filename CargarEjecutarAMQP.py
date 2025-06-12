#!/usr/bin/env python3

import asyncio
import csv
import json
import time
import sys
import os
import math

from mavsdk import System
import aio_pika

# --- Globals for telemetry snapshot ---
current_lat = current_lon = current_alt = None
current_qx = current_qy = current_qz = current_qw = None
current_vx = current_vy = current_vz = None
current_sim_time = None
current_in_air = False

# For landing detection
prev_lat = prev_lon = None

# Last waypoint info (from plan)
last_lat = last_lon = last_alt = inic_alt = None

# Path helpers
current_dir = os.path.dirname(os.path.abspath(__file__))


# --- Quaternion → Euler (roll, pitch, yaw) ---
def quaternion_to_euler(qx, qy, qz, qw):
    # roll (x-axis)
    sinr_cosp = 2 * (qw * qx + qy * qz)
    cosr_cosp = 1 - 2 * (qx * qx + qy * qy)
    roll = math.atan2(sinr_cosp, cosr_cosp)
    # pitch (y-axis)
    sinp = 2 * (qw * qy - qz * qx)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2, sinp)
    else:
        pitch = math.asin(sinp)
    # yaw (z-axis)
    siny_cosp = 2 * (qw * qz + qx * qy)
    cosy_cosp = 1 - 2 * (qy * qy + qz * qz)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return roll, pitch, yaw


# --- Bearing between two GPS points (radians) ---
def calculate_track_angle(lat1, lon1, lat2, lon2):
    # all in radians
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.atan2(x, y)


# --- Subscribe to GPS updates ---
async def subscribe_gps(drone):
    global current_lat, current_lon, current_alt
    async for pos in drone.telemetry.position():
        current_lat = pos.latitude_deg
        current_lon = pos.longitude_deg
        current_alt = pos.absolute_altitude_m


# --- Subscribe to odometry updates ---
async def subscribe_odometry(drone):
    global current_qx, current_qy, current_qz, current_qw
    global current_vx, current_vy, current_vz, current_sim_time
    async for odom in drone.telemetry.odometry():
        current_qx = odom.q.x
        current_qy = odom.q.y
        current_qz = odom.q.z
        current_qw = odom.q.w
        current_vx = odom.velocity_body.x_m_s
        current_vy = odom.velocity_body.y_m_s
        current_vz = odom.velocity_body.z_m_s
        current_sim_time = odom.time_usec / 1e6


# --- Subscribe to in_air status ---
async def subscribe_in_air(drone):
    global current_in_air
    async for flying in drone.telemetry.in_air():
        current_in_air = flying


# --- Periodic logger & AMQP publisher ---
async def periodic_log_and_publish(writer, channel, queue_name):
    global prev_lat, prev_lon

    last_logged_sec = None

    while True:
        # Wait until we have a sim time and have taken off
        if current_sim_time is None or not current_in_air:
            await asyncio.sleep(0.1)
            continue

        sec = int(current_sim_time)
        if sec == last_logged_sec:
            await asyncio.sleep(0.1)
            continue
        last_logged_sec = sec

        # Snapshot
        lat = current_lat
        lon = current_lon
        alt = current_alt
        qx, qy, qz, qw = current_qx, current_qy, current_qz, current_qw
        vx, vy, vz = current_vx, current_vy, current_vz

        # CSV write (keep SimTime and raw odom fields)
        writer.writerow({
            'SimTime': round(current_sim_time, 1),
            'Lat': lat,
            'Lon': lon,
            'Alt': round(alt, 3) if alt is not None else None,
            'qw': round(qw, 0) if qw is not None else None,
            'qx': round(qx, 0) if qx is not None else None,
            'qy': round(qy, 0) if qy is not None else None,
            'qz': round(qz, 0) if qz is not None else None,
            'Vx': round(vx, 3) if vx is not None else None,
            'Vy': round(vy, 3) if vy is not None else None,
            'Vz': round(vz, 3) if vz is not None else None,
        })

        # Compute euler
        roll, pitch, yaw = quaternion_to_euler(qx, qy, qz, qw)

        # Ground speed and track angle
        GS = math.sqrt(vx**2 + vy**2)
        if prev_lat is not None and prev_lon is not None:
            # convert to radians
            track_angle = calculate_track_angle(
                math.radians(prev_lat), math.radians(prev_lon),
                math.radians(lat),   math.radians(lon)
            )
        else:
            track_angle = 0.0
        prev_lat, prev_lon = lat, lon

        # Timestamps
        now_s = time.time()
        now_ms = int(now_s * 1000)
        time_str = f"{now_s:.6f}"

        # Build JSON
        payload = {
            "time_ms": now_ms,
            "time": time_str,
            "message": {
                "position": {
                    "altitude": alt,
                    "longitude": lon,
                    "latitude": lat
                },
                "attitude": {
                    "pitch": pitch,
                    "yaw": yaw,
                    "roll": roll
                },
                "speed": {
                    "GS": GS,
                    "track_angle": track_angle,
                    "vert_speed": vz
                },
                "battery": 50,
                "pilot_alerts": [],
                "time": now_s
            }
        }

        # Publish to AMQP
        msg_body = json.dumps(payload).encode()
        await channel.default_exchange.publish(
            aio_pika.Message(body=msg_body),
            routing_key=queue_name
        )

        # Terminate when drone lands
        if not current_in_air:
            print("-- El dron ha aterrizado, cerrando logger.")
            return


# --- Main mission runner ---
async def run(mission_name):
    global last_lat, last_lon, last_alt, inic_alt

    # Conectar al dron
    drone = System()
    await drone.connect(system_address="udp://:14540")
    print("Esperando a que el dron se conecte...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("-- Conectado al dron!")
            break

    # Leer plan
    mission_path = f"{current_dir}/Planes/{mission_name}.plan"
    with open(mission_path, 'r') as f:
        mission_json = json.load(f)

    items = mission_json["mission"]["items"]
    home = mission_json["mission"].get("plannedHomePosition", None)
    if items:
        wp = items[-1]
        if wp["command"] == 20 and home:
            last_lat, last_lon, last_alt = home
            inic_alt = 0
        else:
            last_lat = wp["params"][4]
            last_lon = wp["params"][5]
            last_alt = wp["params"][6]
            inic_alt = home[2] if home else 0

    # Cargar misión
    mission = await drone.mission_raw.import_qgroundcontrol_mission(mission_path)
    await drone.mission_raw.upload_mission(mission.mission_items)
    if mission.rally_items:
        await drone.mission_raw.upload_rally_points(mission.rally_items)
    print(f"Misión {mission_name} cargada.")

    # Esperar GPS OK
    print("Esperando estimación de posición global...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("-- Posición global OK")
            break

    # Despegue
    await attempt_takeoff(drone)

    # Preparar archivo CSV
    tray_dir = f"{current_dir}/Trayectorias"
    os.makedirs(tray_dir, exist_ok=True)
    csv_file = open(f"{tray_dir}/{mission_name}_log.csv", "w", newline='')
    fieldnames = ['SimTime','Lat','Lon','Alt','qw','qx','qy','qz','Vx','Vy','Vz']
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()

    # Conectar a AMQP
    host = "shark-01.rmq.cloudamqp.com"
    user = "lplqkeqs"
    password = "2D81FzcEA4XrJEHThfwaREmVrxZeklJ0"
    vhost = "lplqkeqs"
    amqp_url = f"amqps://{user}:{password}@{host}/{vhost}"
    connection = await aio_pika.connect_robust(amqp_url)
    channel = await connection.channel()
    queue_name = mission_name
    await channel.declare_queue(queue_name, durable=True)

    # Lanzar tareas
    tasks = [
        asyncio.create_task(subscribe_gps(drone)),
        asyncio.create_task(subscribe_odometry(drone)),
        asyncio.create_task(subscribe_in_air(drone)),
        asyncio.create_task(periodic_log_and_publish(writer, channel, queue_name))
    ]

    # Esperar al fin del periodic logger
    await tasks[-1]
    for t in tasks[:-1]:
        t.cancel()

    await connection.close()
    csv_file.close()


async def attempt_takeoff(drone):
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"-- Intento {attempt} de armar y despegar")
            await drone.action.arm()
            await drone.mission_raw.start_mission()
            # Esperar a que suba
            start = time.time()
            async for in_air in drone.telemetry.in_air():
                if in_air:
                    print("-- Despegado!")
                    return
                if time.time() - start > 1:
                    print("-- No en aire aún, reintentando...")
                    break
        except Exception as e:
            print(f"Error en despegue: {e}")
        await asyncio.sleep(1)
    raise RuntimeError("Fallo al armar y despegar después de varios intentos.")


async def main():
    mission_name = sys.argv[1]
    await run(mission_name)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        print("Script terminado.")
