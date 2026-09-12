"""Interfaz de línea de comandos del agente.

    python -m agente backtest   --simbolo BTCEUR --capital 1000
    python -m agente torneo     --simbolo BTCEUR --capital 1000
    python -m agente papel      --simbolo BTCEUR --capital 1000   (opera en vivo, sin dinero)
    python -m agente estado     --dir ejecuciones/mi-agente
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .core.broker import BrokerPapel, CostesMercado
from .core.cartera import Cartera
from .core.datos import Vela, fuente_por_nombre, guardar_csv
from .core.diario import Diario
from .core.metricas import formatea
from .core.motor import Agente, Config, TICKS_POR_ANIO, cargar_estado
from .core.riesgo import ReglasRiesgo
from .core.vida import ReglasVida, Vitales, escribir_lapida, leer_lapida
from .estrategias.catalogo import CATALOGO, crear

SEGUNDOS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600,
            "4h": 14400, "1d": 86400}


# --------------------------------------------------------------------- utils
def _config(a) -> Config:
    return Config(
        capital=a.capital, divisa=a.divisa, simbolo=a.simbolo,
        intervalo=a.intervalo, coste_vida_anual=a.coste_vida,
        estrategia=a.estrategia,
        params_estrategia=json.loads(a.params) if a.params else {},
        reglas_vida=ReglasVida(ruina_relativa=a.ruina, max_drawdown=a.max_dd),
        reglas_riesgo=ReglasRiesgo(max_exposicion=a.max_exposicion,
                                   stop_loss=a.stop_loss,
                                   trailing_stop=a.trailing_stop,
                                   banda_rebalanceo=a.banda),
    )


def _broker(a) -> BrokerPapel:
    return BrokerPapel(CostesMercado(comision_bps=a.comision_bps,
                                     deslizamiento_bps=a.slippage_bps,
                                     minimo_operacion=a.minimo_operacion))


def _velas(a) -> list:
    if a.fuente == "sintetica":
        f = fuente_por_nombre("sintetica", semilla=a.semilla)
    elif a.fuente == "csv":
        f = fuente_por_nombre("csv", ruta=a.csv)
    else:
        f = fuente_por_nombre(a.fuente)
    print(f"Descargando {a.velas} velas de {a.simbolo} ({a.intervalo}) "
          f"desde {a.fuente}…", file=sys.stderr)
    velas = f.historico(a.simbolo, a.intervalo, a.velas)
    if not velas:
        sys.exit("No se han obtenido velas. Revisa símbolo/intervalo/fuente.")
    print(f"  {len(velas)} velas | {time.strftime('%Y-%m-%d', time.gmtime(velas[0].ts))}"
          f" → {time.strftime('%Y-%m-%d', time.gmtime(velas[-1].ts))}", file=sys.stderr)
    return velas


def _epitafio(a: Agente) -> str:
    v = a.soporte.v
    if v.vivo:
        return (f"SIGUE VIVO tras {v.ticks} ticks — equity "
                f"{v.equity:.2f} {a.cfg.divisa} (ruina en "
                f"{a.soporte.nivel_ruina:.2f})")
    return (f"MUERTO en el tick {v.ticks} — causa: {v.causa_muerte}. "
            f"{v.detalle_muerte}")


# ----------------------------------------------------------------- backtest
def cmd_backtest(a) -> int:
    velas = _velas(a)
    cfg = _config(a)
    salida = Path(a.dir) if a.dir else None
    diario = Diario(salida / "diario.jsonl" if salida else None, eco=a.verboso)
    ag = Agente(cfg, crear(a.estrategia, **cfg.params_estrategia), _broker(a),
                diario=diario)
    ag.vivir(velas)
    r = ag.resumen()

    print(f"\n=== {ag.estrategia.describe()} sobre {a.simbolo} {a.intervalo} ===")
    print(formatea(r, cfg.divisa))
    print(f"  Comisiones          {r['comisiones']:>10.2f} {cfg.divisa}")
    print(f"  Coste de vida       {r['coste_vida']:>10.2f} {cfg.divisa}")
    print(f"\n  → {_epitafio(ag)}")

    if salida:
        ag.guardar(salida / "estado.json")
        (salida / "resumen.json").write_text(
            json.dumps(r, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        guardar_csv(velas, salida / "velas.csv")
        if not ag.vivo:
            escribir_lapida(salida / "LAPIDA.json", ag.soporte.v, r)
        print(f"\n  Resultados en {salida}/")
    diario.cerrar()
    return 0


# ------------------------------------------------------------------- torneo
def cmd_torneo(a) -> int:
    velas = _velas(a)
    filas = []
    for nombre in sorted(CATALOGO):
        cfg = _config(a)
        cfg.estrategia = nombre
        ag = Agente(cfg, crear(nombre), _broker(a))
        ag.vivir(velas)
        r = ag.resumen()
        filas.append((nombre, r, ag))

    filas.sort(key=lambda x: x[1]["equity_final"], reverse=True)
    cab = (f"{'estrategia':<22}{'final':>11}{'retorno':>10}{'CAGR':>9}"
           f"{'máxDD':>9}{'Sharpe':>8}{'ops':>6}  estado")
    print(f"\n=== Torneo · {a.simbolo} {a.intervalo} · {a.capital:.0f} "
          f"{a.divisa} ===\n{cab}\n{'-' * len(cab)}")
    for nombre, r, ag in filas:
        estado = "vivo" if r["vivo"] else f"† {r['causa_muerte']}"
        print(f"{nombre:<22}{r['equity_final']:>11.2f}"
              f"{r['retorno_total'] * 100:>9.1f}%{r['cagr'] * 100:>8.1f}%"
              f"{r['max_drawdown'] * 100:>8.1f}%{r['sharpe']:>8.2f}"
              f"{r['operaciones_cerradas']:>6}  {estado}")
    if a.dir:
        salida = Path(a.dir)
        salida.mkdir(parents=True, exist_ok=True)
        datos = {n: {"resumen": r, "curva": ag.curva_equity}
                 for n, r, ag in filas}
        (salida / "torneo.json").write_text(
            json.dumps(datos, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        guardar_csv(velas, salida / "velas.csv")
        print(f"\n  Resultados en {salida}/torneo.json")
    return 0


# -------------------------------------------------------------------- papel
def cmd_papel(a) -> int:
    """Operativa en vivo con dinero simulado. Reanudable y mortal."""
    salida = Path(a.dir)
    salida.mkdir(parents=True, exist_ok=True)
    lapida = leer_lapida(salida / "LAPIDA.json")
    if lapida and not a.reencarnar:
        v = lapida["vitales"]
        print(f"Este agente está muerto (causa: {v['causa_muerte']}).\n"
              f"{v['detalle_muerte']}\n"
              f"La muerte es definitiva: usa --reencarnar para empezar uno nuevo "
              f"desde cero en otro directorio, o borra {salida}/LAPIDA.json "
              f"si sabes lo que haces.")
        return 1
    if a.reencarnar:
        for f in ("LAPIDA.json", "estado.json"):
            (salida / f).unlink(missing_ok=True)

    cfg = _config(a)
    estado = cargar_estado(salida / "estado.json")
    cartera = vitales = None
    if estado:
        cartera, vitales, _, curva, ops = estado
        print(f"Reanudando agente: equity previo {vitales.equity:.2f} "
              f"{cfg.divisa}, {vitales.ticks} ticks vividos.")

    # En modo ensayo (--fuente sintetica/csv) el "vivo" se simula avanzando
    # una vela por iteración: sirve para probar el bucle completo sin red.
    ensayo = a.fuente in ("sintetica", "csv")
    if ensayo:
        f = (fuente_por_nombre("csv", ruta=a.csv) if a.fuente == "csv"
             else fuente_por_nombre("sintetica", semilla=a.semilla))
        historia = f.historico(a.simbolo, a.intervalo, a.velas)
        print(f"[ensayo] {len(historia)} velas simuladas, "
              f"{a.paso_seg}s por vela — sin red y sin dinero.")
    else:
        fuente = fuente_por_nombre(a.fuente)
    diario = Diario(salida / "diario.jsonl", eco=True)
    ag = Agente(cfg, crear(a.estrategia, **cfg.params_estrategia), _broker(a),
                cartera=cartera, diario=diario, vitales=vitales)
    if estado:
        ag.curva_equity, ag.operaciones = curva, ops

    espera = SEGUNDOS.get(a.intervalo, 3600)
    print(f"Agente en papel sobre {a.simbolo} {a.intervalo}. "
          f"Ruina en {ag.soporte.nivel_ruina:.2f} {cfg.divisa}. "
          f"Ctrl-C para pausar (no mata al agente).")
    ultimo_ts = 0
    cursor = max(2, ag.estrategia.velas_minimas)
    try:
        while ag.vivo:
            if ensayo:
                if cursor > len(historia):
                    print("[ensayo] se acabaron las velas; el agente sigue vivo.")
                    break
                velas = historia[:cursor]
                cursor += 1
            else:
                try:
                    velas = fuente.historico(
                        a.simbolo, a.intervalo,
                        max(300, ag.estrategia.velas_minimas + 5))
                except Exception as e:                 # red caída: reintenta
                    print(f"  ! error de datos: {e}; reintento en 60 s")
                    time.sleep(60)
                    continue
            if velas and velas[-1].ts != ultimo_ts:
                ultimo_ts = velas[-1].ts
                v = ag.tick(velas)
                print(f"[{time.strftime('%H:%M:%S')}] tick {v.ticks} | "
                      f"precio {velas[-1].cierre:.4f} | equity {v.equity:.2f} "
                      f"{cfg.divisa} | dd {v.drawdown:.1%} | "
                      f"exp {ag.cartera.expuesto({a.simbolo: velas[-1].cierre}):.0%}")
                ag.guardar(salida / "estado.json")
            if a.max_ticks and ag.soporte.v.ticks >= a.max_ticks:
                print(f"Alcanzado el límite de {a.max_ticks} ticks. "
                      f"El agente sigue vivo y su estado queda guardado.")
                break
            time.sleep(a.paso_seg if ensayo else min(espera, 60))
    except KeyboardInterrupt:
        print("\nPausado. El agente sigue vivo; vuelve a lanzar el comando "
              "para continuar donde lo dejó.")
    finally:
        ag.guardar(salida / "estado.json")
        if not ag.vivo:
            r = ag.resumen()
            escribir_lapida(salida / "LAPIDA.json", ag.soporte.v, r)
            print(f"\n{_epitafio(ag)}")
            print(formatea(r, cfg.divisa))
        diario.cerrar()
    return 0



# --------------------------------------------------------------- cementerio
def cmd_cementerio(a) -> int:
    """Suelta N agentes idénticos en N mercados distintos y cuenta cadáveres.

    Es la prueba de que la mortalidad no es decorativa: con una estrategia
    mala, la mayoría muere; con una razonable, la mayoría sobrevive. Un único
    backtest afortunado no dice nada; esto sí.
    """
    from collections import Counter
    from .core.datos import Sintetica

    estrategias = ([a.estrategia] if a.estrategia != "todas" else sorted(CATALOGO))
    print(f"\nSoltando {a.agentes} agentes por estrategia en {a.agentes} "
          f"mercados distintos ({a.velas} velas cada uno)…\n")
    cab = (f"{'estrategia':<22}{'vivos':>7}{'muertos':>9}{'mediana':>10}"
           f"{'peor':>9}{'mejor':>10}  causas de muerte")
    print(cab + "\n" + "-" * (len(cab) + 20))

    for nombre in estrategias:
        finales, causas = [], Counter()
        for semilla in range(a.agentes):
            velas = Sintetica(semilla=semilla + a.semilla).historico(
                "SINT", a.intervalo, a.velas)
            cfg = _config(a)
            cfg.simbolo, cfg.estrategia = "SINT", nombre
            ag = Agente(cfg, crear(nombre), _broker(a))
            ag.vivir(velas)
            r = ag.resumen()
            finales.append(r["equity_final"])
            if not r["vivo"]:
                causas[r["causa_muerte"]] += 1
        finales.sort()
        muertos = sum(causas.values())
        mediana = finales[len(finales) // 2]
        detalle = ", ".join(f"{c}×{n}" for c, n in causas.most_common()) or "—"
        print(f"{nombre:<22}{a.agentes - muertos:>7}{muertos:>9}"
              f"{mediana:>10.0f}{finales[0]:>9.0f}{finales[-1]:>10.0f}  {detalle}")
    print(f"\n  (capital inicial {a.capital:.0f} {a.divisa}; "
          f"ruina por debajo de {a.capital * a.ruina:.0f})")
    return 0


# ------------------------------------------------------------------- estado
def cmd_estado(a) -> int:
    salida = Path(a.dir)
    lap = leer_lapida(salida / "LAPIDA.json")
    if lap:
        v = lap["vitales"]
        print(f"† Agente muerto — causa: {v['causa_muerte']}\n"
              f"  {v['detalle_muerte']}\n"
              f"  Vivió {v['ticks']} ticks. Equity final "
              f"{lap['resumen'].get('equity_final', 0):.2f}")
        print(formatea(lap["resumen"]))
        return 0
    est = cargar_estado(salida / "estado.json")
    if not est:
        print(f"No hay ningún agente en {salida}")
        return 1
    cartera, vit, cfg, curva, ops = est
    print(f"● Agente vivo — {vit.ticks} ticks\n"
          f"  Equity      {vit.equity:.2f} {cartera.divisa}\n"
          f"  Caja        {cartera.caja:.2f}\n"
          f"  Drawdown    {vit.drawdown:.1%}\n"
          f"  Operaciones {cartera.operaciones}\n"
          f"  Comisiones  {cartera.comisiones_pagadas:.2f}")
    return 0


# --------------------------------------------------------------------- args
def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agente",
        description="Agente autónomo que intenta multiplicar una cartera "
                    "y muere solo si se arruina.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def comunes(s, con_dir_obligatorio=False):
        s.add_argument("--capital", type=float, default=1000.0)
        s.add_argument("--divisa", default="EUR")
        s.add_argument("--simbolo", default="BTCEUR")
        s.add_argument("--intervalo", default="1h", choices=sorted(TICKS_POR_ANIO))
        s.add_argument("--fuente", default="binance",
                       choices=["binance", "yahoo", "sintetica", "csv"])
        s.add_argument("--csv", help="ruta del CSV si --fuente csv")
        s.add_argument("--semilla", type=int, default=7, help="para --fuente sintetica")
        s.add_argument("--velas", type=int, default=2000)
        s.add_argument("--estrategia", default="tendencia_vol",
                       choices=sorted(CATALOGO) + ["todas"])
        s.add_argument("--params", help='JSON con parámetros, p.ej. \'{"rapida":10}\'')
        # vida
        s.add_argument("--ruina", type=float, default=0.10,
                       help="muere si el equity cae a esta fracción del capital")
        s.add_argument("--max-dd", dest="max_dd", type=float, default=0.50)
        # riesgo
        s.add_argument("--max-exposicion", type=float, default=0.95)
        s.add_argument("--stop-loss", type=float, default=0.15)
        s.add_argument("--trailing-stop", type=float, default=0.25)
        s.add_argument("--banda", type=float, default=0.10)
        # costes
        s.add_argument("--comision-bps", type=float, default=10.0)
        s.add_argument("--slippage-bps", type=float, default=5.0)
        s.add_argument("--minimo-operacion", type=float, default=10.0)
        s.add_argument("--coste-vida", type=float, default=0.02,
                       help="coste anual de existir, como fracción del capital")
        s.add_argument("--dir", required=con_dir_obligatorio,
                       help="carpeta donde guardar estado, diario y lápida")

    b = sub.add_parser("backtest", help="probar una estrategia sobre histórico")
    comunes(b)
    b.add_argument("--verboso", action="store_true")
    b.set_defaults(func=cmd_backtest)

    t = sub.add_parser("torneo", help="comparar todas las estrategias")
    comunes(t)
    t.set_defaults(func=cmd_torneo)

    pa = sub.add_parser("papel", help="operar en vivo con dinero simulado")
    comunes(pa, con_dir_obligatorio=True)
    pa.add_argument("--max-ticks", type=int, default=0)
    pa.add_argument("--paso-seg", type=float, default=1.0,
                    help="segundos por vela en modo ensayo (--fuente sintetica)")
    pa.add_argument("--reencarnar", action="store_true",
                    help="borra la lápida y empieza un agente nuevo")
    pa.set_defaults(func=cmd_papel)

    c = sub.add_parser("cementerio",
                       help="soltar N agentes en N mercados y contar supervivientes")
    comunes(c)
    c.add_argument("--agentes", type=int, default=30)
    c.set_defaults(func=cmd_cementerio, fuente="sintetica")

    e = sub.add_parser("estado", help="ver si el agente vive y cómo va")
    e.add_argument("--dir", required=True)
    e.set_defaults(func=cmd_estado)
    return p


def main(argv=None) -> int:
    a = construir_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
