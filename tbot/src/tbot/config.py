"""Carga de configuración."""
from __future__ import annotations

from pathlib import Path

import yaml


def cargar(ruta: str | Path = "config/config.yaml") -> dict:
    p = Path(ruta)
    if not p.exists():
        raise FileNotFoundError(f"no encuentro la configuración en {p}")
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
