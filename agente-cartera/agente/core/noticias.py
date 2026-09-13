"""Noticias de un valor, desde el RSS público de Yahoo.

Qué se puede hacer con esto honestamente, y qué no:

* **Sí:** enseñar los titulares al humano, y detectar un *repunte* de cobertura.
  Que de pronto haya diez noticias donde suele haber dos es un hecho medible y
  suele significar que está pasando algo — resultados, una demanda, un rumor.

* **No:** deducir del titular si la noticia es buena o mala. Hacerlo bien
  requiere un modelo de lenguaje, y en GitHub Actions no hay ninguno disponible
  sin clave de pago. Contar palabras «positivas» y «negativas» da una cifra con
  aspecto de análisis y valor de moneda al aire, así que este módulo no lo hace.

Por eso el repunte se usa como **freno**, no como señal: cuando hay revuelo,
el bot no abre posiciones nuevas — pero sí puede cerrar. Ante la duda, esperar
es barato; adivinar, no.
"""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Sequence

RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={}&region=US&lang=en-US"
CABECERAS = {"User-Agent": "bot-compraventa/1.0"}


def _limpiar(t: str) -> str:
    t = re.sub(r"<!\[CDATA\[|\]\]>", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    for a, b in [("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"),
                 ("&lt;", "<"), ("&gt;", ">"), ("&apos;", "'")]:
        t = t.replace(a, b)
    return t.strip()


def titulares(ticker: str, limite: int = 20, timeout: int = 20) -> List[Dict]:
    """Titulares recientes. Lista vacía si Yahoo no responde: nunca revienta."""
    url = RSS.format(urllib.parse.quote(ticker))
    try:
        req = urllib.request.Request(url, headers=CABECERAS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            xml = r.read().decode("utf-8", "replace")
    except Exception:
        return []

    fuera = []
    for bloque in re.findall(r"<item>(.*?)</item>", xml, re.S)[:limite]:
        t = re.search(r"<title>(.*?)</title>", bloque, re.S)
        f = re.search(r"<pubDate>(.*?)</pubDate>", bloque, re.S)
        enlace = re.search(r"<link>(.*?)</link>", bloque, re.S)
        ts = None
        if f:
            for formato in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
                try:
                    ts = time.mktime(time.strptime(_limpiar(f.group(1)), formato))
                    break
                except ValueError:
                    continue
        fuera.append({"titular": _limpiar(t.group(1)) if t else "",
                      "ts": ts, "enlace": _limpiar(enlace.group(1)) if enlace else ""})
    return fuera


def pulso(noticias: List[Dict], horas: int = 24) -> int:
    """Cuántos titulares hay de las últimas `horas`. Un número, nada más."""
    ahora = time.time()
    return sum(1 for n in noticias
               if n.get("ts") and ahora - n["ts"] <= horas * 3600)


def repunte(actual: int, historico: Sequence[int], factor: float = 2.5,
            minimo_historico: int = 20) -> Optional[dict]:
    """¿Hay hoy mucha más cobertura de la habitual?

    El baremo NO sale del propio RSS: Yahoo sólo devuelve una veintena de
    titulares recientes, así que cualquier «media semanal» calculada con ellos
    está amañada — daría revuelo siempre. El baremo tiene que venir de fuera:
    la propia serie que el bot va apuntando latido a latido.

    Hasta que haya suficiente historia, esto devuelve None y el bot opera sin
    este freno. Mejor no opinar que opinar mal.
    """
    limpio = [h for h in historico if h is not None]
    if len(limpio) < minimo_historico:
        return None
    ordenado = sorted(limpio)
    mediana = ordenado[len(ordenado) // 2]
    if mediana <= 0:
        mediana = 1
    razon = actual / mediana
    return {"actual": actual, "normal": mediana, "muestras": len(limpio),
            "razon": round(razon, 2), "hay_revuelo": razon >= factor}
