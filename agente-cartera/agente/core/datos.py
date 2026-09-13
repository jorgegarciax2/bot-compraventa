"""Fuentes de precios.

Todas devuelven `Vela` (OHLCV) y son intercambiables. Binance y Yahoo son
públicas y no necesitan clave. `Sintetica` sirve para probar el motor sin
red y para estresar al agente con escenarios malos a propósito.
"""
from __future__ import annotations

import csv
import json
import math
import random
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

USER_AGENT = "agente-cartera/1.0"


@dataclass(frozen=True)
class Vela:
    ts: int          # epoch en segundos, apertura de la vela
    apertura: float
    maximo: float
    minimo: float
    cierre: float
    volumen: float = 0.0


class FuenteDatos:
    """Interfaz. Implementa `historico`; `ultima` sale gratis."""
    nombre = "base"

    def historico(self, simbolo: str, intervalo: str = "1h",
                  limite: int = 500) -> List[Vela]:
        raise NotImplementedError

    def ultima(self, simbolo: str, intervalo: str = "1h") -> Vela:
        velas = self.historico(simbolo, intervalo, limite=2)
        if not velas:
            raise RuntimeError(f"Sin datos para {simbolo}")
        return velas[-1]


def _get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Binance(FuenteDatos):
    """Cripto al contado. API pública, sin clave, sin registro.

    Símbolos: BTCEUR, ETHEUR, BTCUSDT... Intervalos: 1m 5m 15m 1h 4h 1d.
    """
    nombre = "binance"
    BASE = "https://api.binance.com/api/v3"

    def historico(self, simbolo: str, intervalo: str = "1h",
                  limite: int = 500) -> List[Vela]:
        velas: List[Vela] = []
        restantes = limite
        fin: Optional[int] = None
        while restantes > 0:
            lote = min(restantes, 1000)
            params = {"symbol": simbolo.upper(), "interval": intervalo,
                      "limit": lote}
            if fin is not None:
                params["endTime"] = fin
            url = f"{self.BASE}/klines?{urllib.parse.urlencode(params)}"
            crudo = _get_json(url)
            if not crudo:
                break
            trozo = [Vela(int(k[0]) // 1000, float(k[1]), float(k[2]),
                          float(k[3]), float(k[4]), float(k[5])) for k in crudo]
            velas = trozo + velas
            restantes -= len(trozo)
            fin = int(crudo[0][0]) - 1
            if len(crudo) < lote:
                break
            time.sleep(0.15)   # cortesía con el rate limit
        return velas[-limite:]

    def precio(self, simbolo: str) -> float:
        url = f"{self.BASE}/ticker/price?symbol={simbolo.upper()}"
        return float(_get_json(url)["price"])


class Yahoo(FuenteDatos):
    """Acciones, ETFs e índices. Símbolos tipo AAPL, SPY, IWDA.AS, SAN.MC."""
    nombre = "yahoo"
    BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
    _RANGO = {"1d": "2y", "1h": "60d", "5m": "30d", "1m": "7d"}

    def historico(self, simbolo: str, intervalo: str = "1d",
                  limite: int = 500) -> List[Vela]:
        rango = self._RANGO.get(intervalo, "2y")
        url = (f"{self.BASE}/{urllib.parse.quote(simbolo)}"
               f"?range={rango}&interval={intervalo}")
        d = _get_json(url)["chart"]["result"][0]
        ts = d["timestamp"]
        q = d["indicators"]["quote"][0]
        velas = []
        for i, t in enumerate(ts):
            c = q["close"][i]
            if c is None:
                continue
            velas.append(Vela(
                int(t),
                q["open"][i] if q["open"][i] is not None else c,
                q["high"][i] if q["high"][i] is not None else c,
                q["low"][i] if q["low"][i] is not None else c,
                float(c),
                float(q["volume"][i] or 0),
            ))
        return velas[-limite:]


