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
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agente-cartera"))

from agente.core.broker import BrokerPapel, CostesMercado          # noqa: E402
from agente.core.datos import Remuestreada, fuente_por_nombre      # noqa: E402
from agente.core.diario import Diario                              # noqa: E402
from agente.core.motor import Agente, Config, cargar_estado        # noqa: E402
from agente.core.riesgo import ReglasRiesgo                        # noqa: E402
from agente.core.vida import ReglasVida, escribir_lapida, leer_lapida  # noqa: E402
from agente.core import fundamentales as fun                       # noqa: E402
from agente.core import noticias as news                           # noqa: E402
from agente.estrategias.catalogo import crear                      # noqa: E402
from agente.estrategias.filtros import ConFiltroExterno            # noqa: E402

CACHE = RAIZ / "estado" / "_cache"


def avisar_a_actions(latio: bool) -> None:
    """Le dice al flujo si ha pasado algo. Sin esto regeneraría el tablero y
    haría un commit cada vez que el cron despierta, aunque no hubiera latido."""
    destino = os.environ.get("GITHUB_OUTPUT")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(f"latio={'true' if latio else 'false'}\n")


def contexto_externo(c: dict, destino: Path, precio: float) -> dict:
    """Lo que no se ve en el precio: las cuentas de la empresa y el ruido.

    Ninguno de los dos es una señal de compra. Las cuentas dicen si el valor
    merece operarse siquiera; el ruido, si conviene esperar a que se aclare.
    Y los dos fallan hacia el lado seguro: si la fuente no responde, no vetan.
    """
    fuera = {"calidad_ok": True, "permitir_abrir": True, "motivos": []}

    if c.get("fundamentales"):
        try:
            m = fun.metricas(c["simbolo"], CACHE, precio=precio)
            ok, motivos = fun.calidad(m)
            fuera["fundamentales"] = m
            fuera["calidad_ok"] = ok
            fuera["motivos"] += motivos
            print(f"Cuentas: {'OK' if ok else 'NO'} — {', '.join(motivos)}")
        except Exception as e:
            print(f"No he podido leer la SEC ({type(e).__name__}); no veto por eso.")

    if c.get("noticias"):
        try:
            titulares = news.titulares(c["simbolo"], 25)
            pulso = news.pulso(titulares, 24)
            historial = json.loads((destino / "pulso.json").read_text(encoding="utf-8")) \
                if (destino / "pulso.json").exists() else []
            rep = news.repunte(pulso, historial)
            historial = (historial + [pulso])[-200:]
            (destino / "pulso.json").write_text(json.dumps(historial), encoding="utf-8")
            fuera["titulares"] = titulares[:12]
            fuera["repunte"] = rep
            if rep and rep["hay_revuelo"]:
                fuera["permitir_abrir"] = False
                fuera["motivos"].append(f"revuelo de noticias ({rep['razon']}x)")
                print(f"Revuelo: {pulso} titulares frente a {rep['normal']} habituales "
                      f"({rep['razon']}x). No abro posiciones nuevas.")
            else:
                print(f"Noticias: {pulso} en 24 h"
                      + (f" (normal {rep['normal']})" if rep else " (aún sin baremo)"))
        except Exception as e:
            print(f"No he podido leer las noticias ({type(e).__name__}); sigo igual.")

    return fuera


def leer_marca(ruta: Path):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


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


