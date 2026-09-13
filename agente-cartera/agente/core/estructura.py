"""Estructura de mercado: pivotes, soportes, resistencias y figuras.

La regla que sostiene todo este módulo: **un pivote no existe hasta que el
mercado lo confirma**. Un máximo local sólo se sabe que lo era cuando han
pasado `k` velas sin superarlo. Detectarlo en el momento sería mirar el futuro,
y un backtest que hace eso no da un resultado malo, da uno espectacular y falso.

Por eso `pivotes()` nunca devuelve nada de las últimas `k` velas.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

Pivote = Tuple[int, float]        # (índice de la vela, precio)


# --------------------------------------------------------------------- pivotes
def pivotes(maximos: Sequence[float], minimos: Sequence[float],
            k: int = 3) -> Tuple[List[Pivote], List[Pivote]]:
    """Máximos y mínimos locales confirmados: k velas a cada lado sin superarlo.

    Devuelve (altos, bajos) en orden cronológico. Las últimas k velas quedan
    fuera a propósito: todavía no se pueden confirmar.
    """
    altos: List[Pivote] = []
    bajos: List[Pivote] = []
    n = len(maximos)
    if n < 2 * k + 1:
        return altos, bajos
    for i in range(k, n - k):
        ventana_alta = maximos[i - k:i + k + 1]
        if maximos[i] == max(ventana_alta) and maximos[i] > maximos[i - 1]:
            altos.append((i, maximos[i]))
        ventana_baja = minimos[i - k:i + k + 1]
        if minimos[i] == min(ventana_baja) and minimos[i] < minimos[i - 1]:
            bajos.append((i, minimos[i]))
    return altos, bajos


# -------------------------------------------------------------------- niveles
def agrupar(precios: Sequence[float], tolerancia: float = 0.01) -> List[Tuple[float, int]]:
    """Junta precios parecidos en niveles. Devuelve (nivel, nº de toques).

    Un nivel tocado tres veces pesa más que uno tocado una vez: eso es lo que
    separa un soporte de una coincidencia.
    """
    if not precios:
        return []
    ordenados = sorted(precios)
    grupos: List[List[float]] = [[ordenados[0]]]
    for p in ordenados[1:]:
        referencia = sum(grupos[-1]) / len(grupos[-1])
        if referencia > 0 and abs(p - referencia) / referencia <= tolerancia:
            grupos[-1].append(p)
        else:
            grupos.append([p])
    return [(sum(g) / len(g), len(g)) for g in grupos]


def soportes_resistencias(maximos: Sequence[float], minimos: Sequence[float],
                          precio: float, k: int = 3, tolerancia: float = 0.01,
                          minimos_toques: int = 1
                          ) -> Tuple[List[Tuple[float, int]], List[Tuple[float, int]]]:
    """Niveles por debajo (soportes) y por encima (resistencias) del precio.

    Ordenados por cercanía al precio actual. Cada uno con su número de toques.
    """
    altos, bajos = pivotes(maximos, minimos, k)
    niveles = agrupar([p for _, p in altos] + [p for _, p in bajos], tolerancia)
    niveles = [(nv, t) for nv, t in niveles if t >= minimos_toques]
    soportes = sorted([x for x in niveles if x[0] < precio], key=lambda x: -x[0])
    resistencias = sorted([x for x in niveles if x[0] > precio], key=lambda x: x[0])
    return soportes, resistencias


# --------------------------------------------------------------------- figuras
def _similares(a: float, b: float, tolerancia: float) -> bool:
    base = (a + b) / 2
    return base > 0 and abs(a - b) / base <= tolerancia


def hombro_cabeza_hombro(altos: Sequence[Pivote], bajos: Sequence[Pivote],
                         tolerancia_hombros: float = 0.03,
                         minimo_cabeza: float = 0.01) -> Optional[dict]:
    """Busca un HCH bajista en los últimos pivotes.

    Necesita alto-bajo-alto-bajo-alto alternados: hombro, valle, cabeza (más
    alta), valle, hombro (parecido al primero). La línea de cuello une los dos
    valles; la figura no vale nada hasta que el precio la pierde.

    Devuelve {'cuello', 'cabeza', 'hombros', 'objetivo'} o None.
    """
    if len(altos) < 3 or len(bajos) < 2:
        return None
    h1, cabeza, h2 = altos[-3], altos[-2], altos[-1]
    valles = [b for b in bajos if h1[0] < b[0] < h2[0]]
    if len(valles) < 2:
        return None
    v1, v2 = valles[0], valles[-1]

    if not (h1[0] < v1[0] < cabeza[0] < v2[0] < h2[0]):
        return None
    if cabeza[1] <= h1[1] * (1 + minimo_cabeza) or cabeza[1] <= h2[1] * (1 + minimo_cabeza):
        return None                                   # la cabeza debe destacar
    if not _similares(h1[1], h2[1], tolerancia_hombros):
        return None                                   # hombros a distinta altura

    cuello = (v1[1] + v2[1]) / 2
    return {"tipo": "hch", "cuello": cuello, "cabeza": cabeza[1],
            "hombros": (h1[1], h2[1]),
            "objetivo": cuello - (cabeza[1] - cuello),  # proyección clásica
            "indice_fin": h2[0]}


def hch_invertido(altos: Sequence[Pivote], bajos: Sequence[Pivote],
                  tolerancia_hombros: float = 0.03,
                  minimo_cabeza: float = 0.01) -> Optional[dict]:
    """El mismo patrón del revés: suelo con hombro-cabeza-hombro, señal alcista."""
    if len(bajos) < 3 or len(altos) < 2:
        return None
    h1, cabeza, h2 = bajos[-3], bajos[-2], bajos[-1]
    picos = [a for a in altos if h1[0] < a[0] < h2[0]]
    if len(picos) < 2:
        return None
    p1, p2 = picos[0], picos[-1]

    if not (h1[0] < p1[0] < cabeza[0] < p2[0] < h2[0]):
        return None
    if cabeza[1] >= h1[1] * (1 - minimo_cabeza) or cabeza[1] >= h2[1] * (1 - minimo_cabeza):
        return None
    if not _similares(h1[1], h2[1], tolerancia_hombros):
        return None

    cuello = (p1[1] + p2[1]) / 2
    return {"tipo": "hch_invertido", "cuello": cuello, "cabeza": cabeza[1],
            "hombros": (h1[1], h2[1]),
            "objetivo": cuello + (cuello - cabeza[1]),
            "indice_fin": h2[0]}
