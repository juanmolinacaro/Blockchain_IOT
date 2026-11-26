#!/usr/bin/env bash
# Guarda el token de GitHub (solo en este servidor) para subir los datos y prueba la subida.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Ejecuta con sudo"; exit 1; }
read -r -s -p "Pega el token de GitHub (no se verá) y pulsa Enter: " T; echo
[ -n "$T" ] || { echo "Vacío: no se guardó nada."; exit 1; }
umask 077; printf '%s' "$T" > /etc/escucha/github_token
echo "Token guardado. Probando la subida..."
bash /opt/escucha/nube/subir_datos.sh
