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
            
    try:
        await drone.param.set_param_int("SYS_FAILURE_EN", 1)
        print('Param SYS_FAILURE_EN = 1 set successfully')
    except Exception as e:
        print(f'fallo parametro: {e}')

    print('inyectando fallo BARO')
    try:
        await drone.failure.inject(FailureUnit.SENSOR_BARO, FailureType.OFF, 0)
        print('fallo BARO inyectado con exito')
    except Exception as e:
        print(f'fallo BARO explotó: {e}')

asyncio.run(main())
