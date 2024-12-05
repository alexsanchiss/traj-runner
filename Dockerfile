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

# Instala las dependencias generales de PX4
RUN apt-get install -y --no-install-recommends \
    astyle \
    build-essential \
    cmake \
    cppcheck \
    file \
    g++ \
    gcc \
    gdb \
    git \
    lcov \
    libfuse2 \
    libxml2-dev \
    libxml2-utils \
    make \
    ninja-build \
    python3 \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    rsync \
    shellcheck \
    unzip \
    zip

# Instala las dependencias de Python
RUN wget https://raw.githubusercontent.com/PX4/PX4-Autopilot/master/Tools/setup/requirements.txt -O /requirements.txt && \
    python3 -m pip install --user -r /requirements.txt

# Instalación del toolchain de NuttX (si es necesario)
RUN apt-get install -y --no-install-recommends \
    automake \
    binutils-dev \
    bison \
    flex \
    g++-multilib \
    gcc-multilib \
    gdb-multiarch \
    genromfs \
    gettext \
    gperf \
    libelf-dev \
    libexpat-dev \
    libgmp-dev \
    libisl-dev \
    libmpc-dev \
    libmpfr-dev \
    libncurses5 \
    libncurses5-dev \
    libncursesw5-dev \
    libtool \
    pkg-config \
    screen \
    texinfo \
    u-boot-tools \
    util-linux \
    vim-common \
    kconfig-frontends

# Instala las dependencias de simulación de PX4
RUN apt-get install -y --no-install-recommends \
    bc \
    ant \
    openjdk-11-jre \
    openjdk-11-jdk \
    libvecmath-java \
    libeigen3-dev \
    libgstreamer-plugins-base1.0-dev \
    libimage-exiftool-perl \
    libopencv-dev \
    pkg-config \
    protobuf-compiler

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
