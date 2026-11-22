#!/usr/bin/env bash
# Script de construcción que ejecuta Render en cada despliegue.
set -o errexit   # si algún comando falla, se corta el deploy

pip install -r requirements.txt          # 1. instala las dependencias de producción
python manage.py collectstatic --no-input  # 2. junta los CSS/JS en staticfiles/ (WhiteNoise los sirve)
python manage.py migrate                 # 3. aplica migraciones pendientes en PostgreSQL