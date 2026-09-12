"""Métricas de rendimiento ajustado por riesgo.

El retorno total es la métrica menos informativa de todas: no dice nada del
camino recorrido para llegar ahí. Lo que decide si una estrategia es operable
es el drawdown y la consistencia.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PERIODOS_POR_ANYO = {"1m": 525600, "5m": 105120, "15m": 35040, "30m": 17520,
                     "1h": 8760, "4h": 2190, "1d": 365}
# Para acciones el año tiene ~252 sesiones, no 365.
PERIODOS_POR_ANYO_EQUITY = {"1d": 252, "1h": 1638}


def periodos_anyo(timeframe: str, market: str = "crypto") -> float:
    if market == "equity" and timeframe in PERIODOS_POR_ANYO_EQUITY:
        return PERIODOS_POR_ANYO_EQUITY[timeframe]
    return PERIODOS_POR_ANYO.get(timeframe, 365)


def max_drawdown(equity: pd.Series) -> float:
    """Peor caída desde un máximo previo. En negativo."""
    if len(equity) < 2:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def drawdown_series(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def calcular(
    equity: pd.Series,
    trades: pd.DataFrame | None = None,
    timeframe: str = "1d",
    market: str = "crypto",
    rf: float = 0.0,
) -> dict:
    equity = equity.dropna()
    if len(equity) < 2:
        return {"error": "serie de equity demasiado corta"}

    ppa = periodos_anyo(timeframe, market)
    ret = equity.pct_change().dropna()
    anyos = len(equity) / ppa

    total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / anyos) - 1.0) if anyos > 0 else 0.0
    vol = float(ret.std(ddof=1) * np.sqrt(ppa))

    exceso = ret - rf / ppa
    sharpe = float(exceso.mean() / ret.std(ddof=1) * np.sqrt(ppa)) if ret.std(ddof=1) > 0 else 0.0

    # Sortino: solo penaliza la volatilidad a la baja, que es la que duele.
    bajista = ret[ret < 0]
    dd_std = float(bajista.std(ddof=1)) if len(bajista) > 1 else 0.0
    sortino = float(exceso.mean() / dd_std * np.sqrt(ppa)) if dd_std > 0 else 0.0

    mdd = max_drawdown(equity)
    calmar = float(cagr / abs(mdd)) if mdd < 0 else 0.0

    out = {
        "retorno_total": total,
        "cagr": cagr,
        "volatilidad": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": calmar,
        "mejor_barra": float(ret.max()),
        "peor_barra": float(ret.min()),
        "barras": int(len(equity)),
        "anyos": float(anyos),
    }

    if trades is not None and len(trades):
        cerradas = trades[trades.get("pnl").notna()] if "pnl" in trades else trades.iloc[0:0]
        out["n_operaciones"] = int(len(trades))
        out["comisiones_pagadas"] = float(trades["comision"].sum()) if "comision" in trades else 0.0
        if len(cerradas):
            ganadoras = cerradas[cerradas["pnl"] > 0]
            perdedoras = cerradas[cerradas["pnl"] < 0]
            out["win_rate"] = float(len(ganadoras) / len(cerradas))
            suma_g = float(ganadoras["pnl"].sum())
            suma_p = abs(float(perdedoras["pnl"].sum()))
            out["profit_factor"] = float(suma_g / suma_p) if suma_p > 0 else float("inf")
    return out


def formatear(m: dict) -> str:
    if "error" in m:
        return m["error"]
    filas = [
        ("Retorno total", f"{m['retorno_total']:>10.2%}"),
        ("CAGR", f"{m['cagr']:>10.2%}"),
        ("Volatilidad anual", f"{m['volatilidad']:>10.2%}"),
        ("Sharpe", f"{m['sharpe']:>10.2f}"),
        ("Sortino", f"{m['sortino']:>10.2f}"),
        ("Max drawdown", f"{m['max_drawdown']:>10.2%}"),
        ("Calmar", f"{m['calmar']:>10.2f}"),
    ]
    if "n_operaciones" in m:
        filas.append(("Operaciones", f"{m['n_operaciones']:>10d}"))
        filas.append(("Comisiones", f"{m['comisiones_pagadas']:>10.2f}"))
    if "win_rate" in m:
        filas.append(("Win rate", f"{m['win_rate']:>10.2%}"))
        filas.append(("Profit factor", f"{m['profit_factor']:>10.2f}"))
    return "\n".join(f"  {k:<20s} {v}" for k, v in filas)
