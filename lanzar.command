#!/bin/bash
# Arranca el panel web de tbot. Doble clic en el Finder, o ./lanzar.command
# Crea el entorno virtual e instala las dependencias la primera vez.
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  echo "No encuentro ningún Python 3. Instálalo desde https://www.python.org/downloads/"
  read -r -p "Pulsa Intro para cerrar." _; exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Primera ejecución: creando entorno virtual con $PY…"
  "$PY" -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
fi

# Dependencias de tbot (no se instala el paquete: el servidor añade tbot/src al path,
# así funciona también con Python 3.9, que es lo que trae este Mac).
if ! ./.venv/bin/python -c "import pandas, duckdb, pyarrow, yaml, ccxt" >/dev/null 2>&1; then
  echo "Instalando dependencias (sólo la primera vez)…"
  ./.venv/bin/python -m pip install \
    "pandas>=2.2" "numpy>=1.26" "pyarrow>=16" "duckdb>=1.1" \
    "pyyaml>=6.0" "pytz>=2024.1" "requests>=2.32" "ccxt>=4.5"
fi

exec ./.venv/bin/python web/servidor.py "$@"
