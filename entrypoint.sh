#!/bin/bash

# Actualiza el repositorio traj-runner
cd ../traj-runner
cat <<EOL > /.env
UAS_PLANNER_DB="158.42.167.190"
EOL
git pull origin master
pip3 install -r requirements.txt

# Ejecuta el script principal
python3 run.py
