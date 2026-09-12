#!/usr/bin/env python3
"""Genera docs/index.html: el tablero que GitHub Pages publica.

Sin servidor y sin JavaScript. El gráfico se dibuja aquí, en Python, y sale
como SVG dentro del propio HTML: así la página es un fichero suelto que se ve
igual en cualquier sitio, hoy y dentro de un año.
"""
from __future__ import annotations

import html
import json
import math
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

ANCHO, ALTO = 900, 280
MARGEN = {"i": 70, "d": 16, "a": 14, "b": 26}


# ------------------------------------------------------------------ lectura
def leer_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def leer_jsonl(p: Path, ultimos: int | None = None) -> list:
    if not p.exists():
        return []
    fuera = []
    for linea in p.read_text(encoding="utf-8", errors="replace").splitlines():
        linea = linea.strip()
        if linea:
            try:
                fuera.append(json.loads(linea))
            except json.JSONDecodeError:
                pass
    return fuera[-ultimos:] if ultimos else fuera


# ------------------------------------------------------------------ formato
def eur(v, d=2):
    if v is None:
        return "—"
    s = f"{v:,.{d}f}"
    return s.replace(",", " ").replace(".", ",")


def firmado(v, d=2):
    r = round(v or 0.0, d) or 0.0
    return ("+" if r > 0 else "") + eur(r, d)


def pct(v, d=2):
    r = round((v or 0.0) * 100, d) or 0.0
    return f"{r:.{d}f} %"


def clase(v, umbral=0.005):
    return "pos" if v > umbral else "neg" if v < -umbral else "apagado"


# ------------------------------------------------------------------ gráfico
def svg_curva(serie: list, capital: float) -> str:
    if len(serie) < 2:
        return '<p class="nota">Aún no hay suficientes latidos para dibujar la curva.</p>'
    xs = [m["ts"] for m in serie]
    ys = [m["equity"] for m in serie]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys + [capital]), max(ys + [capital])
    margen = (y1 - y0) * 0.08 or max(abs(y1), 1.0) * 0.002
    a, b = y0 - margen, y1 + margen
    aw = ANCHO - MARGEN["i"] - MARGEN["d"]
    ah = ALTO - MARGEN["a"] - MARGEN["b"]

    tx = lambda t: MARGEN["i"] + (0 if x1 == x0 else (t - x0) / (x1 - x0)) * aw
    ty = lambda v: MARGEN["a"] + ah - (0.5 if b == a else (v - a) / (b - a)) * ah

    # Los decimales salen del PASO del eje, no del recorrido: con el patrimonio
    # casi plano, dos decimales hacen que las cinco marcas digan lo mismo.
    paso = (b - a) / 4 or 1.0
    dec = max(0, min(6, int(math.ceil(-math.log10(paso))) + 1))

    partes = []
    # rejilla
    for i in range(5):
        v = a + (b - a) * i / 4
        y = ty(v)
        partes.append(f'<line class="malla" x1="{MARGEN["i"]}" x2="{ANCHO-MARGEN["d"]}" y1="{y:.1f}" y2="{y:.1f}"/>')
        partes.append(f'<text class="eje" x="{MARGEN["i"]-8}" y="{y+3.5:.1f}" text-anchor="end">{eur(v, dec)}</text>')
    # eje de tiempo
    n = 5
    for i in range(n + 1):
        t = x0 + (x1 - x0) * i / n
        etiqueta = time.strftime("%d/%m %H:%M", time.localtime(t))
        anc = "start" if i == 0 else "end" if i == n else "middle"
        partes.append(f'<text class="eje" x="{tx(t):.1f}" y="{ALTO-7}" text-anchor="{anc}">{etiqueta}</text>')
    # capital inicial
    yc = ty(capital)
    partes.append(f'<line class="base" x1="{MARGEN["i"]}" x2="{ANCHO-MARGEN["d"]}" y1="{yc:.1f}" y2="{yc:.1f}"/>')
    # curva
    d = "".join(("L" if i else "M") + f"{tx(t):.1f} {ty(v):.1f}" for i, (t, v) in enumerate(zip(xs, ys)))
    color = "var(--verde)" if ys[-1] >= capital else "var(--rojo)"
    partes.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linejoin="round"/>')

    return (f'<svg viewBox="0 0 {ANCHO} {ALTO}" width="100%" role="img" '
            f'aria-label="Curva de patrimonio">{"".join(partes)}</svg>')


