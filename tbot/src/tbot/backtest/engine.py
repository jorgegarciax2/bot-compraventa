"""Motor de backtesting event-driven.

Dos decisiones de diseño que son el corazón del asunto:

1. LA ESTRATEGIA NO PUEDE VER EL FUTURO POR CONSTRUCCIÓN.
   No es una convención que haya que recordar: el Contexto que recibe la estrategia
   solo expone datos hasta la barra actual, porque físicamente no tiene el resto.

2. LA SEÑAL SE CALCULA CON EL CIERRE DE t Y SE EJECUTA EN LA APERTURA DE t+1.
   Es lo que pasa en la realidad: cuando ves el cierre, ya no puedes operar a ese
   precio. Los backtests que ejecutan al mismo close que generó la señal inventan
   rentabilidad que no existe.

La estrategia devuelve PESOS OBJETIVO, no órdenes. El tamaño de posición es
responsabilidad de la capa de riesgo, no de la señal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tbot.backtest.costs import CostModel

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- contexto
class Context:
    """Lo que la estrategia ve en la barra i. Nada más."""

    def __init__(self, panel: dict[str, pd.DataFrame], index: pd.DatetimeIndex):
        self._panel = panel
        self._index = index
        self._i = 0
        self.equity = 0.0
        self.posiciones: dict[str, float] = {}

    def _set_bar(self, i: int) -> None:
        self._i = i

    @property
    def now(self) -> pd.Timestamp:
        return self._index[self._i]

    @property
    def symbols(self) -> list[str]:
        return list(self._panel.keys())

    def history(self, symbol: str, n: int | None = None) -> pd.DataFrame:
        """Velas del símbolo HASTA la barra actual incluida. Nunca más allá."""
        df = self._panel[symbol].iloc[: self._i + 1]
        return df if n is None else df.iloc[-n:]

    def close(self, symbol: str) -> float:
        return float(self._panel[symbol]["close"].iat[self._i])

    def serie(self, symbol: str, col: str = "close", n: int | None = None) -> pd.Series:
        s = self._panel[symbol][col].iloc[: self._i + 1]
        return s if n is None else s.iloc[-n:]

    def barras_disponibles(self, symbol: str) -> int:
        """Cuántas velas válidas hay hasta ahora. Las estrategias lo usan para
        no operar antes de tener datos suficientes."""
        return int(self._panel[symbol]["close"].iloc[: self._i + 1].notna().sum())


# ------------------------------------------------------------------- estrategia
class Strategy:
    """Clase base. Implementar `target_weights`.

    Un peso de 0.5 en un símbolo significa "quiero el 50% del capital ahí".
    Negativo = corto. La suma de |pesos| por encima de 1 sería apalancamiento:
    el motor lo recorta, porque en este sistema no se usa apalancamiento.
    """

    nombre = "base"

    def on_start(self, ctx: Context) -> None:
        pass

    def target_weights(self, ctx: Context) -> dict[str, float] | None:
        """Pesos objetivo para la barra siguiente.

        Devolver None significa "mantener la cartera tal cual": el motor no emite
        ninguna orden. Es la diferencia entre comprar y mantener de verdad y un
        equiponderado que rebalancea a diario y se come las comisiones.
        """
        raise NotImplementedError


# -------------------------------------------------------------------- resultado
@dataclass
class BacktestResult:
    equity: pd.Series
    posiciones: pd.DataFrame
    trades: pd.DataFrame
    metricas: dict = field(default_factory=dict)
    estrategia: str = ""
    capital_inicial: float = 0.0

    def __str__(self) -> str:
        from tbot.backtest.metrics import formatear

        return f"Backtest [{self.estrategia}]\n{formatear(self.metricas)}"


# ----------------------------------------------------------------------- motor
class Backtester:
    def __init__(
        self,
        costes: CostModel | None = None,
        capital_inicial: float = 10_000.0,
        max_exposicion: float = 1.0,
        permitir_cortos: bool = False,
        banda_rebalanceo: float = 0.0,
    ):
        """
        banda_rebalanceo: desviación mínima respecto al peso objetivo, como
            fracción del patrimonio, por debajo de la cual NO se opera. Sin ella
            el motor persigue el peso exacto en cada barra y sangra comisiones
            por ajustes irrelevantes. 0.0 = rebalanceo perfecto (solo para tests);
            en producción, entre 0.02 y 0.10.
        """
        self.costes = costes or CostModel()
        self.capital_inicial = capital_inicial
        self.max_exposicion = max_exposicion
        self.permitir_cortos = permitir_cortos
        self.banda_rebalanceo = banda_rebalanceo

    # ---------------------------------------------------------------- panel
    @staticmethod
    def construir_panel(datos: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DatetimeIndex]:
        """Alinea todos los símbolos en un eje temporal común.

        Los huecos quedan como NaN, NO se rellenan hacia adelante con precios
        inventados: si no hubo vela, no se puede operar, y el motor lo respeta.
        """
        if not datos:
            raise ValueError("no hay datos")
        idx = pd.DatetimeIndex(sorted(set().union(*[set(df["ts"]) for df in datos.values()])))
        panel = {}
        for sym, df in datos.items():
            d = df.set_index("ts").reindex(idx)
            panel[sym] = d[["open", "high", "low", "close", "volume"]]
        return panel, idx

    # --------------------------------------------------------------- ejecutar
    def run(self, datos: dict[str, pd.DataFrame], estrategia: Strategy,
            timeframe: str = "1d", market: str = "crypto") -> BacktestResult:
        from tbot.backtest.metrics import calcular

        panel, idx = self.construir_panel(datos)
        n = len(idx)
        if n < 2:
            raise ValueError("hacen falta al menos 2 barras")

        ctx = Context(panel, idx)
        estrategia.on_start(ctx)

        cash = self.capital_inicial
        unidades: dict[str, float] = {s: 0.0 for s in panel}
        coste_medio: dict[str, float] = {s: 0.0 for s in panel}

        equity_hist = np.full(n, np.nan)
        pos_hist: list[dict] = []
        trades: list[dict] = []
        pendientes: dict[str, float] | None = None

        # Acceso posicional a numpy: mucho más rápido que .iloc dentro del bucle.
        opens = {s: panel[s]["open"].to_numpy(dtype=float) for s in panel}
        closes = {s: panel[s]["close"].to_numpy(dtype=float) for s in panel}

        for i in range(n):
            t = idx[i]

            # --- 1. Ejecutar lo que se decidió en la barra anterior ----------
            if pendientes:
                # Se revaloriza la cartera a precios de EJECUCIÓN antes de calcular
                # el objetivo: así un peso constante no genera operaciones espurias.
                eq_exec = cash + sum(
                    u * opens[s][i] for s, u in unidades.items() if not np.isnan(opens[s][i])
                )
                for sym, w in pendientes.items():
                    px = opens[sym][i]
                    if np.isnan(px) or px <= 0:
                        continue  # sin vela no hay mercado: la orden no se ejecuta
                    objetivo = w * eq_exec / px
                    delta = objetivo - unidades[sym]
                    if abs(delta * px) < 1e-8:
                        continue
                    # Banda muerta: los ajustes pequeños no compensan su coste.
                    # Cerrar del todo (w == 0) siempre se ejecuta.
                    if (
                        self.banda_rebalanceo > 0
                        and w != 0.0
                        and abs(delta * px) < self.banda_rebalanceo * eq_exec
                    ):
                        continue

                    lado = 1 if delta > 0 else -1
                    px_fill = self.costes.precio_ejecucion(px, lado)
                    notional = delta * px_fill
                    com = self.costes.comision(notional)

                    pnl = None
                    if lado < 0 and unidades[sym] > 0:  # cierre total o parcial de largo
                        cerradas = min(abs(delta), unidades[sym])
                        pnl = cerradas * (px_fill - coste_medio[sym])
                    if lado > 0:
                        prev_u, prev_c = unidades[sym], coste_medio[sym]
                        nuevas = prev_u + delta
                        coste_medio[sym] = (
                            (prev_u * prev_c + delta * px_fill) / nuevas if nuevas != 0 else 0.0
                        )

                    cash -= notional + com
                    unidades[sym] += delta

                    trades.append(
                        {
                            "ts": t,
                            "symbol": sym,
                            "lado": "compra" if lado > 0 else "venta",
                            "unidades": delta,
                            "precio": px_fill,
                            "precio_mercado": px,
                            "notional": notional,
                            "comision": com,
                            "pnl": pnl,
                        }
                    )
                pendientes = None

            # --- 2. Valorar la cartera al cierre de esta barra ---------------
            eq = cash
            for s, u in unidades.items():
                px = closes[s][i]
                if u != 0 and not np.isnan(px):
                    eq += u * px
            equity_hist[i] = eq

            pos_hist.append(
                {"ts": t, "cash": cash, "equity": eq,
                 **{f"pos_{s}": unidades[s] for s in panel}}
            )

            # --- 3. Pedir señal (con datos hasta AQUÍ) para operar en t+1 -----
            if i < n - 1:
                ctx._set_bar(i)
                ctx.equity = eq
                ctx.posiciones = dict(unidades)
                pesos = estrategia.target_weights(ctx)
                pendientes = None if pesos is None else self._sanear(pesos, panel)

        equity = pd.Series(equity_hist, index=idx, name="equity")
        df_trades = pd.DataFrame(trades)
        res = BacktestResult(
            equity=equity,
            posiciones=pd.DataFrame(pos_hist).set_index("ts"),
            trades=df_trades,
            estrategia=getattr(estrategia, "nombre", estrategia.__class__.__name__),
            capital_inicial=self.capital_inicial,
        )
        res.metricas = calcular(equity, df_trades, timeframe=timeframe, market=market)
        return res

    # ---------------------------------------------------------------- helpers
    def _sanear(self, pesos: dict[str, float], panel: dict) -> dict[str, float]:
        """Aplica los límites duros del motor: sin cortos si no están permitidos,
        y sin apalancamiento nunca."""
        limpio = {}
        for s, w in pesos.items():
            if s not in panel:
                raise KeyError(f"la estrategia pide un símbolo que no está en los datos: {s}")
            w = float(w)
            if not self.permitir_cortos:
                w = max(0.0, w)
            limpio[s] = w

        bruto = sum(abs(w) for w in limpio.values())
        if bruto > self.max_exposicion and bruto > 0:
            factor = self.max_exposicion / bruto
            limpio = {s: w * factor for s, w in limpio.items()}
        return limpio
