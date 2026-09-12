"""Diario de a bordo: todo lo que hace el agente queda escrito.

Un agente autónomo sin registro es una caja negra que te dice "he perdido
dinero". El diario es JSONL (una línea por evento) para poder leerlo con
`jq`, importarlo a un CSV o repintar la curva de equity después.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


class Diario:
    def __init__(self, ruta: Optional[str | Path], eco: bool = False) -> None:
        self.ruta = Path(ruta) if ruta else None
        self.eco = eco
        if self.ruta:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self._f = self.ruta.open("a", encoding="utf-8")
        else:
            self._f = None

    def anota(self, tipo: str, **datos: Any) -> Dict[str, Any]:
        ev = {"ts": time.time(), "tipo": tipo, **datos}
        if self._f:
            self._f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
            self._f.flush()
        if self.eco:
            print(self._legible(ev))
        return ev

    @staticmethod
    def _legible(ev: Dict[str, Any]) -> str:
        t = ev["tipo"]
        if t == "operacion":
            return (f"  · {ev['lado']:6s} {ev['cantidad']:.6f} {ev['simbolo']} "
                    f"@ {ev['precio']:.4f}  ({ev.get('motivo', '')})")
        if t == "muerte":
            return f"  ✝ MUERTE [{ev['causa']}] {ev.get('detalle', '')}"
        if t == "nacimiento":
            return (f"  ● NACE con {ev['capital']:.2f} {ev.get('divisa', '')} "
                    f"— estrategia {ev.get('estrategia')}")
        return f"  · {t}: {ev}"

    def cerrar(self) -> None:
        if self._f:
            self._f.close()
            self._f = None

    def __enter__(self) -> "Diario":
        return self

    def __exit__(self, *exc) -> None:
        self.cerrar()


def leer(ruta: str | Path) -> Iterator[Dict[str, Any]]:
    with Path(ruta).open(encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                yield json.loads(linea)
