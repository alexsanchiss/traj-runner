import asyncio
from mavsdk import System
from mavsdk.failure import FailureUnit, FailureType

async def main():
    drone = System()
    await drone.connect(system_address='udp://:14540')
    print('esperando conect')
    async for state in drone.core.connection_state():
        if state.is_connected:
            print('-- Conectado al dron!')
            break
            
    print('inyectando fallo GPS')
    try:
        await drone.failure.inject(getattr(FailureUnit, 'SENSOR_GPS'), getattr(FailureType, 'OFF'), 0)
        print('fallo inyectado con exito')
    except Exception as e:
        print(f'fallo explotó: {e}')

asyncio.run(main())
