import asyncio
from mavsdk import System
async def main():
    drone = System()
    await drone.connect(system_address='udp://:14540')
    print('esperando conect')
    async for state in drone.core.connection_state():
        if state.is_connected:
            print('-- Conectado al dron!')
            break
    print('enviando shell')
    try:
        await drone.shell.send('failure mag off\n')
        print('comando fallos shell enviado correctamente')
    except Exception as e:
        print(f'falló mandando shell: {e}')

asyncio.run(main())
