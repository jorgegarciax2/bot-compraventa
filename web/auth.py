"""Autenticación del panel: una contraseña, sesiones firmadas, nada más.

Decisiones deliberadas:

* La contraseña **nunca** se guarda: sólo su hash PBKDF2 con sal aleatoria.
* La sesión es una cookie firmada con HMAC. No hay estado en el servidor, así que
  reiniciar el panel no te echa fuera.
* En local (127.0.0.1) sin `panel.json` el panel funciona sin contraseña, como
  siempre. En cuanto escucha en una dirección pública, exige contraseña o se
  niega a arrancar: es el error que más caro sale olvidar.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

RAIZ = Path(__file__).resolve().parent.parent
FICHERO = RAIZ / "panel.json"

ITERACIONES = 400_000
DURACION_SESION = 30 * 86400          # 30 días
MAX_INTENTOS = 8                      # por IP, antes de bloquear
BLOQUEO = 900                         # 15 minutos


# ------------------------------------------------------------------ fichero
def hashear(clave: str, sal: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, ITERACIONES)


def guardar_clave(clave: str) -> Path:
    """Escribe el hash de la contraseña y un secreto nuevo para firmar sesiones."""
    if len(clave) < 8:
        raise ValueError("la contraseña debe tener al menos 8 caracteres")
    sal = secrets.token_bytes(16)
    datos = {
        "algoritmo": "pbkdf2_sha256",
        "iteraciones": ITERACIONES,
        "sal": sal.hex(),
        "hash": hashear(clave, sal).hex(),
        "secreto": secrets.token_hex(32),
        "creada": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    FICHERO.write_text(json.dumps(datos, indent=2), encoding="utf-8")
    os.chmod(FICHERO, 0o600)           # que no la lea otro usuario de la máquina
    return FICHERO


def cargar() -> Optional[dict]:
    if not FICHERO.exists():
        return None
    try:
        d = json.loads(FICHERO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return d if {"sal", "hash", "secreto"} <= set(d) else None


def comprobar(clave: str, cfg: dict) -> bool:
    try:
        sal = binascii.unhexlify(cfg["sal"])
        esperado = binascii.unhexlify(cfg["hash"])
    except (binascii.Error, KeyError):
        return False
    calculado = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal,
                                    int(cfg.get("iteraciones", ITERACIONES)))
    return hmac.compare_digest(calculado, esperado)


# ------------------------------------------------------------------ sesiones
def _firma(secreto: str, mensaje: bytes) -> bytes:
    return hmac.new(secreto.encode("utf-8"), mensaje, hashlib.sha256).digest()


def crear_sesion(cfg: dict) -> str:
    caduca = str(int(time.time()) + DURACION_SESION).encode("ascii")
    firma = _firma(cfg["secreto"], caduca)
    return "%s.%s" % (base64.urlsafe_b64encode(caduca).decode().rstrip("="),
                      base64.urlsafe_b64encode(firma).decode().rstrip("="))


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sesion_valida(cookie: str, cfg: dict) -> bool:
    if not cookie or "." not in cookie:
        return False
    trozo, firma = cookie.rsplit(".", 1)
    try:
        caduca_b = _b64d(trozo)
        recibida = _b64d(firma)
    except (binascii.Error, ValueError):
        return False
    if not hmac.compare_digest(_firma(cfg["secreto"], caduca_b), recibida):
        return False
    try:
        return int(caduca_b) > time.time()
    except ValueError:
        return False


# ------------------------------------------- freno a la fuerza bruta, por IP
_intentos: dict = {}
_candado = threading.Lock()


def bloqueado(ip: str) -> float:
    """Segundos que faltan para poder reintentar. 0 si se puede probar ya."""
    with _candado:
        n, hasta = _intentos.get(ip, (0, 0.0))
    return max(0.0, hasta - time.time())


def anota_fallo(ip: str) -> None:
    with _candado:
        n, _ = _intentos.get(ip, (0, 0.0))
        n += 1
        # Espera creciente desde el cuarto fallo; a partir de MAX_INTENTOS, 15 min.
        espera = 0.0 if n < 4 else (BLOQUEO if n >= MAX_INTENTOS else 2 ** (n - 3))
        _intentos[ip] = (n, time.time() + espera)


def limpia_fallos(ip: str) -> None:
    with _candado:
        _intentos.pop(ip, None)


# --------------------------------------------------------------------- utils
def cookie_de(cabecera: str, nombre: str = "sesion") -> str:
    for trozo in (cabecera or "").split(";"):
        k, _, v = trozo.strip().partition("=")
        if k == nombre:
            return v
    return ""


def estado(host: str) -> Tuple[Optional[dict], bool]:
    """Devuelve (configuración, hace_falta_clave) para el host donde escuchamos."""
    cfg = cargar()
    local = host in ("127.0.0.1", "::1", "localhost")
    return cfg, (cfg is not None or not local)
