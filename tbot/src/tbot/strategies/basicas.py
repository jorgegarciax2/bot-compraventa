"""Estrategias de referencia.

Ninguna de estas pretende ganar dinero: existen para validar el motor y para dar
una vara de medir. Cualquier estrategia de la fase 1 tendrá que batir a
`ComprarYMantener` ajustado por riesgo, o no merece correr.
"""
from __future__ import annotations

from tbot.backtest.engine import Context, Strategy
from tbot.features import indicators as ind


class ComprarYMantener(Strategy):
    """Referencia obligatoria. Si una estrategia no bate a esto, sobra.

    Compra a partes iguales en la primera barra y NO vuelve a tocar nada: nada de
    rebalanceos. Con varios activos, rebalancear a pesos fijos genera operaciones
    todos los días y convierte la referencia en una estrategia con costes.
    """

    nombre = "comprar_y_mantener"

    def __init__(self, symbols: list[str] | None = None):
        self.symbols = symbols
        self._comprado = False

    def on_start(self, ctx: Context) -> None:
        self._comprado = False

    def target_weights(self, ctx: Context) -> dict[str, float] | None:
        if self._comprado:
            return None
        self._comprado = True
        syms = self.symbols or ctx.symbols
        w = 1.0 / len(syms)
        return {s: w for s in syms}


class PesosIguales(Strategy):
    """Equiponderado CON rebalanceo en cada barra. Sirve para medir exactamente
    cuánto cuesta rebalancear: compararlo con ComprarYMantener da esa cifra."""

    nombre = "pesos_iguales"

    def __init__(self, symbols: list[str] | None = None):
        self.symbols = symbols

    def target_weights(self, ctx: Context) -> dict[str, float]:
        syms = self.symbols or ctx.symbols
        w = 1.0 / len(syms)
        return {s: w for s in syms}


class CruceMedias(Strategy):
    """Cruce de medias clásico. Está aquí como prueba de vida del motor:
    genera operaciones, permite ver el efecto de los costes y sirve de plantilla."""

    nombre = "cruce_medias"

    def __init__(self, rapida: int = 20, lenta: int = 50, symbols: list[str] | None = None):
        if rapida >= lenta:
            raise ValueError("la media rápida debe ser más corta que la lenta")
        self.rapida, self.lenta = rapida, lenta
        self.symbols = symbols

    def target_weights(self, ctx: Context) -> dict[str, float]:
        syms = self.symbols or ctx.symbols
        activos = {}
        for s in syms:
            if ctx.barras_disponibles(s) < self.lenta + 1:
                activos[s] = 0.0
                continue
            close = ctx.serie(s, "close")
            r = ind.sma(close, self.rapida).iloc[-1]
            l = ind.sma(close, self.lenta).iloc[-1]
            activos[s] = 1.0 if (r == r and l == l and r > l) else 0.0

        n_dentro = sum(1 for v in activos.values() if v > 0)
        if n_dentro == 0:
            return {s: 0.0 for s in syms}
        return {s: (1.0 / n_dentro if v > 0 else 0.0) for s, v in activos.items()}


class Liquidez(Strategy):
    """No hace nada. Sirve para comprobar que sin operaciones la equity es plana."""

    nombre = "liquidez"

    def target_weights(self, ctx: Context) -> dict[str, float]:
        return {s: 0.0 for s in ctx.symbols}
