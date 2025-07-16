# Traj-Runner v0.5.0

Traj-Runner es un conjunto de scripts en Python que interactúan con drones utilizando MAVSDK y PX4. Es un programa diseñado para recibir trayectorias mediante una API y ejecutar planes en un dron conectado utilizando PX4 y MAVSDK-Python. Desde la versión 0.5.0, el sistema soporta ejecución con Docker, permitiendo lanzar procesos en paralelo de forma sencilla y aislada.

## Novedades v0.5.0
- **Soporte Docker:** Ahora puedes ejecutar todo el entorno en contenedores Docker, facilitando la gestión de dependencias y la ejecución de procesos paralelos.
- El resto de funcionalidades principales se mantienen igual que en versiones anteriores.

## Características Nuevas (anteriores):
- Registro de Telemetría Mejorado: Ahora se guardan datos adicionales de telemetría en el archivo CSV, incluyendo información detallada sobre la orientación y la velocidad en los ejes X, Y y Z.
- Análisis de Datos: Se ha implementado una función que permite extraer y graficar datos de vuelo en MATLAB, facilitando la visualización de la trayectoria y el comportamiento del dron.
- Conversión de Coordenadas: Nueva funcionalidad para transformar coordenadas de latitud y longitud en coordenadas X, Y respecto al punto HOME, mejorando la precisión en la representación de la trayectoria.
- Interfaz de Usuario Mejorada: Se han realizado ajustes en los mensajes de estado y los logs, proporcionando una mejor comprensión del estado del dron durante las misiones.

## Características:
- Conexión con el dron utilizando MAVSDK.
- Carga y ejecución de misiones en formato QGroundControl (.plan).
- Registro de datos de vuelo en un archivo CSV para análisis posterior.
- Automatización del despegue y aterrizaje.
- Monitoreo continuo del estado del dron.
- **Ejecución en Docker para procesos paralelos.**

### Scripts principales:
- **CargarEjecutar.py**: Carga la misión, inicia el vuelo y guarda los datos de telemetría en un archivo CSV.
- **Allin.py**: Coordina la simulación con PX4 y ejecuta la misión con MAVSDK.

## Uso
- El programa espera recibir un POST en el endpoint configurado. Una vez que recibe la solicitud, ejecutará el plan correspondiente y responderá con la trayectoria.
- El formato del JSON adjunto al POST debe ser un archivo .plan generado con QGroundControl. Hay algunos ejemplos en la carpeta Planes_Backup

### Requisitos:
- PX4 (Gazebo-Classic)
- MAVSDK-Python
- **Docker** (opcional, recomendado para ejecución paralela y entorno controlado)
