"""Un agente que lleva una cartera de varios valores a la vez.

El `Agente` original opera UN símbolo. Éste lleva varios, y no es lo mismo:
hay que repartir capital, decidir a quién se echa para hacer sitio y respetar
un tope de exposición que ahora es de toda la cartera, no de una posición.

Lo que NO cambia es el resto del motor. La cartera ya guardaba las posiciones
en un diccionario y sabía valorarse con un mapa de precios; el gestor de riesgo
y el broker ya trabajan símbolo a símbolo. Así que esto es un coordinador, no
un motor nuevo — las reglas de vida, los stops y los costes son exactamente los
que ya estaban validados.

Dos decisiones que conviene tener a la vista:

* **Se vende cuando el valor pierde su tendencia, no cuando lo adelantan en el
  ranking.** Rotar la cartera cada vez que cambia el orden es pagar comisiones
  por reordenar lo mismo.
* **Primero se vende y después se compra**, en el mismo latido. Si no, no habría
  caja para entrar en lo nuevo.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..estrategias.base import Contexto, Estrategia
from .broker import Broker, BrokerPapel, COMPRA, VENTA, Orden
from .cartera import Cartera
from .datos import Vela
from .diario import Diario
from .motor import Config
from .riesgo import GestorRiesgo
from .vida import SoporteVital, Vitales, escribir_lapida


class AgenteCartera:
    """Nace con un capital, lo reparte entre N valores y muere si se arruina."""

    def __init__(self, config: Config, crear_estrategia, broker: Optional[Broker] = None,
                 cartera: Optional[Cartera] = None, diario: Optional[Diario] = None,
                 vitales: Optional[Vitales] = None, max_posiciones: int = 5) -> None:
        self.cfg = config
        self.crear_estrategia = crear_estrategia      # una instancia por símbolo
        self.broker = broker or BrokerPapel()
        self.cartera = cartera or Cartera.nueva(config.capital, config.divisa)
        self.riesgo = GestorRiesgo(config.reglas_riesgo)
        self.soporte = SoporteVital(config.reglas_vida,
                                    self.cartera.capital_inicial, vitales)
        self.diario = diario or Diario(None)
        self.max_posiciones = max(1, max_posiciones)
        self.curva_equity: List[float] = []
        self.operaciones: List[dict] = []
        self._estrategias: Dict[str, Estrategia] = {}
        self._nacido = False

    # ------------------------------------------------------------ nacimiento
    def nacer(self) -> None:
        if self._nacido:
            return
        self._nacido = True
        self.diario.anota("nacimiento", capital=self.cartera.capital_inicial,
                          divisa=self.cfg.divisa, cartera=True,
                          max_posiciones=self.max_posiciones,
                          estrategia=self.cfg.estrategia,
                          umbral_ruina=self.soporte.nivel_ruina)

    @property
    def vivo(self) -> bool:
        return self.soporte.vivo

    def _estrategia(self, simbolo: str) -> Estrategia:
        """Una instancia por símbolo: algunas guardan estado interno."""
        if simbolo not in self._estrategias:
            self._estrategias[simbolo] = self.crear_estrategia()
        return self._estrategias[simbolo]

    # ------------------------------------------------------------------ tick
    def tick(self, velas: Dict[str, Sequence[Vela]],
             candidatos: Optional[List[str]] = None) -> Vitales:
        """Un latido de toda la cartera.

        `velas` trae el histórico de cada símbolo que se puede mirar; el orden
        de `candidatos` es la preferencia para entrar cuando hay hueco.
        """
        if not self.vivo:
            return self.soporte.v
        self.nacer()

        precios = {s: v[-1].cierre for s, v in velas.items() if v}
        abiertas = [s for s, p in self.cartera.posiciones.items() if p.abierta]
        # Una posición cuyo precio no ha llegado no se puede valorar ni vender:
        # se deja quieta y se avisa, en vez de inventarse un número.
        for s in abiertas:
            if s not in precios:
                self.diario.anota("aviso", simbolo=s, motivo="sin precio en este latido")
        marcables = {s: precios[s] for s in abiertas if s in precios}
        equity = self.cartera.caja + sum(
            self.cartera.posicion(s).valor(p) for s, p in marcables.items())

        if self.soporte.puede_operar(equity):
            self._operar(velas, precios, candidatos or [], equity)

        # Una cartera llena de acciones y sin efectivo no se muere de hambre:
        # vende algo y paga. Dejarla morir sería premiar a la estrategia que
        # menos invierte, que es justo lo contrario de lo que se quiere medir.
        self._asegurar_caja(precios)
        self.cartera.cobrar_coste_vida(self.cfg.coste_vida_por_tick)

        abiertas = [s for s, p in self.cartera.posiciones.items() if p.abierta]
        marcables = {s: precios[s] for s in abiertas if s in precios}
        equity = self.cartera.caja + sum(
            self.cartera.posicion(s).valor(p) for s, p in marcables.items())
        self.curva_equity.append(equity)
        v = self.soporte.latir(equity, self.cartera.caja)

        if not v.vivo:
            self._liquidar(precios)
            equity = self.cartera.equity({s: precios[s] for s in precios})
            self.curva_equity[-1] = equity
            v.equity = equity
            self.diario.anota("muerte", causa=v.causa_muerte, detalle=v.detalle_muerte,
                              equity=equity, ticks=v.ticks)
        return v

    # --------------------------------------------------------------- interna
    def _deseo(self, simbolo: str, velas, equity: float) -> Optional[float]:
        """Lo que la estrategia querría de ESE valor, como si fuera el único."""
        e = self._estrategia(simbolo)
        if len(velas) < e.velas_minimas:
            return None
        ctx = Contexto(simbolo, list(velas), self.cartera, equity, self.soporte.v.ticks)
        return e.objetivo(ctx)

    def _operar(self, velas: Dict[str, Sequence[Vela]], precios: Dict[str, float],
                candidatos: List[str], equity: float) -> None:
        abiertas = [s for s, p in self.cartera.posiciones.items() if p.abierta]

        # --- 1. ¿Quién se queda? Se sale por perder la tendencia, no por bajar
        #        puestos en el ranking: rotar por orden es pagar por reordenar.
        deseos: Dict[str, Optional[float]] = {}
        for s in abiertas:
            if s not in velas:
                continue
            d = self._deseo(s, velas[s], equity)
            deseos[s] = d
            if d is not None and d <= 0:
                self._ajustar(s, 0.0, precios[s], velas[s][-1].ts, equity)

        siguen = [s for s, p in self.cartera.posiciones.items() if p.abierta]

        # --- 2. Huecos libres, para los mejores candidatos que digan que sí ---
        huecos = self.max_posiciones - len(siguen)
        nuevos = []
        for s in candidatos:
            if huecos <= 0:
                break
            if s in siguen or s not in velas:
                continue
            d = self._deseo(s, velas[s], equity)
            if d is not None and d > 0:
                deseos[s] = d
                nuevos.append(s)
                huecos -= 1

        # --- 3. Repartir ---------------------------------------------------
        ocupadas = siguen + nuevos
        if not ocupadas:
            return
        n = len(ocupadas)

        # Una cartera que invierte el 95% se queda sin caja para pagar el coste
        # de existir y muere de inanición: una muerte de contabilidad, no de
        # mercado. Se aparta un año de costes antes de repartir.
        reserva = self.cfg.coste_vida_por_tick * self.cfg.ticks_por_anio
        margen = min(0.10, (reserva / equity) if equity > 0 else 0.0)
        tope = (self.cfg.reglas_riesgo.max_exposicion * (1 - margen)) / n

        # La banda de rebalanceo estaba pensada para una sola posición: es una
        # fracción de TODA la cartera. Con N posiciones, cada hueco vale 1/N, y
        # si el hueco es menor que la banda no se emite ni una orden — con 30
        # posiciones el bot se quedaba paralizado sin comprar nada. Se escala.
        banda = self.riesgo.reglas.banda_rebalanceo
        original = banda
        self.riesgo.reglas.banda_rebalanceo = banda / n
        try:
            for s in ocupadas:
                d = deseos.get(s)
                if d is None:
                    continue                  # «no opino»: se deja como está
                self._ajustar(s, min(tope, tope * d), precios[s],
                              velas[s][-1].ts, equity)
        finally:
            self.riesgo.reglas.banda_rebalanceo = original

    def _ajustar(self, simbolo: str, objetivo: float, precio: float, ts: int,
                 equity: float) -> None:
        for orden in self.riesgo.ordenes(simbolo, objetivo, precio, self.cartera, equity):
            self._ejecutar(orden, precio, ts)

    def _ejecutar(self, orden: Orden, precio: float, ts: int) -> None:
        antes = self.cartera.pnl_realizado
        ej = self.broker.ejecutar(orden, precio, ts, self.cartera)
        if not ej.aceptada or ej.cantidad <= 0:
            if ej.rechazo:
                self.diario.anota("rechazo", simbolo=orden.simbolo,
                                  lado=orden.lado, motivo=ej.rechazo)
            return
        realizado = (self.cartera.pnl_realizado - antes) if orden.lado == VENTA else None
        reg = {"ts": ts, "simbolo": orden.simbolo, "lado": orden.lado,
               "cantidad": ej.cantidad, "precio": ej.precio, "comision": ej.comision,
               "motivo": orden.motivo, "realizado": realizado}
        self.operaciones.append(reg)
        self.diario.anota("operacion", **reg)

    def _asegurar_caja(self, precios: Dict[str, float]) -> None:
        """Si no hay efectivo para seguir existiendo, recorta la mayor posición.

        La reserva objetivo es un año de coste de vida. Se vende de la posición
        más grande porque es la que menos se desequilibra al recortarla.
        """
        reserva = self.cfg.coste_vida_por_tick * self.cfg.ticks_por_anio
        if self.cartera.caja >= reserva:
            return
        falta = reserva - self.cartera.caja
        candidatas = [(self.cartera.posicion(s).valor(p), s)
                      for s, p in precios.items()
                      if self.cartera.posicion(s).abierta]
        if not candidatas:
            return
        valor, simbolo = max(candidatas)
        if valor <= 0:
            return
        precio = precios[simbolo]
        # Un poco de más, para no repetir la operación en el latido siguiente.
        cantidad = min(self.cartera.posicion(simbolo).cantidad,
                       (falta * 1.5) / precio)
        if cantidad * precio < 1e-6:
            return
        self._ejecutar(Orden(simbolo, VENTA, cantidad, "reponer caja para el coste de vida"),
                       precio, int(time.time()))

    def _liquidar(self, precios: Dict[str, float]) -> None:
        """Al morir se cierra todo lo que se pueda valorar."""
        for s, pos in list(self.cartera.posiciones.items()):
            if pos.abierta and s in precios:
                self.broker.ejecutar(Orden(s, VENTA, pos.cantidad,
                                           "liquidación por muerte"),
                                     precios[s], int(time.time()), self.cartera)

    # ------------------------------------------------------------ resultados
    def resumen(self) -> dict:
        from .metricas import resumen as calc
        m = calc(self.curva_equity or [self.cartera.capital_inicial],
                 self.cfg.ticks_por_anio, self.operaciones)
        v = self.soporte.v
        m.update({"estrategia": self.cfg.estrategia, "cartera": True,
                  "max_posiciones": self.max_posiciones,
                  "intervalo": self.cfg.intervalo, "vivo": v.vivo,
                  "causa_muerte": v.causa_muerte, "detalle_muerte": v.detalle_muerte,
                  "ticks_vividos": v.ticks,
                  "comisiones": self.cartera.comisiones_pagadas,
                  "coste_vida": self.cartera.coste_vida_pagado,
                  "umbral_ruina": self.soporte.nivel_ruina})
        return m

    def guardar(self, ruta) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        estado = {
            "config": {**{k: v for k, v in asdict(self.cfg).items()
                          if k not in ("reglas_vida", "reglas_riesgo")},
                       "reglas_vida": asdict(self.cfg.reglas_vida),
                       "reglas_riesgo": asdict(self.cfg.reglas_riesgo)},
            "cartera": self.cartera.a_dict(),
            "vitales": asdict(self.soporte.v),
            "max_posiciones": self.max_posiciones,
            "curva_equity": self.curva_equity[-5000:],
            "operaciones": self.operaciones[-2000:],
            "guardado": time.time(),
        }
        ruta.write_text(json.dumps(estado, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return ruta


def cargar_cartera(ruta) -> Optional[tuple]:
    """Devuelve (Cartera, Vitales, config, curva, operaciones, max_posiciones)."""
    ruta = Path(ruta)
    if not ruta.exists():
        return None
    try:
        d = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return (Cartera.de_dict(d["cartera"]), Vitales(**d["vitales"]),
            d.get("config", {}), d.get("curva_equity", []),
            d.get("operaciones", []), int(d.get("max_posiciones", 5)))
