#!/bin/bash

# Actualiza el repositorio traj-runner
cd /traj-runner
cat <<EOL > /.env
UAS_PLANNER_DB="postgresql://postgres.gkjjegbhetkybajfjcva:0D%5DI%3A%3B%3AQXxfi%2Fl%3Ac5%C2%A3x3%3ECRu4%3E@aws-0-eu-west-3.pooler.supabase.com:6543/postgres"
EOL
git pull origin master

# Ejecuta el script principal

