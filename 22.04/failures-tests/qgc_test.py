import asyncio
from mavsdk import System
import sys

async def main():
    drone = System()
    await drone.connect(system_address='udp://:14540')
    print('esperando conect')
    async for state in drone.core.connection_state():
        if state.is_connected:
            print('-- Conectado al dron!')
            break
            
    print('inyectando fallo GPS (comando genérico MAV_CMD_DO_SET_MODE - 176 - solo para testear timeout)')
    try:
        # custom params to check timeout (sending random command: MAV_CMD_DO_SET_MODE=176 mode=1 custom_mode=4)
        cmd = await drone.core.send_command(sys.maxsize, 176, 1, 4, 0, 0, 0, 0, 0)
        print(f'Comando enviado con exito: {cmd}')
    except Exception as e:
         print(f'Error en el comando: {e}')

asyncio.run(main())
