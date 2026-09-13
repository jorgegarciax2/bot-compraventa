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


def barra(agentes: list, actual: str) -> str:
    if len(agentes) < 2:
        return ""
    enlaces = []
    for a in agentes:
        n = a.get("nombre", "?")
        etiqueta = {"cripto": "Cripto", "accion": "Acciones"}.get(a.get("tipo"), n)
        clase = " activa" if n == actual else ""
        enlaces.append(f'<a class="pestana{clase}" href="{html.escape(n)}.html">'
                       f'{html.escape(etiqueta)} · {html.escape(a.get("simbolo","")) }</a>')
    return f'<nav class="pestanas">{"".join(enlaces)}</nav>'


def tarjeta_fundamentales(ext: dict) -> str:
    """Las cuentas oficiales. No son una señal de compra: son un filtro de si el
    valor merece operarse."""
    m = (ext or {}).get("fundamentales")
    if not m:
        return ""
    def num(v, suf="", d=1):
        return "—" if v is None else f"{v:,.{d}f}{suf}".replace(",", " ")
    def pc(v, d=1):
        return "—" if v is None else f"{v*100:,.{d}f} %".replace(",", " ")
    filas = [
        ("Ingresos", num((m["ingresos"] or 0) / 1e9, " B$") if m["ingresos"] else "—"),
        ("Crecimiento", pc(m["crecimiento_ingresos"])),
        ("Margen neto", pc(m["margen_neto"])),
        ("ROE", pc(m["roe"])),
        ("Deuda / patrimonio", num(m["deuda_sobre_patrimonio"])),
        ("BPA", num(m["bpa"], " $", 2)),
        ("PER", num(m["per"])),
    ]
    celdas = "".join(f'<div class="dato"><span class="dato-t">{k}</span>'
                     f'<span class="dato-v">{html.escape(v)}</span></div>' for k, v in filas)
    veredicto = "cuentas sanas" if ext.get("calidad_ok") else "no apta"
    clase = "ok" if ext.get("calidad_ok") else "falla"
    motivos = ", ".join(ext.get("motivos") or [])
    return f'''<section class="tarjeta"><h3>Fundamentales
      <span class="insignia {clase}">{veredicto}</span></h3>
      <p class="nota">{html.escape(m.get("empresa") or "")} · ejercicio {m.get("ejercicio")}
      · fuente: SEC EDGAR. {html.escape(motivos)}</p>
      <div class="datos">{celdas}</div>
      <p class="nota">Las cuentas cambian cada trimestre: sirven para decidir
      <em>qué</em> operar, no <em>cuándo</em>. Si suspenden, el bot cierra y no vuelve a entrar.</p>
    </section>'''


def tarjeta_noticias(ext: dict) -> str:
    t = (ext or {}).get("titulares")
    if not t:
        return ""
    rep = ext.get("repunte")
    if rep:
        aviso = (f'<span class="insignia falla">revuelo {rep["razon"]}x</span>'
                 if rep["hay_revuelo"] else
                 f'<span class="insignia ok">{rep["actual"]} hoy · {rep["normal"]} habitual</span>')
    else:
        aviso = '<span class="insignia">sin baremo todavía</span>'
    filas = "".join(
        f'<li><a href="{html.escape(n.get("enlace") or "#")}" target="_blank" rel="noopener">'
        f'{html.escape((n.get("titular") or "")[:120])}</a></li>' for n in t[:10])
    return f'''<section class="tarjeta"><h3>Noticias {aviso}</h3>
      <ul class="titulares">{filas}</ul>
      <p class="nota">El bot <b>no interpreta</b> si un titular es bueno o malo: eso
      necesitaría un modelo de lenguaje que aquí no hay, y contar palabras
      «positivas» daría una cifra con pinta de análisis y valor de moneda al aire.
      Lo único que mide es el <b>repunte</b> de cobertura, y cuando lo detecta deja
      de abrir posiciones — pero sigue pudiendo cerrar.</p>
    </section>'''


