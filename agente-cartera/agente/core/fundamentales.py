"""Fundamentales desde la SEC: las cuentas oficiales, sin intermediarios.

EDGAR publica lo que cada empresa cotizada en EE. UU. presenta al regulador,
auditado y en formato estructurado. Es gratis, no pide clave y no se puede
"cerrar" como hizo Yahoo con sus ratios.

Dos límites que conviene tener claros desde el principio:

* **Sólo EE. UU.** La SEC regula a quien cotiza allí. Para el Santander o
  Iberdrola no hay equivalente gratuito y estructurado.
* **Cambian cada trimestre.** Un fundamental no sirve para decidir *cuándo*
  comprar: sirve para decidir *qué* merece la pena mirar. Usarlo como
  disparador en un bot que late cada 4 horas sería teatro — el dato es el
  mismo durante tres meses.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

# La SEC exige identificarse con un contacto real y pide moderación (máx. 10/s).
CABECERAS = {"User-Agent": "bot-compraventa/1.0 (contacto: jorge.garciagarcia96@gmail.com)",
             "Accept-Encoding": "gzip, deflate"}
CADUCIDAD = 7 * 86400          # las cuentas cambian cada trimestre: una semana sobra

# Las empresas no siempre usan la misma etiqueta contable para lo mismo.
INGRESOS = ["RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues", "SalesRevenueNet"]
BENEFICIO = ["NetIncomeLoss", "ProfitLoss"]
BPA = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]


def _pedir(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        crudo = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip
            crudo = gzip.decompress(crudo)
        return json.loads(crudo.decode("utf-8"))


def _cache(carpeta: Optional[Path], nombre: str) -> Optional[Path]:
    if carpeta is None:
        return None
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / nombre


def cik_de(ticker: str, carpeta: Optional[Path] = None) -> Optional[str]:
    """Traduce AAPL -> 0000320193. La SEC publica la tabla entera."""
    ruta = _cache(carpeta, "tickers_sec.json")
    tabla = None
    if ruta and ruta.exists() and time.time() - ruta.stat().st_mtime < 30 * 86400:
        try:
            tabla = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            tabla = None
    if tabla is None:
        tabla = _pedir("https://www.sec.gov/files/company_tickers.json")
        if ruta:
            ruta.write_text(json.dumps(tabla), encoding="utf-8")
    for fila in tabla.values():
        if fila.get("ticker", "").upper() == ticker.upper():
            return str(fila["cik_str"]).zfill(10)
    return None


def _dedup(entradas: List[dict]) -> List[dict]:
    """Un ejercicio puede aparecer en varios 10-K. Vale la presentación más nueva."""
    por_fin: Dict[str, dict] = {}
    for x in sorted(entradas, key=lambda y: y.get("filed", "")):
        por_fin[x["end"]] = x
    return [por_fin[k] for k in sorted(por_fin)]


def _anuales_flujo(hechos: dict, conceptos: List[str], unidad: str = "USD") -> List[dict]:
    """Serie anual de una magnitud de flujo (ingresos, beneficio, BPA).

    Dos trampas de XBRL que hay que esquivar, y que dan resultados absurdos si
    se pasan por alto:

    1. Dentro de un 10-K vienen también valores TRIMESTRALES marcados como FY.
       Se filtran exigiendo que el periodo dure un año (350-380 días).
    2. Las empresas CAMBIAN de etiqueta contable con los años. NVIDIA dejó de
       usar `RevenueFromContract...` en 2022. Por eso no se coge "el primer
       concepto que exista", sino que se mezclan todos los candidatos y gana
       la presentación más reciente de cada ejercicio.
    """
    from datetime import date
    entradas = []
    for c in conceptos:
        for x in hechos.get(c, {}).get("units", {}).get(unidad, []):
            if x.get("form") != "10-K" or x.get("fp") != "FY" or not x.get("start"):
                continue
            try:
                dias = (date.fromisoformat(x["end"]) - date.fromisoformat(x["start"])).days
            except ValueError:
                continue
            if 350 <= dias <= 380:
                entradas.append(x)
    return _dedup(entradas)


def _anuales_saldo(hechos: dict, conceptos: List[str], unidad: str = "USD") -> List[dict]:
    """Serie anual de un saldo (activos, pasivos, patrimonio): es una foto, no
    tiene periodo, así que el filtro de duración no aplica."""
    entradas = []
    for c in conceptos:
        for x in hechos.get(c, {}).get("units", {}).get(unidad, []):
            if x.get("form") == "10-K" and x.get("fp") == "FY" and not x.get("start"):
                entradas.append(x)
    return _dedup(entradas)


def metricas(ticker: str, carpeta: Optional[Path] = None,
             precio: Optional[float] = None) -> Optional[dict]:
    """Las cifras que importan de una empresa. None si no está en la SEC."""
    cik = cik_de(ticker, carpeta)
    if not cik:
        return None

    ruta = _cache(carpeta, f"sec_{cik}.json")
    datos = None
    if ruta and ruta.exists() and time.time() - ruta.stat().st_mtime < CADUCIDAD:
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            datos = None
    if datos is None:
        datos = _pedir(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        if ruta:
            ruta.write_text(json.dumps(datos), encoding="utf-8")

    hechos = datos.get("facts", {}).get("us-gaap", {})
    ingresos = _anuales_flujo(hechos, INGRESOS)
    beneficio = _anuales_flujo(hechos, BENEFICIO)
    activos = _anuales_saldo(hechos, ["Assets"])
    pasivos = _anuales_saldo(hechos, ["Liabilities"])
    patrimonio = _anuales_saldo(hechos, ["StockholdersEquity"])
    bpa = _anuales_flujo(hechos, BPA, "USD/shares")

    # El margen mezcla dos series: si no son del mismo ejercicio, no se calcula.
    mismo_ejercicio = bool(ingresos and beneficio
                           and ingresos[-1]["end"] == beneficio[-1]["end"])

    def ultimo(serie):
        return serie[-1]["val"] if serie else None

    ing, ben = ultimo(ingresos), ultimo(beneficio)
    act, pas, pat = ultimo(activos), ultimo(pasivos), ultimo(patrimonio)
    e = ultimo(bpa)

    crecimiento = None
    if len(ingresos) >= 2 and ingresos[-2]["val"]:
        crecimiento = ingresos[-1]["val"] / ingresos[-2]["val"] - 1

    return {
        "ticker": ticker.upper(),
        "empresa": datos.get("entityName"),
        "ejercicio": ingresos[-1]["end"] if ingresos else None,
        "ingresos": ing,
        "beneficio": ben,
        "crecimiento_ingresos": crecimiento,
        "margen_neto": (ben / ing) if (mismo_ejercicio and ing and ing > 0) else None,
        "roe": (ben / pat) if (pat and ben is not None and pat > 0) else None,
        "deuda_sobre_patrimonio": (pas / pat) if (pat and pas is not None and pat > 0) else None,
        "bpa": e,
        "per": (precio / e) if (precio and e and e > 0) else None,
        "historico_ingresos": [(x["end"], x["val"]) for x in ingresos[-5:]],
    }


def calidad(m: Optional[dict]) -> tuple:
    """Convierte las cifras en un aprobado o un suspenso, con sus motivos.

    No es una nota de inversión: es un filtro grosero para descartar empresas
    que pierden dinero o están muy endeudadas. Que apruebe no dice nada sobre
    si la acción subirá.
    """
    if not m:
        return False, ["sin datos en la SEC"]
    motivos = []
    if m["beneficio"] is None or m["beneficio"] <= 0:
        motivos.append("pierde dinero")
    if m["margen_neto"] is not None and m["margen_neto"] < 0.03:
        motivos.append(f"margen neto {m['margen_neto']:.1%}")
    if m["deuda_sobre_patrimonio"] is not None and m["deuda_sobre_patrimonio"] > 4:
        motivos.append(f"deuda/patrimonio {m['deuda_sobre_patrimonio']:.1f}")
    if m["crecimiento_ingresos"] is not None and m["crecimiento_ingresos"] < -0.10:
        motivos.append(f"ingresos {m['crecimiento_ingresos']:+.1%}")
    return (not motivos), (motivos or ["cuentas sanas"])
