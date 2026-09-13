"""Estrategias incluidas. Cada una es unas pocas líneas: ése es el objetivo.

Ninguna es un consejo de inversión ni tiene alfa garantizado. Son puntos de
partida honestos y un banco de pruebas para comparar contra `ComprarYAguantar`
y contra `Azar`, que es el control: si tu estrategia no bate al azar y a
aguantar, no tienes estrategia.
"""
from __future__ import annotations

import random
from typing import Optional

from ..core import estructura as est
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


class Estructura(Estrategia):
    """Estructura de mercado: tendencia, soportes, resistencias y figuras.

    Las cuatro decisiones, en orden de autoridad:

    1. **Figuras.** Un hombro-cabeza-hombro con el cuello perdido saca del
       mercado; el invertido con el cuello superado mete. Una figura sin el
       cuello roto no es una señal, es un dibujo.
    2. **Fuerza de tendencia (ADX).** Por debajo del umbral el mercado está
       lateral: las rupturas de nivel son casi todas falsas y no se opera.
    3. **Dirección (medias).** Sin tendencia alcista, fuera.
    4. **Niveles.** Romper una resistencia muy tocada da exposición plena;
       chocar contra ella sin romperla la reduce; perder un soporte cierra.

    El tamaño final lo dosifica la volatilidad, igual que `tendencia_vol`: la
    señal dice *si*, la volatilidad dice *cuánto*.
    """
    nombre = "estructura"

    def __init__(self, rapida: int = 20, lenta: int = 100, adx_minimo: float = 20.0,
                 k_pivote: int = 5, tolerancia: float = 0.015, toques_minimos: int = 2,
                 ventana: int = 400, ventana_vol: int = 48,
                 vol_objetivo: float = 0.012, margen_nivel: float = 0.01,
                 freno_resistencia: float = 1.0, **kw) -> None:
        super().__init__(rapida=rapida, lenta=lenta, adx_minimo=adx_minimo,
                         k_pivote=k_pivote, tolerancia=tolerancia,
                         toques_minimos=toques_minimos, ventana=ventana,
                         ventana_vol=ventana_vol, vol_objetivo=vol_objetivo,
                         margen_nivel=margen_nivel,
                         freno_resistencia=freno_resistencia, **kw)
        self.velas_minimas = max(lenta, ventana_vol, 2 * k_pivote + 1) + 2

    def _tamano(self, cierres) -> float:
        """Cuánto, según la volatilidad. Nunca más de lo que el riesgo tolera."""
        vol = ind.volatilidad(cierres, self.ventana_vol)
        if not vol:
            return 0.0
        return max(0.0, min(1.0, self.vol_objetivo / vol))

    def objetivo(self, ctx: Contexto):
        velas = ctx.velas[-self.ventana:]
        cierres = [v.cierre for v in velas]
        maximos = [v.maximo for v in velas]
        minimos = [v.minimo for v in velas]
        precio = ctx.precio

        altos, bajos = est.pivotes(maximos, minimos, self.k_pivote)

        # 1. Las figuras mandan, pero sólo con el cuello roto.
        figura_baja = est.hombro_cabeza_hombro(altos, bajos)
        if figura_baja and precio < figura_baja["cuello"]:
            return 0.0
        figura_alta = est.hch_invertido(altos, bajos)
        if figura_alta and precio > figura_alta["cuello"]:
            return self._tamano(cierres)

        # 2. ¿Hay tendencia que operar?
        fuerza = ind.adx(maximos, minimos, cierres, 14)
        if fuerza is None or fuerza < self.adx_minimo:
            return 0.0

        # 3. ¿Hacia dónde?
        r, l = ind.ema(cierres, self.rapida), ind.ema(cierres, self.lenta)
        if r is None or l is None or r <= l:
            return 0.0

        # 4. Los niveles deciden el matiz.
        sop, res = est.soportes_resistencias(
            maximos, minimos, precio, self.k_pivote,
            self.tolerancia, self.toques_minimos)
        tamano = self._tamano(cierres)

        if sop:
            nivel, toques = sop[0]
            if precio < nivel * (1 - self.margen_nivel) and toques >= self.toques_minimos:
                return 0.0                      # soporte perdido: fuera

        if res:
            nivel, toques = res[0]
            if precio >= nivel * (1 - self.margen_nivel):
                # Pegado a una resistencia muy tocada: a medio gas hasta romperla.
                return tamano * (self.freno_resistencia
                                 if toques >= self.toques_minimos else 1.0)

        return tamano


class TendenciaVolumen(Estrategia):
    """Tendencia confirmada por volumen. Pensada para acciones.

    La diferencia con `tendencia_vol` es una sola pregunta añadida: ¿hay dinero
    detrás del movimiento? Una subida con el volumen secándose es una subida
    en la que cada vez participa menos gente, y suele terminar mal. El OBV
    (volumen acumulado con signo) responde a eso.

    En cripto el volumen es menos fiable —mercados fragmentados, operativa
    artificial—, pero en acciones lo publica el propio mercado.
    """
    nombre = "tendencia_volumen"

    def __init__(self, rapida: int = 20, lenta: int = 100, ventana_vol: int = 48,
                 vol_objetivo: float = 0.012, ventana_obv: int = 20,
                 sin_volumen: float = 0.5, **kw) -> None:
        super().__init__(rapida=rapida, lenta=lenta, ventana_vol=ventana_vol,
                         vol_objetivo=vol_objetivo, ventana_obv=ventana_obv,
                         sin_volumen=sin_volumen, **kw)
        self.velas_minimas = max(lenta, ventana_vol, ventana_obv) + 2

    def objetivo(self, ctx: Contexto):
        c = ctx.cierres
        r, l = ind.ema(c, self.rapida), ind.ema(c, self.lenta)
        if r is None or l is None or r <= l:
            return 0.0
        vol = ind.volatilidad(c, self.ventana_vol)
        if not vol:
            return 0.0
        tamano = max(0.0, min(1.0, self.vol_objetivo / vol))

        volumenes = [v.volumen for v in ctx.velas]
        if not any(volumenes):
            return tamano                     # sin datos de volumen, no penaliza
        acompana = ind.obv_acompana(c, volumenes, self.ventana_obv)
        if acompana is False:
            return tamano * self.sin_volumen  # sube el precio pero no el dinero
        return tamano


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
        TendenciaConVolatilidad, TendenciaVolumen, Estructura, Azar,
    )
}


def crear(nombre: str, **params) -> Estrategia:
    if nombre not in CATALOGO:
        raise ValueError(f"Estrategia desconocida: {nombre}. "
                         f"Disponibles: {sorted(CATALOGO)}")
    return CATALOGO[nombre](**params)
