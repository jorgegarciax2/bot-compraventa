"""Define la contraseña del panel.

    python web/clave.py

La contraseña se pide por teclado y no se guarda en ningún sitio: sólo se
almacena su hash PBKDF2 con sal, en panel.json, con permisos 600.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth                                                       # noqa: E402


def main() -> int:
    if auth.FICHERO.exists():
        print("Ya hay una contraseña en %s." % auth.FICHERO)
        if input("¿Sustituirla? [s/N] ").strip().lower() not in ("s", "si", "sí"):
            return 1
    print("\nLa contraseña no se muestra mientras la escribes.")
    clave = getpass.getpass("Contraseña nueva: ")
    if len(clave) < 8:
        print("Demasiado corta: mínimo 8 caracteres.", file=sys.stderr)
        return 1
    if clave != getpass.getpass("Repítela: "):
        print("No coinciden.", file=sys.stderr)
        return 1
    ruta = auth.guardar_clave(clave)
    print("\nGuardada en %s (permisos 600)." % ruta)
    print("Se guarda el hash, no la contraseña. Si la olvidas, vuelve a ejecutar esto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
