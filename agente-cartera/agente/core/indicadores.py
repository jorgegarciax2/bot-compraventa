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


# --------------------------------------------------- fuerza y giro de tendencia
def macd(cierres: Sequence[float], rapida: int = 12, lenta: int = 26,
         senal: int = 9) -> Optional[tuple]:
    """Devuelve (macd, señal, histograma). El histograma es lo que se mira."""
    if len(cierres) < lenta + senal:
        return None
    linea = []
    for i in range(lenta, len(cierres) + 1):
        r, l = ema(cierres[:i], rapida), ema(cierres[:i], lenta)
        if r is None or l is None:
            return None
        linea.append(r - l)
    if len(linea) < senal:
        return None
    s = ema(linea, senal)
    if s is None:
        return None
    return linea[-1], s, linea[-1] - s


def adx(maximos: Sequence[float], minimos: Sequence[float],
        cierres: Sequence[float], n: int = 14) -> Optional[float]:
    """Fuerza de la tendencia, sin decir en qué dirección.

    Por debajo de 20 el mercado está lateral y las rupturas son casi todas
    falsas; por encima de 25 hay tendencia de verdad. Es el filtro que evita
    operar estructura en un mercado que no va a ninguna parte.
    """
    if len(cierres) < 2 * n + 1:
        return None
    dm_mas, dm_menos, trs = [], [], []
    for i in range(1, len(cierres)):
        subida = maximos[i] - maximos[i - 1]
        bajada = minimos[i - 1] - minimos[i]
        dm_mas.append(subida if (subida > bajada and subida > 0) else 0.0)
        dm_menos.append(bajada if (bajada > subida and bajada > 0) else 0.0)
        trs.append(max(maximos[i] - minimos[i],
                       abs(maximos[i] - cierres[i - 1]),
                       abs(minimos[i] - cierres[i - 1])))

    def suavizar(v):
        s = sum(v[:n])
        fuera = [s]
        for x in v[n:]:
            s = s - s / n + x
            fuera.append(s)
        return fuera

    if len(trs) < n:
        return None
    str_, sm, sme = suavizar(trs), suavizar(dm_mas), suavizar(dm_menos)
    dxs = []
    for tr, m, me in zip(str_, sm, sme):
        if tr <= 0:
            continue
        di_mas, di_menos = 100 * m / tr, 100 * me / tr
        total = di_mas + di_menos
        if total > 0:
            dxs.append(100 * abs(di_mas - di_menos) / total)
    if len(dxs) < n:
        return None
    return sum(dxs[-n:]) / n


# ------------------------------------------------------------------- volumen
def volumen_relativo(volumenes: Sequence[float], n: int = 20) -> Optional[float]:
    """Volumen de la última vela frente a su media reciente.

    Por encima de 1,5 hay algo pasando. Una ruptura de nivel sin volumen que la
    acompañe es sospechosa: significa que casi nadie está de acuerdo.
    """
    if len(volumenes) < n + 1:
        return None
    media = sum(volumenes[-(n + 1):-1]) / n
    return (volumenes[-1] / media) if media > 0 else None


def obv(cierres: Sequence[float], volumenes: Sequence[float]) -> Optional[List[float]]:
    """On-Balance Volume: suma el volumen de las velas al alza y resta el de las
    bajistas. Si el precio sube pero el OBV no, la subida no tiene detrás
    dinero que la sostenga."""
    if len(cierres) < 2 or len(volumenes) != len(cierres):
        return None
    serie = [0.0]
    for i in range(1, len(cierres)):
        if cierres[i] > cierres[i - 1]:
            serie.append(serie[-1] + volumenes[i])
        elif cierres[i] < cierres[i - 1]:
            serie.append(serie[-1] - volumenes[i])
        else:
            serie.append(serie[-1])
    return serie


def obv_acompana(cierres: Sequence[float], volumenes: Sequence[float],
                 n: int = 20) -> Optional[bool]:
    """¿El volumen confirma el movimiento del precio en las últimas n velas?"""
    serie = obv(cierres, volumenes)
    if serie is None or len(serie) < n + 1 or len(cierres) < n + 1:
        return None
    subio_precio = cierres[-1] > cierres[-1 - n]
    subio_obv = serie[-1] > serie[-1 - n]
    return subio_precio == subio_obv
