"""Contrato de las estrategias.

Una estrategia NO manda órdenes ni calcula tamaños: sólo dice qué fracción
del patrimonio quiere tener invertida en el activo, entre 0 y 1. El motor y
la capa de riesgo traducen ese deseo en órdenes ejecutables. Así todas las
estrategias son comparables y el riesgo se gestiona en un único sitio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from ..core.cartera import Cartera, Posicion
from ..core.datos import Vela


@dataclass
class Contexto:
    simbolo: str
    velas: List[Vela]          # histórico hasta la vela actual, incluida
    cartera: Cartera
    equity: float
    tick: int = 0

    @property
    def vela(self) -> Vela:
        return self.velas[-1]

    @property
    def precio(self) -> float:
        return self.velas[-1].cierre

    @property
    def cierres(self) -> List[float]:
        return [v.cierre for v in self.velas]

    @property
    def maximos(self) -> List[float]:
        return [v.maximo for v in self.velas]

    @property
    def minimos(self) -> List[float]:
        return [v.minimo for v in self.velas]

    @property
    def posicion(self) -> Posicion:
        return self.cartera.posicion(self.simbolo)

    @property
    def exposicion(self) -> float:
        """Fracción del equity actualmente invertida (0..1)."""
        if self.equity <= 0:
            return 0.0
        return self.posicion.valor(self.precio) / self.equity


class Estrategia:
    """Subclasa esto y escribe `objetivo`. Eso es toda la API."""
    nombre = "base"
    velas_minimas = 2

    def __init__(self, **params) -> None:
        self.params = params
        for k, v in params.items():
            setattr(self, k, v)

    def objetivo(self, ctx: Contexto) -> Optional[float]:
        """Fracción deseada del equity en el activo, 0..1.

        Devuelve None para "no opinar" (el motor mantiene la posición).
        """
        raise NotImplementedError

    def describe(self) -> str:
        p = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.nombre}({p})" if p else self.nombre
