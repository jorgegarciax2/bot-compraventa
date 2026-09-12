#!/usr/bin/env python3
"""Un latido del agente. Lo ejecuta GitHub Actions una vez por hora.

En el panel local el agente es un proceso que vive y respira solo. Aquí no hay
proceso que dure: cada ejecución carga su estado del repositorio, da UN tick y
lo vuelve a guardar. Es el mismo motor y las mismas reglas — lo único que cambia
es quién lleva el reloj.

    python github/latido.py [--config configuracion.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agente-cartera"))

from agente.core.broker import BrokerPapel, CostesMercado          # noqa: E402
from agente.core.datos import fuente_por_nombre                    # noqa: E402
from agente.core.diario import Diario                              # noqa: E402
from agente.core.motor import Agente, Config, cargar_estado        # noqa: E402
from agente.core.riesgo import ReglasRiesgo                        # noqa: E402
from agente.core.vida import ReglasVida, escribir_lapida, leer_lapida  # noqa: E402
from agente.estrategias.catalogo import crear                      # noqa: E402


def construir(c: dict) -> Config:
    return Config(
        capital=float(c["capital"]), divisa=c.get("divisa", "EUR"),
        simbolo=c["simbolo"], intervalo=c.get("intervalo", "1h"),
        coste_vida_anual=float(c.get("coste_vida_anual", 0.02)),
        estrategia=c.get("estrategia", "tendencia_vol"),
        params_estrategia=c.get("params_estrategia") or {},
        reglas_vida=ReglasVida(ruina_relativa=float(c.get("ruina_relativa", 0.10)),
                               max_drawdown=float(c.get("max_drawdown", 0.50))),
        reglas_riesgo=ReglasRiesgo(max_exposicion=float(c.get("max_exposicion", 0.95)),
                                   stop_loss=float(c.get("stop_loss", 0.15)),
                                   trailing_stop=float(c.get("trailing_stop", 0.25)),
                                   banda_rebalanceo=float(c.get("banda_rebalanceo", 0.10))),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Un latido del agente")
    ap.add_argument("--config", default=str(RAIZ / "configuracion.json"))
    a = ap.parse_args()

    c = json.loads(Path(a.config).read_text(encoding="utf-8"))
    destino = RAIZ / "estado" / c.get("nombre", "btc")
    destino.mkdir(parents=True, exist_ok=True)

    lapida = leer_lapida(destino / "LAPIDA.json")
    if lapida:
        v = lapida["vitales"]
        print(f"El agente está muerto (causa: {v['causa_muerte']}). {v.get('detalle_muerte','')}")
        print("La muerte es definitiva. Para empezar otro, borra la carpeta "
              f"{destino.relative_to(RAIZ)} y cambia el nombre en la configuración.")
        return 0                      # no es un fallo: es su final

    if c.get("pausado"):
        print("Pausado por configuración (pausado: true). No opero.")
        return 0

    cfg = construir(c)
    estrategia = crear(cfg.estrategia, **cfg.params_estrategia)

    # --- datos -----------------------------------------------------------
    fuente = fuente_por_nombre(c.get("fuente", "yahoo"))
    necesarias = max(300, estrategia.velas_minimas + 5)
    velas = fuente.historico(cfg.simbolo, cfg.intervalo, necesarias)
    if len(velas) < estrategia.velas_minimas:
        print(f"Sólo {len(velas)} velas y la estrategia necesita "
              f"{estrategia.velas_minimas}. No opero todavía.")
        return 0
    print(f"{len(velas)} velas de {cfg.simbolo} ({cfg.intervalo}) · "
          f"último cierre {velas[-1].cierre:,.2f} {cfg.divisa}")

    # --- estado previo ----------------------------------------------------
    previo = cargar_estado(destino / "estado.json")
    cartera = vitales = None
    curva, ops = [], []
    if previo:
        cartera, vitales, _, curva, ops = previo
        print(f"Reanudo: {vitales.ticks} latidos, patrimonio "
              f"{vitales.equity:.2f} {cfg.divisa}")
    else:
        print(f"Nace con {cfg.capital:.2f} {cfg.divisa}")

    broker = BrokerPapel(CostesMercado(
        comision_bps=float(c.get("comision_bps", 10)),
        deslizamiento_bps=float(c.get("slippage_bps", 5)),
        minimo_operacion=float(c.get("minimo_operacion", 10))))

    diario = Diario(destino / "diario.jsonl", eco=True)
    ag = Agente(cfg, estrategia, broker, cartera=cartera, diario=diario, vitales=vitales)
    if previo:
        ag.curva_equity, ag.operaciones = curva, ops
        # Cada ejecución es un proceso nuevo, así que el agente cree que acaba de
        # nacer y lo anota otra vez. Nació una sola vez, hace horas o días.
        ag._nacido = True

    # --- el latido --------------------------------------------------------
    antes = len(ag.operaciones)
    v = ag.tick(velas)
    ag.guardar(destino / "estado.json")

    # La curva del agente son números sin fecha. Aquí sí sabemos cuándo ha
    # pasado cada cosa, así que se apunta aparte: de esto sale el gráfico.
    pos = ag.cartera.posicion(cfg.simbolo)
    with (destino / "serie.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": time.time(), "tick": v.ticks,
            "equity": round(v.equity, 6), "caja": round(ag.cartera.caja, 6),
            "cantidad": pos.cantidad, "precio": velas[-1].cierre,
            "drawdown": round(v.drawdown, 6),
        }) + "\n")

    nuevas = len(ag.operaciones) - antes
    print(f"Latido {v.ticks} · patrimonio {v.equity:,.2f} {cfg.divisa} "
          f"· caída {v.drawdown:.2%} · exposición "
          f"{ag.cartera.expuesto({cfg.simbolo: velas[-1].cierre}):.0%}"
          + (f" · {nuevas} operación(es)" if nuevas else ""))

    if not ag.vivo:
        r = ag.resumen()
        escribir_lapida(destino / "LAPIDA.json", v, r)
        print(f"\nMUERTE: {v.causa_muerte} — {v.detalle_muerte}")
    diario.cerrar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
