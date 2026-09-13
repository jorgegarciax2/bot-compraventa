"""Filtros externos: lo que la estrategia no puede ver desde el precio.

Una estrategia sólo recibe velas. Los fundamentales y las noticias vienen de
fuera, cambian a otro ritmo y no tienen sentido dentro del bucle de precios:
las cuentas de una empresa son las mismas durante tres meses.

Por eso no se meten en la estrategia, se envuelven alrededor. La estrategia
sigue siendo una función pura del precio, comparable con las demás, y el filtro
se limita a dos vetos:

* **Cuentas malas** → fuera del valor, se cierre lo que haya.
* **Revuelo de noticias** → no se abre ni se amplía, pero sí se puede cerrar.
  Cuando pasa algo y no sabes qué, esperar es barato y adivinar no.
"""
from __future__ import annotations

from typing import Optional

from .base import Contexto, Estrategia


class ConFiltroExterno(Estrategia):
    """Envuelve una estrategia y le aplica los vetos de fuera."""

    def __init__(self, interna: Estrategia, calidad_ok: bool = True,
                 permitir_abrir: bool = True, motivo: str = "") -> None:
        self.interna = interna
        self.calidad_ok = calidad_ok
        self.permitir_abrir = permitir_abrir
        self.motivo = motivo
        self.nombre = interna.nombre
        self.params = dict(getattr(interna, "params", {}))
        self.velas_minimas = interna.velas_minimas

    def objetivo(self, ctx: Contexto) -> Optional[float]:
        if not self.calidad_ok:
            return 0.0                       # cuentas malas: no se opera el valor

        deseo = self.interna.objetivo(ctx)
        if deseo is None or self.permitir_abrir:
            return deseo

        # Con revuelo sólo se permite ir a menos, nunca a más.
        return min(deseo, ctx.exposicion)

    def describe(self) -> str:
        base = self.interna.describe()
        return f"{base} + filtro externo" if self.motivo else base
