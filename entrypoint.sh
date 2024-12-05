#!/bin/bash

# Actualiza el repositorio traj-runner
cd /traj-runner
git pull origin master

# Ejecuta el script principal
python3 run.py
