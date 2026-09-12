"""Indicadores en Python puro (sin numpy/pandas: cero dependencias)."""
from __future__ import annotations

import math
from typing import List, Optional, Sequence


def sma(valores: Sequence[float], n: int) -> Optional[float]:
    if len(valores) < n or n <= 0:
        return None
    return sum(valores[-n:]) / n


def ema(valores: Sequence[float], n: int) -> Optional[float]:
    if len(valores) < n or n <= 0:
        return None
    k = 2 / (n + 1)
    e = sum(valores[:n]) / n
    for v in valores[n:]:
        e = v * k + e * (1 - k)
    return e


def desviacion(valores: Sequence[float], n: int) -> Optional[float]:
    if len(valores) < n or n < 2:
        return None
    m = sum(valores[-n:]) / n
    var = sum((v - m) ** 2 for v in valores[-n:]) / (n - 1)
    return math.sqrt(var)


def retornos(cierres: Sequence[float]) -> List[float]:
    return [cierres[i] / cierres[i - 1] - 1
            for i in range(1, len(cierres)) if cierres[i - 1] > 0]


def volatilidad(cierres: Sequence[float], n: int) -> Optional[float]:
    """Volatilidad por vela (desviación de los retornos)."""
    r = retornos(cierres[-(n + 1):])
    if len(r) < max(2, n // 2):
        return None
    return desviacion(r, len(r))


def rsi(cierres: Sequence[float], n: int = 14) -> Optional[float]:
    if len(cierres) < n + 1:
        return None
    ganancias = perdidas = 0.0
    for i in range(len(cierres) - n, len(cierres)):
        d = cierres[i] - cierres[i - 1]
        ganancias += max(d, 0.0)
        perdidas += max(-d, 0.0)
    if perdidas == 0:
        return 100.0
    rs = (ganancias / n) / (perdidas / n)
    return 100 - 100 / (1 + rs)


def zscore(valores: Sequence[float], n: int) -> Optional[float]:
    m = sma(valores, n)
    s = desviacion(valores, n)
    if m is None or not s:
        return None
    return (valores[-1] - m) / s


def maximo(valores: Sequence[float], n: int) -> Optional[float]:
    return max(valores[-n:]) if len(valores) >= n else None


def minimo(valores: Sequence[float], n: int) -> Optional[float]:
    return min(valores[-n:]) if len(valores) >= n else None


def atr(maximos: Sequence[float], minimos: Sequence[float],
        cierres: Sequence[float], n: int = 14) -> Optional[float]:
    if len(cierres) < n + 1:
        return None
    trs = []
    for i in range(len(cierres) - n, len(cierres)):
        tr = max(maximos[i] - minimos[i],
                 abs(maximos[i] - cierres[i - 1]),
                 abs(minimos[i] - cierres[i - 1]))
        trs.append(tr)
    return sum(trs) / len(trs)
