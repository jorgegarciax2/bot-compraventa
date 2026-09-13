#!/usr/bin/env python3
"""Rastrea cientos de empresas buscando oportunidades.

Dos pasos, porque las dos fuentes van a velocidades muy distintas:

1. **Las cuentas de todo el mercado**, de la SEC, en cuatro peticiones. Cambian
   cada trimestre, así que se piden una vez y valen para días.
2. **El precio de las que sobreviven al filtro**, de Yahoo, una petición por
   empresa. Esto sí cambia cada día y es lo que marca el ritmo.

Sobre el orden del resultado, conviene ser claro: **no es una predicción**. Es un
filtro (fuera las que pierden dinero o están muy endeudadas, fuera las que no
están en tendencia) y una ordenación por una medida simple y explicable — cuánto
se ha despegado el precio de su media larga, medido en volatilidades. Nadie ha
demostrado que esa ordenación anticipe nada; sirve para no mirar 4.000 empresas
a mano, no para saber cuál subirá.

    python github/explorador.py [--minimo-ingresos 2e9] [--maximo 200]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agente-cartera"))

from agente.core import estructura as est                          # noqa: E402
from agente.core import fundamentales as fun                       # noqa: E402
from agente.core import indicadores as ind                         # noqa: E402
from agente.core.datos import fuente_por_nombre                    # noqa: E402

CACHE = RAIZ / "estado" / "_cache"
SALIDA = RAIZ / "estado" / "_explorador"


def tecnico(velas) -> dict | None:
    """Lo que dice el precio de una empresa. None si no hay histórico bastante."""
    if len(velas) < 120:
        return None
    c = [v.cierre for v in velas]
    mx = [v.maximo for v in velas]
    mn = [v.minimo for v in velas]
    vol = [v.volumen for v in velas]

    rapida, lenta = ind.ema(c, 20), ind.ema(c, 100)
    if rapida is None or lenta is None or lenta <= 0:
        return None
    volat = ind.volatilidad(c, 48) or 0.0
    # Despegue de la media larga medido en volatilidades: comparable entre
    # empresas tranquilas y nerviosas, que es justo lo que hace falta para
    # ordenar una lista mezclada.
    impulso = ((c[-1] / lenta) - 1) / volat if volat > 0 else 0.0

    sop, res = est.soportes_resistencias(mx, mn, c[-1], k=5, tolerancia=0.015,
                                         minimos_toques=2)
    return {
        "precio": c[-1],
        "tendencia": rapida > lenta,
        "adx": ind.adx(mx, mn, c, 14),
        "rsi": ind.rsi(c, 14),
        "impulso": impulso,
        "volatilidad": volat,
        "volumen_relativo": ind.volumen_relativo(vol, 20),
        "obv_acompana": ind.obv_acompana(c, vol, 20),
        "soporte": sop[0][0] if sop else None,
        "resistencia": res[0][0] if res else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Busca oportunidades en todo el mercado")
    ap.add_argument("--anio", type=int, default=datetime.now().year - 2,
                    help="ejercicio fiscal completo del que hay cuentas")
    ap.add_argument("--minimo-ingresos", type=float, default=2e9,
                    help="descarta empresas menores: sin liquidez no hay operativa")
    ap.add_argument("--maximo", type=int, default=200,
                    help="cuántas mirar con detalle (una petición de precio cada una)")
    ap.add_argument("--adx-minimo", type=float, default=20.0)
    a = ap.parse_args()

    SALIDA.mkdir(parents=True, exist_ok=True)
    print(f"Descargando las cuentas del mercado (ejercicio {a.anio})…")
    universo = fun.universo(a.anio, CACHE)
    print(f"  {len(universo):,} empresas con ticker y cuentas")

    grandes = [e for e in universo if (e.get("ingresos") or 0) >= a.minimo_ingresos]
    aptas = [e for e in grandes
             if fun.calidad({**e, "bpa": None, "per": None})[0]]
    aptas.sort(key=lambda x: -(x["ingresos"] or 0))
    candidatas = aptas[:a.maximo]
    print(f"  {len(grandes):,} con ingresos > {a.minimo_ingresos/1e9:.0f} B$")
    print(f"  {len(aptas):,} con cuentas sanas · miro el precio de las {len(candidatas)} mayores\n")

    y = fuente_por_nombre("yahoo")
    analizadas, fallos = [], 0
    for i, e in enumerate(candidatas, 1):
        try:
            velas = y.historico(e["ticker"], "1d", 400)
            t = tecnico(velas)
            if t:
                analizadas.append({**e, **t})
        except Exception:
            fallos += 1
        if i % 25 == 0:
            print(f"  {i}/{len(candidatas)} · {len(analizadas)} con datos", flush=True)
        time.sleep(0.12)                      # cortesía con Yahoo

    print(f"\n{len(analizadas)} empresas analizadas ({fallos} sin datos de precio)")

    # El filtro técnico: sólo lo que está en tendencia de verdad y no reventado.
    oportunidades = [
        e for e in analizadas
        if e["tendencia"] and (e["adx"] or 0) >= a.adx_minimo
        and (e["rsi"] or 100) < 75 and e["obv_acompana"] is not False
    ]
    oportunidades.sort(key=lambda x: -x["impulso"])
    print(f"{len(oportunidades)} pasan también el filtro técnico\n")

    cab = f"{'#':>3} {'ticker':<7}{'empresa':<30}{'impulso':>9}{'ADX':>6}{'RSI':>6}{'margen':>9}{'crec.':>8}"
    print(cab + "\n" + "-" * len(cab))
    for n, e in enumerate(oportunidades[:15], 1):
        pc = lambda v: f"{v*100:>7.1f}%" if v is not None else "      —"
        print(f"{n:>3} {e['ticker']:<7}{(e['empresa'] or '')[:29]:<30}{e['impulso']:>9.2f}"
              f"{e['adx'] or 0:>6.0f}{e['rsi'] or 0:>6.0f}{pc(e['margen_neto'])}{pc(e['crecimiento_ingresos'])}")

    (SALIDA / "oportunidades.json").write_text(json.dumps({
        "generado": time.time(),
        "ejercicio": a.anio,
        "universo": len(universo),
        "grandes": len(grandes),
        "aptas": len(aptas),
        "analizadas": len(analizadas),
        "oportunidades": oportunidades[:60],
        "criterio": {"minimo_ingresos": a.minimo_ingresos, "adx_minimo": a.adx_minimo,
                     "maximo": a.maximo},
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nGuardado en {SALIDA.relative_to(RAIZ)}/oportunidades.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
