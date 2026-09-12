"""Indicadores técnicos.

Todos operan sobre series que terminan en la barra actual y devuelven un valor
por barra, alineado. Ninguno mira hacia adelante: se pueden usar dentro del
backtest sin riesgo de lookahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    subidas = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    bajadas = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = subidas / bajadas.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    # Sin ninguna bajada en la ventana el RSI es 100 (y 0 si no hubo subidas).
    # Dejarlo en NaN o en 50 falsea las señales en tendencias limpias.
    out = out.mask(bajadas.eq(0) & subidas.gt(0), 100.0)
    out = out.mask(subidas.eq(0) & bajadas.gt(0), 0.0)
    return out.fillna(50.0)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    return pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """Average True Range: la unidad de riesgo del sistema. El tamaño de cada
    posición se calcula a partir de aquí, no a ojo."""
    return true_range(high, low, close).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def volatilidad(s: pd.Series, n: int = 20, periodos_anyo: int = 365) -> pd.Series:
    return s.pct_change().rolling(n, min_periods=n).std() * np.sqrt(periodos_anyo)


def momentum(s: pd.Series, n: int = 20) -> pd.Series:
    return s / s.shift(n) - 1.0


def zscore(s: pd.Series, n: int = 20) -> pd.Series:
    m = s.rolling(n, min_periods=n).mean()
    d = s.rolling(n, min_periods=n).std()
    return (s - m) / d.replace(0, np.nan)


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    m = sma(s, n)
    d = s.rolling(n, min_periods=n).std()
    return pd.DataFrame({"media": m, "superior": m + k * d, "inferior": m - k * d})


def donchian(high: pd.Series, low: pd.Series, n: int = 20) -> pd.DataFrame:
    """Canal de máximos/mínimos. Base de las estrategias de breakout.

    Ojo: se usa shift(1) porque el máximo de los últimos n incluyendo la barra
    actual contiene información de la propia barra que queremos romper.
    """
    return pd.DataFrame(
        {"techo": high.rolling(n, min_periods=n).max().shift(1),
         "suelo": low.rolling(n, min_periods=n).min().shift(1)}
    )