class Csv(FuenteDatos):
    """CSV con cabecera: ts,apertura,maximo,minimo,cierre,volumen."""
    nombre = "csv"

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)

    def historico(self, simbolo: str = "", intervalo: str = "",
                  limite: int = 10 ** 9) -> List[Vela]:
        with self.ruta.open(encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        velas = [Vela(int(float(r["ts"])), float(r["apertura"]),
                      float(r["maximo"]), float(r["minimo"]),
                      float(r["cierre"]), float(r.get("volumen", 0) or 0))
                 for r in filas]
        return velas[-limite:]


class Sintetica(FuenteDatos):
    """Mercado generado: deriva + volatilidad con cambios de régimen y saltos.

    No es un mercado real, pero sí es *desagradable* como uno: tiene tramos
    alcistas, laterales y caídas bruscas. Sirve para comprobar que el agente
    sobrevive a lo bueno y muere en lo malo.
    """
    nombre = "sintetica"

    def __init__(self, precio_inicial: float = 100.0, semilla: int = 7,
                 deriva_anual: float = 0.10, vol_anual: float = 0.60,
                 velas_por_anio: int = 8760, prob_crisis: float = 0.0008) -> None:
        self.p0 = precio_inicial
        self.semilla = semilla
        self.mu = deriva_anual
        self.sigma = vol_anual
        self.n_anio = velas_por_anio
        self.prob_crisis = prob_crisis

    def historico(self, simbolo: str = "SINT", intervalo: str = "1h",
                  limite: int = 2000) -> List[Vela]:
        rnd = random.Random(self.semilla)
        dt = 1.0 / self.n_anio
        precio = self.p0
        mu, sigma = self.mu, self.sigma
        crisis = 0
        ahora = int(time.time()) - limite * 3600
        velas: List[Vela] = []
        for i in range(limite):
            if crisis > 0:
                crisis -= 1
                mu_e, sig_e = -1.5, sigma * 2.5
            else:
                if rnd.random() < self.prob_crisis:
                    crisis = rnd.randint(24, 240)
                mu_e, sig_e = mu, sigma
                if i % 900 == 0:                       # cambio de régimen suave
                    mu = rnd.choice([-0.4, -0.1, 0.1, 0.35, 0.8])
                    sigma = rnd.uniform(0.25, 0.95)
            z = rnd.gauss(0, 1)
            ret = (mu_e - 0.5 * sig_e ** 2) * dt + sig_e * math.sqrt(dt) * z
            apertura = precio
            precio = max(1e-6, precio * math.exp(ret))
            mecha = abs(rnd.gauss(0, sig_e * math.sqrt(dt) * 0.6))
            alto = max(apertura, precio) * (1 + mecha)
            bajo = min(apertura, precio) * (1 - mecha)
            velas.append(Vela(ahora + i * 3600, apertura, alto, bajo, precio,
                              rnd.uniform(10, 1000)))
        return velas


def fuente_por_nombre(nombre: str, **kw) -> FuenteDatos:
    tabla = {"binance": Binance, "yahoo": Yahoo, "sintetica": Sintetica, "csv": Csv}
    if nombre not in tabla:
        raise ValueError(f"Fuente desconocida: {nombre}. Opciones: {list(tabla)}")
    return tabla[nombre](**kw)


def guardar_csv(velas: Iterable[Vela], ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "apertura", "maximo", "minimo", "cierre", "volumen"])
        for v in velas:
            w.writerow([v.ts, v.apertura, v.maximo, v.minimo, v.cierre, v.volumen])
    return ruta


# ------------------------------------------------------------- remuestreo
SEGUNDOS_INTERVALO = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                      "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
                      "12h": 43200, "1d": 86400}


def remuestrear(velas: List[Vela], segundos: int) -> List[Vela]:
    """Agrupa velas cortas en otras más largas, alineadas al reloj UTC.

    Existe por una limitación concreta: Yahoo no sirve velas de 4 horas, y en
    GitHub Actions no se puede usar Binance porque bloquea las IP de EE. UU.
    Así que se piden de 1 hora y se agrupan de cuatro en cuatro.

    La última vela puede estar a medio formar. Es lo correcto: su cierre es el
    precio actual, que es justo lo que hace falta para valorar la cartera.
    """
    if not velas:
        return []
    cubos = {}
    orden = []
    for v in velas:
        k = v.ts - (v.ts % segundos)
        c = cubos.get(k)
        if c is None:
            cubos[k] = [v.apertura, v.maximo, v.minimo, v.cierre, v.volumen]
            orden.append(k)
        else:
            c[1] = max(c[1], v.maximo)
            c[2] = min(c[2], v.minimo)
            c[3] = v.cierre
            c[4] += v.volumen
    return [Vela(k, *cubos[k]) for k in orden]


class Remuestreada(FuenteDatos):
    """Envuelve otra fuente y le cambia el tamaño de vela."""
    nombre = "remuestreada"

    def __init__(self, base: FuenteDatos, origen: str = "1h") -> None:
        self.base = base
        self.origen = origen

    def historico(self, simbolo: str, intervalo: str = "4h",
                  limite: int = 500) -> List[Vela]:
        destino = SEGUNDOS_INTERVALO.get(intervalo)
        origen = SEGUNDOS_INTERVALO.get(self.origen)
        if not destino or not origen or destino < origen:
            raise ValueError(f"No puedo remuestrear de {self.origen} a {intervalo}")
        factor = max(1, destino // origen)
        crudas = self.base.historico(simbolo, self.origen, limite * factor + factor)
        return remuestrear(crudas, destino)[-limite:]