def pagina(c: dict, agentes: list) -> str:
    """El cuerpo HTML del tablero de UN agente."""
    nombre = c.get("nombre", "agente")
    dst = RAIZ / "estado" / nombre
    est = leer_json(dst / "estado.json")
    lap = leer_json(dst / "LAPIDA.json")
    ext = leer_json(dst / "externo.json") or {}
    serie = leer_jsonl(dst / "serie.jsonl")
    eventos = leer_jsonl(dst / "diario.jsonl", 60)
    nav = barra(agentes, nombre)

    if not est:
        return nav + ('<section class="tarjeta"><h2>Todavía sin latidos</h2>'
                      '<p class="nota">Este agente aún no ha operado.</p></section>')

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
        insignia = (f'<span class="insignia muerto">† muerto</span> causa: '
                    f'<b>{html.escape(str(causa))}</b>. {html.escape(str(detalle))}')
    elif c.get("pausado"):
        insignia = '<span class="insignia pausado">‖ pausado</span> no opera.'
    else:
        iv = html.escape(str(cfg.get("intervalo", "?")))
        extra = ""
        if not ext.get("calidad_ok", True):
            extra = " <b>Vetado por sus cuentas</b>, el bot no entra."
        elif not ext.get("permitir_abrir", True):
            extra = " Hay revuelo de noticias: no abre posiciones nuevas."
        insignia = (f'<span class="insignia vivo">● en marcha</span> late una vez por '
                    f'vela de {iv}; se comprueba cada 30 minutos.{extra}')

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
         f"comisiones {eur(cart.get('comisiones_pagadas'))} · coste de vida "
         f"{eur(cart.get('coste_vida_pagado'))}", ""),
        ("Caída desde máximo", pct(vit.get("drawdown")),
         f"muere al {pct(cfg.get('reglas_vida',{}).get('max_drawdown',0.5),0)}",
         "neg" if float(vit.get("drawdown") or 0) > 0.0001 else "apagado"),
    ]
    html_kpis = "".join(
        f'<div class="kpi"><span class="kpi-t">{t}</span>'
        f'<span class="kpi-v {cl}">{html.escape(v)}</span>'
        f'<span class="kpi-s">{html.escape(sb)}</span></div>' for t, v, sb, cl in kpis)

    filas_dias = "".join(
        f'<tr><td>{d["dia"]}</td><td class="num">{eur(d["cierre"])}</td>'
        f'<td class="num {clase(d["pnl"])}">{firmado(d["pnl"])}</td>'
        f'<td class="num {clase(d["pnl"])}">{pct(d["pnl_pct"])}</td>'
        f'<td class="num apagado">{eur(d["min"])}</td>'
        f'<td class="num apagado">{eur(d["max"])}</td>'
        f'<td class="num apagado">{d["latidos"]}</td></tr>'
        for d in reversed(dias)) or '<tr><td colspan="7" class="apagado">Sin días completos.</td></tr>'

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
        cls = {"muerte": "l-error", "rechazo": "l-warning",
               "operacion": "l-hito"}.get(e.get("tipo"), "")
        txt = fn(e) if fn else str(e.get("tipo"))
        lineas.append(f'<div class="{cls}">'
                      f'{time.strftime("%d/%m %H:%M", time.localtime(e.get("ts",0)))}  '
                      f'{html.escape(txt)}</div>')

    return f'''{nav}
<section class="tarjeta cabecera-agente">
  <h2>{html.escape(simbolo)} · {html.escape(str(cfg.get("estrategia","")))} · vela {html.escape(str(cfg.get("intervalo","")))}</h2>
  <p class="linea">{insignia}</p>
  <p class="nota">{vit.get("ticks",0)} latidos · último {time.strftime("%d/%m/%Y %H:%M", time.localtime(ultimo)) if ultimo else "—"}</p>
</section>

<section class="kpis">{html_kpis}</section>

<section class="tarjeta"><h3>Patrimonio</h3>{svg_curva(serie, capital)}</section>

{tarjeta_fundamentales(ext)}
{tarjeta_noticias(ext)}

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


def main() -> int:
    conf = leer_json(RAIZ / "configuracion.json") or {}
    agentes = conf.get("agentes") or [conf]
    salida = RAIZ / "docs"
    salida.mkdir(exist_ok=True)
    pie = time.strftime("%d/%m/%Y %H:%M")

    for i, c in enumerate(agentes):
        nombre = c.get("nombre", "agente")
        cuerpo = pagina(c, agentes)
        titulo = f"Bot · {c.get('simbolo','?')}"
        doc = PLANTILLA.format(titulo=titulo, cuerpo=cuerpo, pie=pie)
        (salida / f"{nombre}.html").write_text(doc, encoding="utf-8")
        if i == 0:
            (salida / "index.html").write_text(doc, encoding="utf-8")
        print(f"  docs/{nombre}.html")
    print(f"Tablero generado: {len(agentes)} agente(s)")
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
.pestanas{{display:flex;gap:4px;background:var(--f3);padding:4px;border-radius:10px;
border:1px solid var(--b);flex-wrap:wrap}}
.pestana{{padding:8px 16px;border-radius:7px;color:var(--t2);text-decoration:none;
font-size:13.5px;white-space:nowrap}}
.pestana:hover{{color:var(--t);background:var(--f2)}}
.pestana.activa{{background:#4c9aff;color:#fff;font-weight:600}}
.datos{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}}
.dato{{background:var(--f3);border:1px solid var(--b);border-radius:8px;padding:9px 11px;
display:flex;flex-direction:column;gap:2px}}
.dato-t{{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--t3)}}
.dato-v{{font:600 15px/1.3 var(--mono)}}
.insignia.ok{{color:var(--verde)}} .insignia.falla{{color:var(--rojo)}}
.titulares{{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:7px}}
.titulares li{{font-size:13px;line-height:1.45}}
.titulares a{{color:var(--t2);text-decoration:none}}
.titulares a:hover{{color:#4c9aff;text-decoration:underline}}
h3 .insignia{{margin-left:8px;text-transform:none;letter-spacing:0}}
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
