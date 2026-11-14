"""Actualiza el programa desde GitHub antes de arrancar la escucha (lo llama `escuchar_hft.bat`).

Descarga la última versión de la rama y reemplaza solo el código (`copytrading/`, `windows/` y los
`requirements`). Nunca toca la carpeta `data/` (lo que la escucha ha ido guardando) ni el entorno
`.venv`. Si no hay internet o algo falla, sigue con la versión que ya hay.
"""
from __future__ import annotations

import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ZIP_URL = ("https://github.com/juanmolinacaro/Blockchain_IOT/archive/refs/heads/"
           "claude/onchain-replication-strategy-8naui6.zip")
UPDATABLE = ("copytrading/", "windows/", "requirements.txt", "requirements-escucha.txt")
SKIP = ("windows/escuchar_hft.bat",)        # el .bat está en uso mientras corre: no se reemplaza aquí


def apply_zip(data: bytes, root: Path) -> list[str]:
    """Copia del ZIP los archivos de código que cambiaron. Devuelve la lista de archivos actualizados."""
    changed = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        prefix = names[0].split("/")[0] + "/" if names else ""
        for name in names:
            rel = name[len(prefix):] if name.startswith(prefix) else name
            if not rel or rel.endswith("/") or rel in SKIP or "__pycache__" in rel:
                continue
            if not any(rel == u or (u.endswith("/") and rel.startswith(u)) for u in UPDATABLE):
                continue
            content = zf.read(name)
            dest = root / rel
            if dest.exists() and hashlib.sha256(dest.read_bytes()).digest() == hashlib.sha256(content).digest():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            changed.append(rel)
    return changed


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    try:
        with urllib.request.urlopen(ZIP_URL, timeout=60) as resp:
            data = resp.read()
        changed = apply_zip(data, root)
    except Exception as exc:
        print(f"No se pudo buscar actualizaciones ({exc}); sigo con la versión actual.")
        return 0
    if changed:
        print(f"Programa actualizado ({len(changed)} archivos nuevos o cambiados).")
    else:
        print("El programa ya estaba al día.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
