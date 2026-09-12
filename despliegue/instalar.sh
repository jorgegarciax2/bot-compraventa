#!/usr/bin/env bash
# Instala el panel en un Ubuntu recién creado (Oracle Cloud Always Free).
#
#   sudo bash despliegue/instalar.sh                        # dominio automático
#   sudo bash despliegue/instalar.sh mi-dominio.ejemplo.com # o el tuyo
#
# Es idempotente: puedes volver a ejecutarlo para actualizar.
set -euo pipefail

DOMINIO="${1:-}"
DESTINO=/opt/bot
USUARIO=bot
ORIGEN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then echo "Ejecútame con sudo." >&2; exit 1; fi

# Sin dominio propio se usa sslip.io, que resuelve 88-12-34-56.sslip.io a esa IP
# sin registrarse en ningún sitio. Let's Encrypt emite certificado contra él por
# desafío HTTP-01, así que el HTTPS sale igual de bien y sin una cuenta más.
if [ -z "$DOMINIO" ]; then
  IP_PUBLICA=""
  for servicio in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
    IP_PUBLICA="$(curl -4 -s --max-time 8 "$servicio" | tr -d '[:space:]')" || true
    [[ "$IP_PUBLICA" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] && break
    IP_PUBLICA=""
  done
  if [ -z "$IP_PUBLICA" ]; then
    echo "No he podido averiguar la IP pública. Pásame un dominio:" >&2
    echo "  sudo bash despliegue/instalar.sh mi-dominio.ejemplo.com" >&2
    exit 1
  fi
  DOMINIO="${IP_PUBLICA//./-}.sslip.io"
  echo "==> Sin dominio propio: usaré $DOMINIO"
fi

echo "==> Paquetes del sistema"
export DEBIAN_FRONTEND=noninteractive
# iptables-persistent pregunta si guardar las reglas actuales y colgaría el script.
echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip rsync ca-certificates curl \
                      debian-keyring debian-archive-keyring apt-transport-https \
                      iptables-persistent

echo "==> Caddy (para el HTTPS automático)"
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq caddy
fi

echo "==> Usuario de servicio y archivos"
id -u "$USUARIO" >/dev/null 2>&1 || useradd --system --home "$DESTINO" --shell /usr/sbin/nologin "$USUARIO"
mkdir -p "$DESTINO"
# Se copia el código, nunca el estado ni el entorno: los agentes que ya estén
# operando en el servidor no se tocan.
rsync -a --delete \
  --exclude '.venv/' --exclude 'ejecuciones/' --exclude 'tbot/data/' \
  --exclude 'panel.json' --exclude '__pycache__/' --exclude '.DS_Store' \
  "$ORIGEN"/ "$DESTINO"/
mkdir -p "$DESTINO/ejecuciones" "$DESTINO/tbot/data"
chown -R "$USUARIO:$USUARIO" "$DESTINO"

echo "==> Memoria de intercambio (la máquina gratis tiene 1 GB)"
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap -q /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Entorno de Python"
if [ ! -x "$DESTINO/.venv/bin/python" ]; then
  sudo -u "$USUARIO" python3 -m venv "$DESTINO/.venv"
fi
sudo -u "$USUARIO" "$DESTINO/.venv/bin/python" -m pip install --quiet --upgrade pip
sudo -u "$USUARIO" "$DESTINO/.venv/bin/python" -m pip install --quiet \
  "pandas>=2.2" "numpy>=1.26" "pyarrow>=16" "duckdb>=1.1" \
  "pyyaml>=6.0" "pytz>=2024.1" "requests>=2.32" "ccxt>=4.5"

echo "==> Cortafuegos (Oracle bloquea todo menos SSH por defecto)"
for puerto in 80 443; do
  iptables -C INPUT -p tcp --dport "$puerto" -j ACCEPT 2>/dev/null \
    || iptables -I INPUT 1 -p tcp --dport "$puerto" -j ACCEPT
done
netfilter-persistent save >/dev/null
echo "    OJO: falta abrir 80 y 443 también en la consola de Oracle"
echo "    (Red virtual en la nube -> Lista de seguridad -> Reglas de entrada)."

echo "==> Caddy"
install -d -m 755 /var/log/caddy
chown caddy:caddy /var/log/caddy
sed "s/TU-DOMINIO.duckdns.org/$DOMINIO/" "$DESTINO/despliegue/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload-or-restart caddy

echo "==> Servicio del panel"
cp "$DESTINO/despliegue/bot-panel.service" /etc/systemd/system/bot-panel.service
systemctl daemon-reload
systemctl enable bot-panel >/dev/null

if [ ! -f "$DESTINO/panel.json" ]; then
  echo
  echo "==================================================================="
  echo " Falta la contraseña del panel. Sin ella el servicio no arrancará."
  echo
  echo "   sudo -u $USUARIO $DESTINO/.venv/bin/python $DESTINO/web/clave.py"
  echo "   sudo systemctl start bot-panel"
  echo
  echo " Luego entra en:  https://$DOMINIO"
  echo "==================================================================="
else
  systemctl restart bot-panel
  sleep 2
  systemctl --no-pager --lines=5 status bot-panel || true
  echo
  echo "Listo. Entra en https://$DOMINIO"
fi
