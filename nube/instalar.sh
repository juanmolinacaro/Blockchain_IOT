#!/usr/bin/env bash
# Instala la escucha 24/7 en un servidor Linux (Ubuntu/Debian; pensado para Oracle Cloud "Always Free").
# Uso (en el servidor):  curl -fsSL https://raw.githubusercontent.com/juanmolinacaro/Blockchain_IOT/claude/onchain-replication-strategy-8naui6/nube/instalar.sh | sudo bash
# Se puede volver a correr sin problema: no borra la carpeta data.
set -euo pipefail

BRANCH="claude/onchain-replication-strategy-8naui6"
ZIP="https://github.com/juanmolinacaro/Blockchain_IOT/archive/refs/heads/${BRANCH}.zip"
DIR=/opt/escucha
NTFY_TOPIC_DEFAULT="juan-ruta-d89ef32a94"

[ "$(id -u)" -eq 0 ] || { echo "Ejecuta con sudo"; exit 1; }

echo "== 1/6 Paquetes"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv git unzip curl ca-certificates >/dev/null
timedatectl set-timezone America/Bogota 2>/dev/null || true

echo "== 2/6 Memoria de reserva (para servidores de 1 GB)"
if [ ! -f /swapfile ] && [ "$(awk '/MemTotal/{print $2}' /proc/meminfo)" -lt 2000000 ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== 3/6 Programa"
id escucha >/dev/null 2>&1 || useradd --system --create-home --home-dir "$DIR" --shell /usr/sbin/nologin escucha
mkdir -p "$DIR" /etc/escucha
TMP=$(mktemp -d)
curl -fsSL "$ZIP" -o "$TMP/codigo.zip"
unzip -q "$TMP/codigo.zip" -d "$TMP"
SRC=$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -1)
for item in copytrading nube windows requirements.txt requirements-escucha.txt; do
  rm -rf "${DIR:?}/$item"; cp -r "$SRC/$item" "$DIR/"
done
mkdir -p "$DIR/data"
[ -f "$DIR/data/hft_cohorte.json" ] || cp "$SRC/data/hft_cohorte.json" "$DIR/data/" 2>/dev/null || true
rm -rf "$TMP"

echo "== 4/6 Python"
[ -x "$DIR/.venv/bin/python" ] || python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q --upgrade pip
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements-escucha.txt"
chown -R escucha:escucha "$DIR"

echo "== 5/6 Configuración"
if [ ! -f /etc/escucha/escucha.env ]; then
  echo "NTFY_TOPIC=${NTFY_TOPIC_DEFAULT}" > /etc/escucha/escucha.env
fi
chmod 640 /etc/escucha/escucha.env; chgrp escucha /etc/escucha/escucha.env

echo "== 6/6 Servicios"
cat > /etc/systemd/system/escucha.service <<UNIT
[Unit]
Description=Escucha 24/7 de BTC y ETH (Hyperliquid, Binance) con avisos ntfy
After=network-online.target
Wants=network-online.target

[Service]
User=escucha
WorkingDirectory=$DIR
EnvironmentFile=/etc/escucha/escucha.env
Environment=PYTHONUNBUFFERED=1
ExecStartPre=-$DIR/.venv/bin/python -m copytrading.actualizar
ExecStartPre=-$DIR/.venv/bin/pip install -q -r $DIR/requirements-escucha.txt
ExecStart=$DIR/.venv/bin/python -m copytrading.escucha
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
UNIT

# reinicio diario a las 5:00 (Colombia) para tomar la última versión del programa
cat > /etc/systemd/system/escucha-actualizar.service <<UNIT
[Unit]
Description=Reinicia la escucha para actualizar el programa
[Service]
Type=oneshot
ExecStart=/bin/systemctl restart escucha.service
UNIT
cat > /etc/systemd/system/escucha-actualizar.timer <<UNIT
[Unit]
Description=Actualiza la escucha cada día a las 5:00
[Timer]
OnCalendar=*-*-* 05:00:00 America/Bogota
Persistent=true
[Install]
WantedBy=timers.target
UNIT

# subida de los datos a GitHub cada 6 h (solo si hay token: sudo bash /opt/escucha/nube/poner_token.sh)
cat > /etc/systemd/system/escucha-datos.service <<UNIT
[Unit]
Description=Sube los datos de la escucha a GitHub (rama datos-escucha)
[Service]
Type=oneshot
ExecStart=/bin/bash $DIR/nube/subir_datos.sh
UNIT
cat > /etc/systemd/system/escucha-datos.timer <<UNIT
[Unit]
Description=Sube los datos cada 6 horas
[Timer]
OnCalendar=*-*-* 00,06,12,18:20:00 America/Bogota
Persistent=true
[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now escucha.service escucha-actualizar.timer escucha-datos.timer >/dev/null
sleep 5
systemctl --no-pager --lines=5 status escucha.service || true
echo
echo "Listo. La escucha corre 24/7 y se reinicia sola."
echo "Ver lo que hace:      sudo journalctl -u escucha -f"
echo "Subir datos a GitHub: sudo bash $DIR/nube/poner_token.sh   (una sola vez)"
