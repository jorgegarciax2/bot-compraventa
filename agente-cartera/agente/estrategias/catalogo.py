"""Estrategias incluidas. Cada una es unas pocas líneas: ése es el objetivo.

Ninguna es un consejo de inversión ni tiene alfa garantizado. Son puntos de
partida honestos y un banco de pruebas para comparar contra `ComprarYAguantar`
y contra `Azar`, que es el control: si tu estrategia no bate al azar y a
aguantar, no tienes estrategia.
"""
from __future__ import annotations

import random
from typing import Optional

from ..core import indicadores as ind
from .base import Contexto, Estrategia


class ComprarYAguantar(Estrategia):
    """Referencia obligatoria. Compra todo lo permitido y no toca nada más."""
    nombre = "comprar_y_aguantar"
    velas_minimas = 1

    def objetivo(self, ctx: Contexto) -> Optional[float]:
        return 1.0


class CruceMedias(Estrategia):
    """Seguimiento de tendencia clásico: dentro si la media rápida > lenta."""
    nombre = "cruce_medias"

    def __init__(self, rapida: int = 20, lenta: int = 60, **kw) -> None:
        super().__init__(rapida=rapida, lenta=lenta, **kw)
        self.velas_minimas = lenta + 1

    def objetivo(self, ctx: Contexto) -> Optional[float]:
        c = ctx.cierres
        r, l = ind.ema(c, self.rapida), ind.ema(c, self.lenta)
        if r is None or l is None:
            return 0.0
        return 1.0 if r > l else 0.0


class RupturaCanal(Estrategia):
    """Momentum tipo Donchian: entra al romper máximos, sale al perder mínimos."""
    nombre = "ruptura_canal"

    def __init__(self, entrada: int = 55, salida: int = 20, **kw) -> None:
        super().__init__(entrada=entrada, salida=salida, **kw)
        self.velas_minimas = entrada + 1

    def objetivo(self, ctx: Contexto) -> Optional[float]:
        c = ctx.cierres
        techo = ind.maximo(c[:-1], self.entrada)
        suelo = ind.minimo(c[:-1], self.salida)
        if techo is None or suelo is None:
            return 0.0
        if ctx.precio > techo:
            return 1.0
        if ctx.precio < suelo:
            return 0.0
        return None      # dentro del canal: mantiene lo que tenga


class ReversionMedia(Estrategia):
    """Compra caídas dentro de una tendencia alcista y suelta en el rebote.

    El filtro de tendencia larga es lo que evita el clásico "comprar barato
    todo el camino hacia cero".
    """
    nombre = "reversion_media"

    def __init__(self, ventana: int = 24, z_entrada: float = -1.5,
                 z_salida: float = 0.3, filtro_tendencia: int = 200, **kw) -> None:
        super().__init__(ventana=ventana, z_entrada=z_entrada,
                         z_salida=z_salida, filtro_tendencia=filtro_tendencia, **kw)
        self.velas_minimas = max(ventana, filtro_tendencia) + 1

    def objetivo(self, ctx: Contexto) -> Optional[float]:
        c = ctx.cierres
        tendencia = ind.sma(c, self.filtro_tendencia)
        z = ind.zscore(c, self.ventana)
        if z is None or tendencia is None:
            return 0.0
        if ctx.precio < tendencia:      # sin tendencia alcista, fuera
            return 0.0
        if z <= self.z_entrada:
            return 1.0
        if z >= self.z_salida:
            return 0.0
        return None


class TendenciaConVolatilidad(Estrategia):
    """Tendencia, pero dosificando: cuanto más vuela el precio, menos peso.

    Es la más "adulta" del catálogo: la exposición no es 0 ó 1, sino la que
    hace que el riesgo aportado sea aproximadamente constante.
    """
    nombre = "tendencia_vol"

    def __init__(self, rapida: int = 20, lenta: int = 100, ventana_vol: int = 48,
                 vol_objetivo: float = 0.012, **kw) -> None:
        super().__init__(rapida=rapida, lenta=lenta, ventana_vol=ventana_vol,
                         vol_objetivo=vol_objetivo, **kw)
        self.velas_minimas = max(lenta, ventana_vol) + 2

    def objetivo(self, ctx: Contexto) -> Optional[float]:
        c = ctx.cierres
        r, l = ind.ema(c, self.rapida), ind.ema(c, self.lenta)
        if r is None or l is None or r <= l:
            return 0.0
        vol = ind.volatilidad(c, self.ventana_vol)
        if not vol:
            return 0.0
        return max(0.0, min(1.0, self.vol_objetivo / vol))


class Azar(Estrategia):
    """Control negativo: decide a cara o cruz. Sirve para dos cosas.

    1. Comprobar que el agente muere de verdad cuando opera sin criterio.
    2. Recordar que cualquier estrategia que no lo bata claramente es ruido.
    """
    nombre = "azar"
    velas_minimas = 1

    def __init__(self, semilla: int = 42, prob_dentro: float = 0.5, **kw) -> None:
        super().__init__(semilla=semilla, prob_dentro=prob_dentro, **kw)
        self._rnd = random.Random(semilla)

    def objetivo(self, ctx: Contexto) -> Optional[float]:
        return 1.0 if self._rnd.random() < self.prob_dentro else 0.0


CATALOGO = {
    c.nombre: c for c in (
        ComprarYAguantar, CruceMedias, RupturaCanal, ReversionMedia,
        TendenciaConVolatilidad, Azar,
    )
}


def crear(nombre: str, **params) -> Estrategia:
    if nombre not in CATALOGO:
        raise ValueError(f"Estrategia desconocida: {nombre}. "
                         f"Disponibles: {sorted(CATALOGO)}")
    return CATALOGO[nombre](**params)