# ------------------------------------------------------------------- días
def por_dias(serie: list) -> list:
    dias = {}
    for m in serie:
        k = time.strftime("%Y-%m-%d", time.localtime(m["ts"]))
        d = dias.get(k)
        if d is None:
            dias[k] = {"dia": k, "cierre": m["equity"], "min": m["equity"],
                       "max": m["equity"], "t0": m["tick"], "t1": m["tick"]}
        else:
            d["cierre"] = m["equity"]
            d["min"] = min(d["min"], m["equity"])
            d["max"] = max(d["max"], m["equity"])
            d["t1"] = m["tick"]
    fuera, previo = [], None
    for k in sorted(dias):
        d = dias[k]
        base = previo if previo is not None else d["cierre"]
        d["pnl"] = d["cierre"] - base
        d["pnl_pct"] = (d["cierre"] / base - 1.0) if base else 0.0
        d["latidos"] = d["t1"] - d["t0"] + 1
        previo = d["cierre"]
        fuera.append(d)
    return fuera


LEGIBLE = {
    "nacimiento": lambda e: f"● nace con {eur(e.get('capital'))} {e.get('divisa','')} sobre {e.get('simbolo')} — {e.get('estrategia')}",
    "operacion": lambda e: f"{'▲' if e.get('lado')=='compra' else '▼'} {e.get('lado')} {eur(e.get('cantidad'),6)} @ {eur(e.get('precio'),4)} · {e.get('motivo','')}",
    "rechazo": lambda e: f"· orden rechazada ({e.get('lado')}): {e.get('motivo')}",
    "muerte": lambda e: f"✝ MUERTE [{e.get('causa')}] {e.get('detalle','')} · patrimonio final {eur(e.get('equity'))}",
}


