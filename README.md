# Traj-Runner v0.1.0

Traj-Runner es un conjunto de scripts en Python que interactúan con drones utilizando MAVSDK y PX4. Permite cargar misiones previamente definidas en formato JSON, con el formato de QGroundControl y ejecutar vuelos automáticos mientras se registran datos de telemetría como posición, velocidad, orientación y GPS.

## Características:
- Conexión con el dron utilizando MAVSDK.
- Carga y ejecución de misiones en formato QGroundControl (.plan).
- Registro de datos de vuelo en un archivo CSV para análisis posterior.
- Automatización del despegue y aterrizaje.
- Monitoreo continuo del estado del dron.

### Scripts principales:
- **CargarEjecutar.py**: Carga la misión, inicia el vuelo y guarda los datos de telemetría en un archivo CSV.
- **Allin.py**: Coordina la simulación con PX4 y ejecuta la misión con MAVSDK.

### Requisitos:
- MAVSDK-Python
- PX4 (Gazebo-Classic)
