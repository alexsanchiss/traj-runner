# Usa Ubuntu 22.04 como base
FROM ubuntu:22.04

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
    wget \
    procps \
    sudo

# Clona el repositorio de PX4 y configura el PPA
RUN git clone https://github.com/PX4/PX4-Autopilot.git --recursive && \
    add-apt-repository ppa:kisak/kisak-mesa -y && \
    apt-get update && \
    apt-get upgrade -y

# Instala las dependencias de PX4
RUN bash ./PX4-Autopilot/Tools/setup/ubuntu.sh

RUN cd PX4-Autopilot && \
    (make px4_sitl gz_x500 | tee build.log & \
    px4_pid=$!; \
    while sleep 1; do \
        if grep -q "Startup script returned successfully" build.log; then \
            echo "PX4 SITL está listo. Deteniendo el proceso."; \
            kill -9 $px4_pid; \
            break; \
        fi; \
    done)

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