def main() -> int:
    conf = leer_json(RAIZ / "configuracion.json") or {}
    nombre = conf.get("nombre", "btc")
    dst = RAIZ / "estado" / nombre

    est = leer_json(dst / "estado.json")
    lap = leer_json(dst / "LAPIDA.json")
    serie = leer_jsonl(dst / "serie.jsonl")
    eventos = leer_jsonl(dst / "diario.jsonl", 60)

    salida = RAIZ / "docs"
    salida.mkdir(exist_ok=True)

    if not est:
        (salida / "index.html").write_text(PLANTILLA.format(
            titulo="Bot de compraventa", cuerpo=
            '<section class="tarjeta"><h2>Todavía sin latidos</h2>'
            '<p class="nota">El bot aún no ha operado. El primer latido llega '
            'en la próxima hora en punto.</p></section>',
            pie=time.strftime("%d/%m/%Y %H:%M")), encoding="utf-8")
        print("Tablero generado (sin estado todavía).")
        return 0

    cart, vit, cfg = est["cartera"], est["vitales"], est.get("config", {})
    simbolo = cfg.get("simbolo", "?")
    divisa = cart.get("divisa", "EUR")
    capital = float(cart.get("capital_inicial") or 0)
    equity = float(vit.get("equity") or capital)
    caja = float(cart.get("caja") or 0)
    pos = (cart.get("posiciones") or {}).get(simbolo, {}) or {}
    cantidad = float(pos.get("cantidad") or 0)
    valor_pos = max(0.0, equity - caja)
    exposicion = (valor_pos / equity) if equity > 0 else 0.0
    pnl = equity - capital
    muerto = bool(lap) or not vit.get("vivo", True)

    dias = por_dias(serie)
    hoy = time.strftime("%Y-%m-%d")
    hoy_d = next((d for d in dias if d["dia"] == hoy), None)

    if muerto:
        causa = vit.get("causa_muerte") or (lap or {}).get("vitales", {}).get("causa_muerte")
        detalle = vit.get("detalle_muerte") or (lap or {}).get("vitales", {}).get("detalle_muerte", "")
        insignia = f'<span class="insignia muerto">† muerto</span> causa: <b>{html.escape(str(causa))}</b>. {html.escape(str(detalle))}'
    elif conf.get("pausado"):
        insignia = '<span class="insignia pausado">‖ pausado</span> no opera hasta que quites «pausado» de la configuración.'
    else:
        insignia = '<span class="insignia vivo">● en marcha</span> late una vez por hora.'

    ultimo = serie[-1]["ts"] if serie else None
    kpis = [
        ("Patrimonio", f"{eur(equity)} {divisa}", f"empezó con {eur(capital)}", clase(pnl)),
        ("Resultado total", f"{firmado(pnl)} {divisa}",
         f"{pct(pnl/capital if capital else 0)} desde el inicio", clase(pnl)),
        ("Hoy", f"{firmado(hoy_d['pnl'])} {divisa}" if hoy_d else "—",
         f"{pct(hoy_d['pnl_pct'])} · {hoy_d['latidos']} latidos" if hoy_d else "sin latidos hoy",
         clase(hoy_d["pnl"]) if hoy_d else "apagado"),
        ("Posición", f"{exposicion*100:.0f} % invertido" if cantidad > 1e-12 else "fuera",
         f"{eur(cantidad,6)} {simbolo} · medio {eur(pos.get('precio_medio'),2)}"
         if cantidad > 1e-12 else "todo en caja", ""),
        ("Caja", f"{eur(caja)} {divisa}",
         f"comisiones {eur(cart.get('comisiones_pagadas'))} · coste de vida {eur(cart.get('coste_vida_pagado'))}", ""),
        ("Caída desde máximo", pct(vit.get("drawdown")),
         f"muere al {pct(cfg.get('reglas_vida',{}).get('max_drawdown',0.5),0)}", 
         "neg" if float(vit.get("drawdown") or 0) > 0.0001 else "apagado"),
    ]
    html_kpis = "".join(
        f'<div class="kpi"><span class="kpi-t">{t}</span>'
        f'<span class="kpi-v {c}">{html.escape(v)}</span>'
        f'<span class="kpi-s">{html.escape(s)}</span></div>' for t, v, s, c in kpis)

    filas_dias = "".join(
        f'<tr><td>{d["dia"]}</td><td class="num">{eur(d["cierre"])}</td>'
        f'<td class="num {clase(d["pnl"])}">{firmado(d["pnl"])}</td>'
        f'<td class="num {clase(d["pnl"])}">{pct(d["pnl_pct"])}</td>'
        f'<td class="num apagado">{eur(d["min"])}</td>'
        f'<td class="num apagado">{eur(d["max"])}</td>'
        f'<td class="num apagado">{d["latidos"]}</td></tr>'
        for d in reversed(dias)) or '<tr><td colspan="7" class="apagado">Sin días completos todavía.</td></tr>'

    ops = (est.get("operaciones") or [])[-60:]
    filas_ops = "".join(
        f'<tr><td>{time.strftime("%d/%m %H:%M", time.localtime(o.get("ts",0)))}</td>'
        f'<td class="{"pos" if o.get("lado")=="compra" else "neg"}">{o.get("lado")}</td>'
        f'<td class="num">{eur(o.get("cantidad"),6)}</td>'
        f'<td class="num">{eur(o.get("precio"),2)}</td>'
        f'<td class="num apagado">{eur(o.get("comision"),4)}</td>'
        f'<td class="num {clase(o.get("realizado") or 0) if o.get("realizado") is not None else "apagado"}">'
        f'{firmado(o["realizado"]) if o.get("realizado") is not None else "—"}</td>'
        f'<td class="apagado">{html.escape(str(o.get("motivo","")))}</td></tr>'
        for o in reversed(ops)) or '<tr><td colspan="7" class="apagado">Todavía no ha operado.</td></tr>'

    lineas = []
    for e in eventos:
        fn = LEGIBLE.get(e.get("tipo"))
        cls = {"muerte": "l-error", "rechazo": "l-warning", "operacion": "l-hito"}.get(e.get("tipo"), "")
        txt = fn(e) if fn else str(e.get("tipo"))
        lineas.append(f'<div class="{cls}">{time.strftime("%d/%m %H:%M", time.localtime(e.get("ts",0)))}  {html.escape(txt)}</div>')

    cuerpo = f'''
<section class="tarjeta cabecera-agente">
  <h2>{html.escape(simbolo)} · {html.escape(str(cfg.get("estrategia","")))} · vela {html.escape(str(cfg.get("intervalo","")))}</h2>
  <p class="linea">{insignia}</p>
  <p class="nota">{vit.get("ticks",0)} latidos · último {time.strftime("%d/%m/%Y %H:%M", time.localtime(ultimo)) if ultimo else "—"}</p>
</section>

<section class="kpis">{html_kpis}</section>

<section class="tarjeta"><h3>Patrimonio</h3>{svg_curva(serie, capital)}</section>

<section class="tarjeta"><h3>Día a día</h3>
<div class="envoltura"><table>
<thead><tr><th>día</th><th class="num">cierre</th><th class="num">resultado</th><th class="num">%</th><th class="num">mínimo</th><th class="num">máximo</th><th class="num">latidos</th></tr></thead>
<tbody>{filas_dias}</tbody></table></div></section>

<section class="tarjeta"><h3>Operaciones</h3>
<div class="envoltura"><table>
<thead><tr><th>fecha</th><th>lado</th><th class="num">cantidad</th><th class="num">precio</th><th class="num">comisión</th><th class="num">realizado</th><th>motivo</th></tr></thead>
<tbody>{filas_ops}</tbody></table></div></section>

<section class="tarjeta"><h3>Diario de a bordo</h3><pre class="diario">{"".join(lineas)}</pre></section>
'''

    (salida / "index.html").write_text(PLANTILLA.format(
        titulo=f"Bot · {simbolo}", cuerpo=cuerpo,
        pie=time.strftime("%d/%m/%Y %H:%M")), encoding="utf-8")
    print(f"Tablero generado: docs/index.html ({vit.get('ticks',0)} latidos)")
    return 0


PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="600">
<title>{titulo}</title>
<style>
:root{{color-scheme:dark;--f:#0d1117;--f2:#141b24;--f3:#1b2430;--b:#263241;--b2:#334354;
--t:#e6edf3;--t2:#9aa8b8;--t3:#6b7a8c;--verde:#2fbf87;--rojo:#e5606b;--ambar:#f2a33c;
--mono:ui-monospace,SFMono-Regular,Menlo,monospace}}
@media (prefers-color-scheme:light){{:root{{color-scheme:light;--f:#f6f7f9;--f2:#fff;--f3:#eef1f5;
--b:#dde3ea;--b2:#c7d1dc;--t:#16202b;--t2:#5a6876;--t3:#8494a4;--verde:#1a8f63;--rojo:#c8383f}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--f);color:var(--t);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
.envuelve{{max-width:1000px;margin:0 auto;padding:20px;display:flex;flex-direction:column;gap:16px}}
h1{{font:600 20px/1.2 var(--mono);margin:0;letter-spacing:-.02em}}
h2{{font-size:15px;margin:0 0 8px}}
h3{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--t2);margin:0 0 12px}}
.tarjeta{{background:var(--f2);border:1px solid var(--b);border-radius:10px;padding:14px 16px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.kpi{{background:var(--f2);border:1px solid var(--b);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:3px}}
.kpi-t{{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--t3)}}
.kpi-v{{font:600 21px/1.25 var(--mono);letter-spacing:-.02em}}
.kpi-v.pos{{color:var(--verde)}} .kpi-v.neg{{color:var(--rojo)}}
.kpi-s{{font-size:11.5px;color:var(--t3)}}
.linea{{margin:0 0 6px;color:var(--t2)}}
.nota{{color:var(--t3);font-size:12px;margin:0}}
.insignia{{font:11px var(--mono);padding:2px 8px;border-radius:999px;border:1px solid var(--b2);margin-right:6px}}
.insignia.vivo{{color:var(--verde)}} .insignia.muerto{{color:var(--rojo)}} .insignia.pausado{{color:var(--t3)}}
.envoltura{{overflow-x:auto;border:1px solid var(--b);border-radius:8px;max-height:420px;overflow-y:auto}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}}
th,td{{padding:7px 11px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--b)}}
th{{position:sticky;top:0;background:var(--f3);color:var(--t2);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
.num{{text-align:right;font-family:var(--mono)}}
.pos{{color:var(--verde)}} .neg{{color:var(--rojo)}} .apagado{{color:var(--t3)}}
.malla{{stroke:var(--b)}} .base{{stroke:var(--t3);stroke-dasharray:4 4}}
.eje{{fill:var(--t3);font:10px var(--mono)}}
.diario{{margin:0;padding:12px;background:var(--f);border:1px solid var(--b);border-radius:8px;
font:11.5px/1.7 var(--mono);max-height:300px;overflow:auto;color:var(--t2);white-space:pre-wrap}}
.l-error{{color:var(--rojo)}} .l-warning{{color:var(--ambar)}} .l-hito{{color:var(--t)}}
footer{{color:var(--t3);font-size:11.5px;line-height:1.6;border-top:1px solid var(--b);padding-top:14px}}
</style></head><body><div class="envuelve">
<header><h1>bot de compraventa</h1>
<p class="nota">Dinero ficticio. Ninguna orden llega a ningún bróker.</p></header>
{cuerpo}
<footer>Generado el {pie} por GitHub Actions. La página se recarga sola cada 10 minutos.<br>
Ninguna de estas estrategias tiene ventaja demostrada, y un backtest bueno no predice nada.</footer>
</div></body></html>
"""

if __name__ == "__main__":
    raise SystemExit(main())
