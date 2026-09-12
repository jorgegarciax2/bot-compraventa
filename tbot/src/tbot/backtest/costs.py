"""Modelo de costes de transacción.

Un backtest sin costes realistas no es optimista: es inútil. La mayoría de
estrategias que "funcionan" en papel mueren aquí, y es mejor que mueran ahora.
"""
from __future__ import annotations

from dataclasses import dataclass

BPS = 1e-4  # 1 punto básico = 0.01%


@dataclass(frozen=True)
class CostModel:
    comision_bps: float = 10.0   # lo que cobra el bróker por operar
    slippage_bps: float = 5.0    # el precio se mueve mientras llega tu orden
    spread_bps: float = 2.0      # compras a ask y vendes a bid: pagas la mitad del spread

    @classmethod
    def sin_costes(cls) -> "CostModel":
        """Solo para tests y para medir cuánto se come la fricción."""
        return cls(0.0, 0.0, 0.0)

    @property
    def impacto_bps(self) -> float:
        """Lo que empeora tu precio de ejecución, sin contar comisión."""
        return self.slippage_bps + self.spread_bps / 2.0

    def precio_ejecucion(self, precio: float, lado: int) -> float:
        """lado: +1 compra, -1 venta. Compras más caro y vendes más barato, siempre."""
        return precio * (1.0 + lado * self.impacto_bps * BPS)

    def comision(self, notional: float) -> float:
        return abs(notional) * self.comision_bps * BPS
