"""Cartera: caja, posiciones y valoración a mercado.

Es la única fuente de verdad sobre "cuánto dinero tiene vivo el agente".
No decide nada: sólo contabiliza. Las decisiones están en las estrategias
y las reglas de vida/muerte en `vida.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Optional


@dataclass
class Posicion:
    simbolo: str
    cantidad: float = 0.0
    precio_medio: float = 0.0          # coste medio de adquisición
    maximo_favorable: float = 0.0      # para trailing stop

    @property
    def abierta(self) -> bool:
        return self.cantidad > 1e-12

    def valor(self, precio: float) -> float:
        return self.cantidad * precio

    def pnl_no_realizado(self, precio: float) -> float:
        return (precio - self.precio_medio) * self.cantidad


@dataclass
class Cartera:
    """Cartera long-only al contado (sin apalancamiento ni cortos).

    Decisión de diseño: sin apalancamiento el equity nunca puede ser
    negativo, así que "morir al llegar a cero" se define como caer por
    debajo de un umbral de ruina, no como equity < 0 literal.
    Ver `vida.py`.
    """
    divisa: str = "EUR"
    caja: float = 0.0
    capital_inicial: float = 0.0
    posiciones: Dict[str, Posicion] = field(default_factory=dict)

    # contabilidad acumulada
    pnl_realizado: float = 0.0
    comisiones_pagadas: float = 0.0
    coste_vida_pagado: float = 0.0
    operaciones: int = 0

    @classmethod
    def nueva(cls, capital: float, divisa: str = "EUR") -> "Cartera":
        if capital <= 0:
            raise ValueError("El capital inicial debe ser > 0")
        return cls(divisa=divisa, caja=capital, capital_inicial=capital)

    # ---------------------------------------------------------------- lectura
    def posicion(self, simbolo: str) -> Posicion:
        return self.posiciones.setdefault(simbolo, Posicion(simbolo))

    def valor_posiciones(self, precios: Dict[str, float]) -> float:
        total = 0.0
        for simbolo, pos in self.posiciones.items():
            if pos.abierta:
                precio = precios.get(simbolo)
                if precio is None:
                    raise KeyError(f"Falta precio de marcado para {simbolo}")
                total += pos.valor(precio)
        return total

    def equity(self, precios: Dict[str, float]) -> float:
        """Patrimonio total: caja + posiciones valoradas a mercado."""
        return self.caja + self.valor_posiciones(precios)

    def expuesto(self, precios: Dict[str, float]) -> float:
        """Fracción del equity que está en riesgo de mercado (0..1)."""
        eq = self.equity(precios)
        return 0.0 if eq <= 0 else self.valor_posiciones(precios) / eq

    # -------------------------------------------------------------- escritura
    def aplicar_compra(self, simbolo: str, cantidad: float, precio: float,
                       comision: float) -> None:
        coste = cantidad * precio + comision
        if coste > self.caja + 1e-9:
            raise ValueError(
                f"Caja insuficiente: necesita {coste:.2f}, tiene {self.caja:.2f}")
        pos = self.posicion(simbolo)
        nuevo_total = pos.cantidad + cantidad
        pos.precio_medio = (
            (pos.precio_medio * pos.cantidad + precio * cantidad) / nuevo_total
        )
        pos.cantidad = nuevo_total
        pos.maximo_favorable = max(pos.maximo_favorable, precio)
        self.caja -= coste
        self.comisiones_pagadas += comision
        self.operaciones += 1

    def aplicar_venta(self, simbolo: str, cantidad: float, precio: float,
                      comision: float) -> float:
        pos = self.posicion(simbolo)
        if cantidad > pos.cantidad + 1e-12:
            raise ValueError(
                f"No se puede vender {cantidad} de {simbolo}: sólo hay {pos.cantidad}")
        ingreso = cantidad * precio - comision
        realizado = (precio - pos.precio_medio) * cantidad - comision
        pos.cantidad -= cantidad
        if not pos.abierta:
            pos.cantidad = 0.0
            pos.precio_medio = 0.0
            pos.maximo_favorable = 0.0
        self.caja += ingreso
        self.pnl_realizado += realizado
        self.comisiones_pagadas += comision
        self.operaciones += 1
        return realizado

    def cobrar_coste_vida(self, importe: float) -> None:
        """El agente paga por existir (infraestructura, datos, custodia).

        Es lo que hace que "no hacer nada" tampoco sea gratis: sin esto,
        un agente pasivo sería inmortal y el objetivo perdería sentido.
        """
        if importe <= 0:
            return
        self.caja -= importe
        self.coste_vida_pagado += importe

    # ------------------------------------------------------------ persistencia
    def a_dict(self) -> dict:
        d = asdict(self)
        d["posiciones"] = {k: asdict(v) for k, v in self.posiciones.items()}
        return d

    @classmethod
    def de_dict(cls, d: dict) -> "Cartera":
        posiciones = {k: Posicion(**v) for k, v in d.get("posiciones", {}).items()}
        return cls(
            divisa=d.get("divisa", "EUR"),
            caja=d["caja"],
            capital_inicial=d["capital_inicial"],
            posiciones=posiciones,
            pnl_realizado=d.get("pnl_realizado", 0.0),
            comisiones_pagadas=d.get("comisiones_pagadas", 0.0),
            coste_vida_pagado=d.get("coste_vida_pagado", 0.0),
            operaciones=d.get("operaciones", 0),
        )
