"""Ciclo de vida del agente: cuándo sigue vivo y cuándo muere.

El agente es mortal por diseño. Muere solo, sin intervención, y la muerte
es *irreversible*: deja una lápida en disco y cualquier arranque posterior
sobre ese mismo estado se niega a operar.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


class CausaMuerte:
    RUINA = "ruina"                     # el equity cayó al umbral de ruina
    DRAWDOWN = "drawdown_maximo"        # perdió más del X% desde su máximo
    INANICION = "inanicion"             # sin caja para pagar el coste de vida
    POLVO = "polvo"                     # equity por debajo del mínimo operable
    EDAD = "edad_maxima"                # fin del horizonte configurado
    MANUAL = "parada_manual"


@dataclass
class ReglasVida:
    """Condiciones de supervivencia. Todas se evalúan en cada tick."""
    umbral_ruina: float = 0.0        # muere si equity <= este valor absoluto
    ruina_relativa: float = 0.10     # ...o si equity <= 10% del capital inicial
    max_drawdown: float = 0.50       # muere si pierde >50% desde su máximo
    equity_minimo_operable: float = 10.0  # por debajo no puede ni operar
    edad_maxima_ticks: Optional[int] = None

    def valida(self) -> None:
        if not 0 < self.max_drawdown <= 1:
            raise ValueError("max_drawdown debe estar en (0, 1]")
        if not 0 <= self.ruina_relativa < 1:
            raise ValueError("ruina_relativa debe estar en [0, 1)")


@dataclass
class Vitales:
    """Estado vital del agente en un instante."""
    vivo: bool = True
    ticks: int = 0
    equity: float = 0.0
    equity_maximo: float = 0.0
    drawdown: float = 0.0
    causa_muerte: Optional[str] = None
    detalle_muerte: Optional[str] = None
    ts_muerte: Optional[float] = None


class SoporteVital:
    """Evalúa las reglas de vida y mata al agente cuando toca."""

    def __init__(self, reglas: ReglasVida, capital_inicial: float,
                 vitales: Optional[Vitales] = None) -> None:
        reglas.valida()
        self.reglas = reglas
        self.capital_inicial = capital_inicial
        self.v = vitales or Vitales(equity=capital_inicial,
                                    equity_maximo=capital_inicial)

    # ------------------------------------------------------------------ ruina
    @property
    def nivel_ruina(self) -> float:
        """Equity por debajo del cual el agente se considera arruinado."""
        return max(self.reglas.umbral_ruina,
                   self.capital_inicial * self.reglas.ruina_relativa)

    @property
    def vivo(self) -> bool:
        return self.v.vivo

    def puede_operar(self, equity: float) -> bool:
        return self.v.vivo and equity >= self.reglas.equity_minimo_operable

    # ------------------------------------------------------------------- tick
    def latir(self, equity: float, caja: float) -> Vitales:
        """Actualiza los vitales con el equity actual y decide si muere."""
        if not self.v.vivo:
            return self.v

        self.v.ticks += 1
        self.v.equity = equity
        self.v.equity_maximo = max(self.v.equity_maximo, equity)
        self.v.drawdown = (
            0.0 if self.v.equity_maximo <= 0
            else 1.0 - equity / self.v.equity_maximo
        )

        if caja < 0:
            return self._morir(CausaMuerte.INANICION,
                               f"caja negativa ({caja:.2f}): no puede pagar el "
                               f"coste de vida")
        if equity <= self.nivel_ruina:
            return self._morir(CausaMuerte.RUINA,
                               f"equity {equity:.2f} <= umbral de ruina "
                               f"{self.nivel_ruina:.2f}")
        if equity < self.reglas.equity_minimo_operable:
            return self._morir(CausaMuerte.POLVO,
                               f"equity {equity:.2f} por debajo del mínimo "
                               f"operable {self.reglas.equity_minimo_operable:.2f}")
        if self.v.drawdown >= self.reglas.max_drawdown:
            return self._morir(CausaMuerte.DRAWDOWN,
                               f"drawdown {self.v.drawdown:.1%} >= límite "
                               f"{self.reglas.max_drawdown:.1%}")
        if (self.reglas.edad_maxima_ticks is not None
                and self.v.ticks >= self.reglas.edad_maxima_ticks):
            return self._morir(CausaMuerte.EDAD,
                               f"alcanzó {self.v.ticks} ticks de vida")
        return self.v

    def matar(self, causa: str = CausaMuerte.MANUAL, detalle: str = "") -> Vitales:
        return self._morir(causa, detalle)

    def _morir(self, causa: str, detalle: str) -> Vitales:
        self.v.vivo = False
        self.v.causa_muerte = causa
        self.v.detalle_muerte = detalle
        self.v.ts_muerte = time.time()
        return self.v


# ---------------------------------------------------------------------- lápida
def escribir_lapida(ruta: Path, vitales: Vitales, resumen: dict) -> Path:
    """Deja constancia irreversible de la muerte del agente."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(
        {"vitales": asdict(vitales), "resumen": resumen},
        indent=2, ensure_ascii=False), encoding="utf-8")
    return ruta


def leer_lapida(ruta: Path) -> Optional[dict]:
    ruta = Path(ruta)
    if not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
