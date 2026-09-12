#!/usr/bin/env bash
# Sube el código al servidor desde este portátil y reinstala.
#
#   ./despliegue/subir.sh ubuntu@123.45.67.89
#
# No sube el entorno de Python, ni el estado de los agentes, ni la contraseña:
# lo que ya esté operando en el servidor sigue como está.
set -euo pipefail

SERVIDOR="${1:-}"
DOMINIO="${2:-}"        # opcional: sin él se usa sslip.io sobre la IP pública
if [ -z "$SERVIDOR" ]; then
  echo "Uso: ./despliegue/subir.sh usuario@ip [mi-dominio.ejemplo.com]" >&2
  exit 1
fi
cd "$(dirname "$0")/.."

echo "==> Subiendo el código a $SERVIDOR"
rsync -az --delete --info=stats1 \
  --exclude '.venv/' --exclude 'ejecuciones/' --exclude 'tbot/data/' \
  --exclude 'panel.json' --exclude '__pycache__/' --exclude '.DS_Store' \
  ./ "$SERVIDOR:/tmp/bot-subida/"

echo "==> Instalando"
ssh -t "$SERVIDOR" "sudo bash /tmp/bot-subida/despliegue/instalar.sh '$DOMINIO'"
