"""Capa de riesgo: traduce el deseo de la estrategia en algo que no te arruine.

Toda la protección del capital vive aquí, no en las estrategias. Si mañana
escribes una estrategia agresiva, sigue pasando por este filtro.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .broker import COMPRA, VENTA, Orden
from .cartera import Cartera


@dataclass
class ReglasRiesgo:
    max_exposicion: float = 0.95     # nunca el 100 %: deja caja para costes
    stop_loss: float = 0.15          # corta si pierde 15 % desde el precio medio
    trailing_stop: float = 0.25      # ...o 25 % desde el máximo alcanzado
    banda_rebalanceo: float = 0.10   # ignora ajustes < 10 % de equity (ahorra comisiones)
    max_ops_por_dia: Optional[int] = None

    def valida(self) -> None:
        if not 0 < self.max_exposicion <= 1:
            raise ValueError("max_exposicion debe estar en (0, 1]")
        for nombre in ("stop_loss", "trailing_stop"):
            v = getattr(self, nombre)
            if v is not None and not 0 < v < 1:
                raise ValueError(f"{nombre} debe estar en (0, 1) o None")


class GestorRiesgo:
    def __init__(self, reglas: Optional[ReglasRiesgo] = None) -> None:
        self.reglas = reglas or ReglasRiesgo()
        self.reglas.valida()
        self.ultimo_stop: str = ""

    def ordenes(self, simbolo: str, objetivo: Optional[float], precio: float,
                cartera: Cartera, equity: float) -> List[Orden]:
        """Convierte una exposición objetivo en órdenes concretas."""
        self.ultimo_stop = ""
        pos = cartera.posicion(simbolo)
        if pos.abierta:
            pos.maximo_favorable = max(pos.maximo_favorable, precio)

        # --- los stops mandan por encima de la estrategia ---------------
        forzado = self._stop_disparado(pos, precio)
        if forzado:
            self.ultimo_stop = forzado
            objetivo = 0.0
        elif objetivo is None:
            return []                       # la estrategia no opina: no tocar

        objetivo = max(0.0, min(self.reglas.max_exposicion, objetivo))
        if equity <= 0:
            return []

        actual = pos.valor(precio) / equity
        delta = objetivo - actual
        if not forzado and abs(delta) < self.reglas.banda_rebalanceo:
            return []

        importe = abs(delta) * equity
        cantidad = importe / precio
        if cantidad <= 0:
            return []

        if delta > 0:
            motivo = f"subir exposición {actual:.0%}→{objetivo:.0%}"
            return [Orden(simbolo, COMPRA, cantidad, motivo)]
        motivo = forzado or f"bajar exposición {actual:.0%}→{objetivo:.0%}"
        cantidad = pos.cantidad if objetivo == 0.0 else min(cantidad, pos.cantidad)
        return [Orden(simbolo, VENTA, cantidad, motivo)] if cantidad > 0 else []

    def _stop_disparado(self, pos, precio: float) -> str:
        if not pos.abierta:
            return ""
        r = self.reglas
        if r.stop_loss and pos.precio_medio > 0:
            if precio <= pos.precio_medio * (1 - r.stop_loss):
                return (f"stop-loss: {precio:.4f} <= "
                        f"{pos.precio_medio * (1 - r.stop_loss):.4f}")
        if r.trailing_stop and pos.maximo_favorable > 0:
            if precio <= pos.maximo_favorable * (1 - r.trailing_stop):
                return (f"trailing-stop: {precio:.4f} <= "
                        f"{pos.maximo_favorable * (1 - r.trailing_stop):.4f}")
        return ""
