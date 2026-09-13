#!/usr/bin/env python3
"""Validación por ventanas: ¿la estrategia funciona, o tuvo suerte?

Un backtest largo da UN número, y un número no distingue una estrategia buena de
una que acertó una vez. Esto parte el histórico en ventanas consecutivas y mide
cada estrategia en todas ellas, sobre varios activos.

Lo que importa no es la mejor ventana: es la mediana, cuántas veces bate a
comprar y aguantar, y sobre todo **la peor**. Una estrategia que gana mucho de
media y te arruina una vez de cada seis no es operable.

    python github/validar.py [--intervalo 4h] [--ventanas 6] [--dias 90]
"""
from __future__ import annotations

import argparse
import contextlib
import io
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agente-cartera"))

from agente.core.broker import BrokerPapel, CostesMercado          # noqa: E402
from agente.core.datos import fuente_por_nombre                    # noqa: E402
from agente.core.motor import Agente, Config                       # noqa: E402
from agente.core.riesgo import ReglasRiesgo                        # noqa: E402
from agente.core.vida import ReglasVida                            # noqa: E402
from agente.estrategias.catalogo import CATALOGO, crear            # noqa: E402

ACTIVOS = ["BTCEUR", "ETHEUR", "SOLEUR", "XRPEUR", "BNBEUR"]
POR_DIA = {"1h": 24, "4h": 6, "1d": 1}


def correr(velas, estrategia: str, intervalo: str) -> dict:
    cfg = Config(capital=1000.0, divisa="EUR", simbolo="X", intervalo=intervalo,
                 coste_vida_anual=0.02, estrategia=estrategia,
                 reglas_vida=ReglasVida(ruina_relativa=0.10, max_drawdown=0.50),
                 reglas_riesgo=ReglasRiesgo())
    ag = Agente(cfg, crear(estrategia),
                BrokerPapel(CostesMercado(comision_bps=10, deslizamiento_bps=5,
                                          minimo_operacion=10)))
    with contextlib.redirect_stdout(io.StringIO()):
        ag.vivir(velas)
    return ag.resumen()


def main() -> int:
    ap = argparse.ArgumentParser(description="Validación por ventanas")
    ap.add_argument("--intervalo", default="4h", choices=sorted(POR_DIA))
    ap.add_argument("--ventanas", type=int, default=6)
    ap.add_argument("--dias", type=int, default=90, help="días por ventana")
    ap.add_argument("--activos", nargs="+", default=ACTIVOS)
    ap.add_argument("--fuente", default="binance", choices=["binance", "yahoo"])
    a = ap.parse_args()

    por_ventana = a.dias * POR_DIA[a.intervalo]
    # Cada ventana necesita calentamiento: las estrategias lentas piden ~100 velas.
    calentamiento = 150
    total = a.ventanas * por_ventana + calentamiento

    f = fuente_por_nombre(a.fuente)
    print(f"Validación · {a.intervalo} · {a.ventanas} ventanas de {a.dias} días "
          f"· {len(a.activos)} activos · 1.000 EUR por prueba\n")

    datos = {}
    for s in a.activos:
        v = f.historico(s, a.intervalo, total)
        datos[s] = v
        print(f"  {s}: {len(v)} velas", file=sys.stderr)

    estrategias = sorted(CATALOGO)
    resultados = {e: [] for e in estrategias}
    muertes = {e: 0 for e in estrategias}
    gana_a_aguantar = {e: 0 for e in estrategias}
    pruebas = 0

    for simbolo, velas in datos.items():
        for w in range(a.ventanas):
            fin = len(velas) - (a.ventanas - 1 - w) * por_ventana
            ini = max(0, fin - por_ventana - calentamiento)
            trozo = velas[ini:fin]
            if len(trozo) < calentamiento + 30:
                continue
            pruebas += 1
            ref = correr(trozo, "comprar_y_aguantar", a.intervalo)["retorno_total"]
            for e in estrategias:
                r = correr(trozo, e, a.intervalo)
                resultados[e].append(r["retorno_total"])
                muertes[e] += (not r["vivo"])
                gana_a_aguantar[e] += (r["retorno_total"] > ref)

    print(f"\n{pruebas} pruebas por estrategia "
          f"({len(datos)} activos × {a.ventanas} ventanas)\n")
    cab = (f"{'estrategia':<20}{'mediana':>10}{'media':>10}{'mejor':>10}"
           f"{'PEOR':>10}{'>0':>7}{'>B&H':>7}{'muertes':>9}")
    print(cab + "\n" + "-" * len(cab))

    orden = sorted(estrategias, key=lambda e: -statistics.median(resultados[e]))
    for e in orden:
        r = resultados[e]
        pos = sum(1 for x in r if x > 0)
        print(f"{e:<20}{statistics.median(r)*100:>9.1f}%{statistics.fmean(r)*100:>9.1f}%"
              f"{max(r)*100:>9.1f}%{min(r)*100:>9.1f}%"
              f"{pos:>4}/{len(r)}{gana_a_aguantar[e]:>4}/{len(r)}{muertes[e]:>9}")

    print("\nLa columna que decide es PEOR, no mejor: es lo que te puede pasar.")
    print("«>B&H» = veces que batió a comprar y aguantar en esa misma ventana.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
