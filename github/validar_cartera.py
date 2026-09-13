#!/usr/bin/env python3
"""¿Llevar una cartera de N valores es mejor que llevar uno solo?

Compara, sobre el mismo periodo y con los mismos costes:

* carteras de 3, 5 y 8 posiciones que rotan según la señal,
* comprar y aguantar equiponderado sobre todo el universo,
* y un solo valor, que es lo que hacía el bot hasta ahora.

**Sesgo que no se puede eliminar del todo:** el universo son grandes empresas
que siguen cotizando hoy. Las que quebraron o fueron absorbidas no están, así
que el resultado de «comprar y aguantar» sale mejor de lo que habría sido en
vivo. La ordenación sí es honesta: se calcula con los datos disponibles en cada
momento, sin mirar hacia adelante.

    python github/validar_cartera.py [--dias 750] [--posiciones 3 5 8]
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agente-cartera"))

from agente.core.broker import BrokerPapel, CostesMercado                # noqa: E402
from agente.core.datos import fuente_por_nombre                          # noqa: E402
from agente.core.motor import Agente, Config                             # noqa: E402
from agente.core.multi import AgenteCartera                              # noqa: E402
from agente.core.riesgo import ReglasRiesgo                              # noqa: E402
from agente.core.vida import ReglasVida                                  # noqa: E402
from agente.core import indicadores as ind                               # noqa: E402
from agente.estrategias.catalogo import crear                            # noqa: E402

# Grandes empresas de sectores distintos. No es «el mercado», pero tampoco es
# una lista de ganadores: hay varias que lo han hecho mal estos años.
UNIVERSO = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "JPM", "BAC",
            "WMT", "KO", "PEP", "JNJ", "PFE", "MRK", "XOM", "CVX", "CAT",
            "BA", "DIS", "NKE", "MCD", "HD", "VZ", "T", "CSCO", "INTC",
            "IBM", "GE", "F", "GM"]


def config(capital: float, estrategia: str) -> Config:
    return Config(capital=capital, divisa="USD", simbolo="CARTERA", intervalo="1d",
                  coste_vida_anual=0.02, estrategia=estrategia,
                  reglas_vida=ReglasVida(ruina_relativa=0.10, max_drawdown=0.50),
                  reglas_riesgo=ReglasRiesgo())


def costes() -> BrokerPapel:
    return BrokerPapel(CostesMercado(comision_bps=10, deslizamiento_bps=5,
                                     minimo_operacion=10))


def impulso(cierres) -> float:
    """Despegue de la media larga, en volatilidades. Sólo con datos de hasta hoy."""
    lenta = ind.ema(cierres, 100)
    vol = ind.volatilidad(cierres, 48)
    if not lenta or not vol or lenta <= 0:
        return -99.0
    return ((cierres[-1] / lenta) - 1) / vol


def main() -> int:
    ap = argparse.ArgumentParser(description="Valida la cartera de varios valores")
    ap.add_argument("--dias", type=int, default=750)
    ap.add_argument("--posiciones", type=int, nargs="+", default=[3, 5, 8])
    ap.add_argument("--estrategia", default="estructura")
    ap.add_argument("--capital", type=float, default=1000.0)
    a = ap.parse_args()

    y = fuente_por_nombre("yahoo")
    print(f"Descargando {len(UNIVERSO)} valores…", file=sys.stderr)
    datos = {}
    for s in UNIVERSO:
        try:
            v = y.historico(s, "1d", a.dias + 200)
            if len(v) >= a.dias + 150:
                datos[s] = v[-(a.dias + 150):]
        except Exception:
            pass
        time.sleep(0.1)

    n = min(len(v) for v in datos.values())
    datos = {s: v[-n:] for s, v in datos.items()}
    calentamiento = 150
    pasos = n - calentamiento
    print(f"{len(datos)} valores · {n} sesiones · {pasos} de operativa\n")

    filas = []

    # ---- carteras de N posiciones -------------------------------------
    for k in a.posiciones:
        ag = AgenteCartera(config(a.capital, a.estrategia),
                           lambda: crear(a.estrategia), costes(), max_posiciones=k)
        with contextlib.redirect_stdout(io.StringIO()):
            for i in range(calentamiento, n):
                ventana = {s: v[:i + 1] for s, v in datos.items()}
                ranking = sorted(ventana, key=lambda s: -impulso([x.cierre for x in ventana[s]]))
                if not ag.vivo:
                    break
                ag.tick(ventana, ranking)
        r = ag.resumen()
        filas.append((f"cartera de {k}", r))

    # ---- comprar y aguantar equiponderado ------------------------------
    ag = AgenteCartera(config(a.capital, "comprar_y_aguantar"),
                       lambda: crear("comprar_y_aguantar"), costes(),
                       max_posiciones=len(datos))
    with contextlib.redirect_stdout(io.StringIO()):
        for i in range(calentamiento, n):
            ventana = {s: v[:i + 1] for s, v in datos.items()}
            if not ag.vivo:
                break
            ag.tick(ventana, sorted(ventana))
    filas.append((f"aguantar los {len(datos)}", ag.resumen()))

    # ---- un solo valor, como hasta ahora --------------------------------
    for s in ["MSFT", "INTC"]:
        if s not in datos:
            continue
        cfg = config(a.capital, a.estrategia)
        cfg.simbolo = s
        uno = Agente(cfg, crear(a.estrategia), costes())
        with contextlib.redirect_stdout(io.StringIO()):
            uno.vivir(datos[s], calentamiento=calentamiento)
        filas.append((f"sólo {s}", uno.resumen()))

    cab = (f"{'estrategia':<22}{'final':>10}{'retorno':>10}{'CAGR':>9}"
           f"{'máxDD':>9}{'Sharpe':>8}{'ops':>6}{'comis.':>9}  estado")
    print(cab + "\n" + "-" * len(cab))
    for nombre, r in filas:
        estado = "vivo" if r["vivo"] else f"† {r['causa_muerte']}"
        print(f"{nombre:<22}{r['equity_final']:>10.2f}{r['retorno_total']*100:>9.1f}%"
              f"{r['cagr']*100:>8.1f}%{r['max_drawdown']*100:>8.1f}%{r['sharpe']:>8.2f}"
              f"{r['operaciones_cerradas']:>6}{r['comisiones']:>9.2f}  {estado}")
    print("\nEl universo son empresas que siguen cotizando hoy: «aguantar» sale")
    print("mejor de lo que habría salido en vivo. La ordenación sí es honesta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
