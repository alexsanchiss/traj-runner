# Usa Ubuntu 20.04 como base
FROM ubuntu:20.04

# Configura las variables de entorno necesarias
ENV DEBIAN_FRONTEND=noninteractive

# Actualiza e instala dependencias iniciales
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y \
    git \
    software-properties-common \
    python3-all \
    python3-pip \
    ca-certificates \
    gnupg \
    lsb-core \
    wget

# Clona el repositorio de PX4 y configura el PPA
RUN git clone https://github.com/PX4/PX4-Autopilot.git --recursive && \
    add-apt-repository ppa:kisak/kisak-mesa -y && \
    apt-get update && \
    apt-get upgrade -y

# Instala las dependencias de PX4
RUN bash ./PX4-Autopilot/Tools/setup/ubuntu.sh

# Clona el repositorio traj-runner e instala sus dependencias de Python
RUN git clone https://github.com/0xMastxr/traj-runner.git && \
    cd traj-runner && \
    pip3 install -r requirements.txt

# Copia el script de entrada al contenedor
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Define el directorio de trabajo
WORKDIR /traj-runner

# Usa el script de entrada
ENTRYPOINT ["/entrypoint.sh"]
