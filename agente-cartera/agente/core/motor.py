"""El agente: nace con un capital, opera, y muere solo si se arruina.

Un solo bucle sirve para backtest (velas históricas de golpe) y para
operativa en vivo en papel (una vela nueva cada N minutos). Es el mismo
código, lo que evita el clásico "en backtest iba bien".
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..estrategias.base import Contexto, Estrategia
from .broker import Broker, BrokerPapel, COMPRA, VENTA
from .cartera import Cartera
from .datos import Vela
from .diario import Diario
from .riesgo import GestorRiesgo, ReglasRiesgo
from .vida import (CausaMuerte, ReglasVida, SoporteVital, Vitales,
                   escribir_lapida, leer_lapida)

TICKS_POR_ANIO = {"1m": 525_600, "5m": 105_120, "15m": 35_040, "30m": 17_520,
                  "1h": 8_760, "4h": 2_190, "1d": 365, "1w": 52}


@dataclass
class Config:
    capital: float = 1_000.0
    divisa: str = "EUR"
    simbolo: str = "BTCEUR"
    intervalo: str = "1h"
    coste_vida_anual: float = 0.02   # 2 % del capital inicial al año, por existir
    estrategia: str = "tendencia_vol"
    params_estrategia: Dict = field(default_factory=dict)
    reglas_vida: ReglasVida = field(default_factory=ReglasVida)
    reglas_riesgo: ReglasRiesgo = field(default_factory=ReglasRiesgo)

    @property
    def ticks_por_anio(self) -> float:
        return TICKS_POR_ANIO.get(self.intervalo, 8_760)

    @property
    def coste_vida_por_tick(self) -> float:
        return self.capital * self.coste_vida_anual / self.ticks_por_anio


class Agente:
    """Nace, respira una vez por vela, y en algún momento muere."""

    def __init__(self, config: Config, estrategia: Estrategia,
                 broker: Optional[Broker] = None,
                 cartera: Optional[Cartera] = None,
                 diario: Optional[Diario] = None,
                 vitales: Optional[Vitales] = None) -> None:
        self.cfg = config
        self.estrategia = estrategia
        self.broker = broker or BrokerPapel()
        self.cartera = cartera or Cartera.nueva(config.capital, config.divisa)
        self.riesgo = GestorRiesgo(config.reglas_riesgo)
        self.soporte = SoporteVital(config.reglas_vida,
                                    self.cartera.capital_inicial, vitales)
        self.diario = diario or Diario(None)
        self.curva_equity: List[float] = []
        self.operaciones: List[dict] = []
        self._nacido = False

    # ------------------------------------------------------------ nacimiento
    def nacer(self) -> None:
        if self._nacido:
            return
        self._nacido = True
        self.diario.anota("nacimiento", capital=self.cartera.capital_inicial,
                          divisa=self.cfg.divisa, simbolo=self.cfg.simbolo,
                          estrategia=self.estrategia.describe(),
                          umbral_ruina=self.soporte.nivel_ruina)

    @property
    def vivo(self) -> bool:
        return self.soporte.vivo

    # ------------------------------------------------------------------ tick
    def tick(self, velas: Sequence[Vela]) -> Vitales:
        """Un latido: valorar, decidir, ejecutar, pagar por existir, revisar vitales."""
        if not self.vivo:
            return self.soporte.v
        self.nacer()

        vela = velas[-1]
        precios = {self.cfg.simbolo: vela.cierre}
        equity = self.cartera.equity(precios)

        # 1. decidir (sólo si tiene histórico suficiente y puede operar)
        if (len(velas) >= self.estrategia.velas_minimas
                and self.soporte.puede_operar(equity)):
            ctx = Contexto(self.cfg.simbolo, list(velas), self.cartera, equity,
                           self.soporte.v.ticks)
            objetivo = self.estrategia.objetivo(ctx)
            ordenes = self.riesgo.ordenes(self.cfg.simbolo, objetivo,
                                          vela.cierre, self.cartera, equity)
            for orden in ordenes:
                self._ejecutar(orden, vela)

        # 2. pagar el coste de existir
        self.cartera.cobrar_coste_vida(self.cfg.coste_vida_por_tick)

        # 3. revisar si sigue vivo
        equity = self.cartera.equity(precios)
        self.curva_equity.append(equity)
        v = self.soporte.latir(equity, self.cartera.caja)

        if not v.vivo:
            self._liquidar(vela)
            equity = self.cartera.equity(precios)
            self.curva_equity[-1] = equity
            v.equity = equity
            self.diario.anota("muerte", causa=v.causa_muerte,
                              detalle=v.detalle_muerte, equity=equity,
                              ticks=v.ticks)
        return v

    def _ejecutar(self, orden, vela: Vela) -> None:
        antes = self.cartera.pnl_realizado
        ej = self.broker.ejecutar(orden, vela.cierre, vela.ts, self.cartera)
        if not ej.aceptada or ej.cantidad <= 0:
            if ej.rechazo:
                self.diario.anota("rechazo", simbolo=orden.simbolo,
                                  lado=orden.lado, motivo=ej.rechazo)
            return
        realizado = (self.cartera.pnl_realizado - antes) if orden.lado == VENTA else None
        reg = {"ts": vela.ts, "simbolo": orden.simbolo, "lado": orden.lado,
               "cantidad": ej.cantidad, "precio": ej.precio,
               "comision": ej.comision, "motivo": orden.motivo,
               "realizado": realizado}
        self.operaciones.append(reg)
        self.diario.anota("operacion", **reg)

    def _liquidar(self, vela: Vela) -> None:
        """Al morir, cierra todo a mercado: la lápida lleva un número real."""
        pos = self.cartera.posicion(self.cfg.simbolo)
        if pos.abierta:
            from .broker import Orden
            self.broker.ejecutar(Orden(self.cfg.simbolo, VENTA, pos.cantidad,
                                       "liquidación por muerte"),
                                 vela.cierre, vela.ts, self.cartera)

    # ------------------------------------------------------------- ejecución
    def vivir(self, velas: Sequence[Vela], calentamiento: Optional[int] = None) -> Vitales:
        """Backtest: recorre el histórico vela a vela hasta el final o la muerte."""
        calentamiento = calentamiento or max(1, self.estrategia.velas_minimas)
        for i in range(calentamiento, len(velas) + 1):
            if not self.vivo:
                break
            self.tick(velas[:i])
        return self.soporte.v

    # ------------------------------------------------------------ resultados
    def resumen(self) -> dict:
        from .metricas import resumen as calc
        m = calc(self.curva_equity or [self.cartera.capital_inicial],
                 self.cfg.ticks_por_anio, self.operaciones)
        v = self.soporte.v
        m.update({
            "estrategia": self.estrategia.describe(),
            "simbolo": self.cfg.simbolo,
            "intervalo": self.cfg.intervalo,
            "vivo": v.vivo,
            "causa_muerte": v.causa_muerte,
            "detalle_muerte": v.detalle_muerte,
            "ticks_vividos": v.ticks,
            "comisiones": self.cartera.comisiones_pagadas,
            "coste_vida": self.cartera.coste_vida_pagado,
            "umbral_ruina": self.soporte.nivel_ruina,
        })
        return m

    # ----------------------------------------------------------- persistencia
    def guardar(self, ruta: str | Path) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        estado = {
            "config": {**{k: v for k, v in asdict(self.cfg).items()
                          if k not in ("reglas_vida", "reglas_riesgo")},
                       "reglas_vida": asdict(self.cfg.reglas_vida),
                       "reglas_riesgo": asdict(self.cfg.reglas_riesgo)},
            "cartera": self.cartera.a_dict(),
            "vitales": asdict(self.soporte.v),
            "curva_equity": self.curva_equity[-5000:],
            "operaciones": self.operaciones[-2000:],
            "guardado": time.time(),
        }
        ruta.write_text(json.dumps(estado, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return ruta


def cargar_estado(ruta: str | Path):
    """Devuelve (Cartera, Vitales, dict_config) o None si no hay estado."""
    ruta = Path(ruta)
    if not ruta.exists():
        return None
    d = json.loads(ruta.read_text(encoding="utf-8"))
    return (Cartera.de_dict(d["cartera"]),
            Vitales(**d["vitales"]),
            d.get("config", {}),
            d.get("curva_equity", []),
            d.get("operaciones", []))
