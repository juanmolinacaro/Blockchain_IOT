#!/usr/bin/env bash
# Copia data/ de la escucha a la rama "datos-escucha" del repositorio y la sube a GitHub (cada 6 h).
# Necesita el token guardado con poner_token.sh. Sin token, no hace nada.
set -euo pipefail
DIR="${DIR:-/opt/escucha}"
TOKEN_FILE="${TOKEN_FILE:-/etc/escucha/github_token}"
REPO="${REPO:-https://github.com/juanmolinacaro/Blockchain_IOT.git}"
BR=datos-escucha
WORK="${WORK:-/var/lib/escucha-datos}"
[ -s "$TOKEN_FILE" ] || { echo "Sin token: no se suben datos."; exit 0; }
AUTH="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$(cat "$TOKEN_FILE")" | base64 -w0)"
g() { git -c "http.https://github.com/.extraheader=$AUTH" -C "$WORK" "$@"; }
if [ ! -d "$WORK/.git" ]; then
  mkdir -p "$WORK"
  git -C "$WORK" init -q
  git -C "$WORK" remote add origin "$REPO"
  if g fetch -q --depth 1 origin "$BR" 2>/dev/null; then
    git -C "$WORK" checkout -q -b "$BR" FETCH_HEAD
  else
    git -C "$WORK" checkout -q --orphan "$BR"
  fi
fi
git -C "$WORK" config user.name "escucha-nube"
git -C "$WORK" config user.email "escucha-nube@users.noreply.github.com"
mkdir -p "$WORK/data"
# copia segura: solo lo que la escucha guarda
for f in "$DIR"/data/*.csv "$DIR"/data/*.jsonl "$DIR"/data/*.json "$DIR"/data/*.txt; do
  [ -f "$f" ] && cp -f "$f" "$WORK/data/"
done
git -C "$WORK" add -A data
if git -C "$WORK" diff --cached --quiet; then echo "Sin cambios."; exit 0; fi
git -C "$WORK" commit -q -m "Datos de la escucha $(date '+%Y-%m-%d %H:%M')"
for i in 1 2 3 4; do
  g push -q origin "HEAD:$BR" && { echo "Datos subidos."; exit 0; }
  sleep $((i * 15))
done
echo "No se pudo subir (se reintenta en 6 h)."; exit 1