def latir(c: dict) -> bool:
    """Un latido de UN agente. Devuelve si de verdad ha latido."""
    nombre = c.get("nombre", "agente")
    destino = RAIZ / "estado" / nombre
    destino.mkdir(parents=True, exist_ok=True)
    print(f"\n=== {nombre} · {c['simbolo']} {c.get('intervalo','1d')} "
          f"· {c.get('estrategia')} ===")

    lapida = leer_lapida(destino / "LAPIDA.json")
    if lapida:
        v = lapida["vitales"]
        print(f"Muerto (causa: {v['causa_muerte']}). {v.get('detalle_muerte','')}")
        return False
    if c.get("pausado"):
        print("Pausado por configuración.")
        return False

    cfg = construir(c)
    base = crear(cfg.estrategia, **cfg.params_estrategia)

    fuente = fuente_por_nombre(c.get("fuente", "yahoo"))
    origen = c.get("remuestrear_desde")
    if origen and origen != cfg.intervalo:
        fuente = Remuestreada(fuente, origen)
    velas = fuente.historico(cfg.simbolo, cfg.intervalo, max(300, base.velas_minimas + 5))
    if len(velas) < base.velas_minimas:
        print(f"Sólo {len(velas)} velas y hacen falta {base.velas_minimas}.")
        return False
    print(f"{len(velas)} velas · último cierre {velas[-1].cierre:,.2f} {cfg.divisa}")

    marca = destino / "ultima_vela.json"
    if (leer_marca(marca) or {}).get("ts") == velas[-1].ts and not c.get("forzar_latido"):
        from datetime import datetime, timezone
        abre = datetime.fromtimestamp(velas[-1].ts, timezone.utc)
        print(f"Sin vela nueva (la actual abrió a las {abre:%H:%M} UTC). No late.")
        return False

    externo = contexto_externo(c, destino, velas[-1].cierre)
    estrategia = ConFiltroExterno(base, externo["calidad_ok"],
                                  externo["permitir_abrir"],
                                  ", ".join(externo["motivos"]))
    (destino / "externo.json").write_text(
        json.dumps(externo, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    previo = cargar_estado(destino / "estado.json")
    cartera = vitales = None
    curva, ops = [], []
    if previo:
        cartera, vitales, _, curva, ops = previo
        print(f"Reanudo: {vitales.ticks} latidos, {vitales.equity:.2f} {cfg.divisa}")
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
        ag._nacido = True

    antes = len(ag.operaciones)
    v = ag.tick(velas)
    ag.guardar(destino / "estado.json")

    pos = ag.cartera.posicion(cfg.simbolo)
    with (destino / "serie.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": time.time(), "tick": v.ticks, "equity": round(v.equity, 6),
            "caja": round(ag.cartera.caja, 6), "cantidad": pos.cantidad,
            "precio": velas[-1].cierre, "drawdown": round(v.drawdown, 6),
        }) + "\n")

    nuevas = len(ag.operaciones) - antes
    print(f"Latido {v.ticks} · {v.equity:,.2f} {cfg.divisa} · caída {v.drawdown:.2%}"
          f" · exposición {ag.cartera.expuesto({cfg.simbolo: velas[-1].cierre}):.0%}"
          + (f" · {nuevas} operación(es)" if nuevas else ""))

    if not ag.vivo:
        escribir_lapida(destino / "LAPIDA.json", v, ag.resumen())
        print(f"MUERTE: {v.causa_muerte} — {v.detalle_muerte}")
    marca.write_text(json.dumps({"ts": velas[-1].ts, "intervalo": cfg.intervalo}),
                     encoding="utf-8")
    diario.cerrar()
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Un latido de cada agente")
    ap.add_argument("--config", default=str(RAIZ / "configuracion.json"))
    ap.add_argument("--solo", help="latir sólo este agente, por nombre")
    a = ap.parse_args()

    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    agentes = cfg.get("agentes") or [cfg]      # admite el formato antiguo de un agente
    if a.solo:
        agentes = [x for x in agentes if x.get("nombre") == a.solo]
        if not agentes:
            print(f"No hay ningún agente llamado «{a.solo}».", file=sys.stderr)
            return 1

    algo = False
    for c in agentes:
        try:
            algo = latir(c) or algo
        except Exception as e:
            # Que un agente falle no debe dejar a los demás sin latir.
            print(f"ERROR en {c.get('nombre')}: {type(e).__name__}: {e}", file=sys.stderr)

    avisar_a_actions(algo)
    if not algo:
        print("\nNingún agente ha latido en esta pasada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
