"""Servidor local del panel de tbot.

Sólo biblioteca estándar: el resto de dependencias son las que ya usa tbot.
Escucha exclusivamente en 127.0.0.1 — este panel no se expone a la red.

    python web/servidor.py [--puerto 8765] [--sin-navegador]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent.parent
TBOT = RAIZ / "tbot"
ESTATICO = Path(__file__).resolve().parent / "estatico"
sys.path.insert(0, str(Path(__file__).resolve().parent))

# tbot vive en el subdirectorio tbot/src y no está instalado como paquete:
# así el panel funciona con cualquier Python >= 3.9 sin tocar el pyproject.
sys.path.insert(0, str(TBOT / "src"))

import auth                                                        # noqa: E402
import vivo                                                        # noqa: E402

# tbot arrastra pandas, pyarrow y duckdb: unos 300 MB de RAM que sólo hacen falta
# cuando se usa el laboratorio. En una máquina de 1 GB eso es la diferencia entre
# arrancar y no arrancar, así que se importa cuando se necesita, no al arrancar.
ESTRATEGIAS = {
    "comprar_y_mantener": "Compra a partes iguales en la primera barra y no vuelve "
                          "a tocar nada. La vara de medir.",
    "pesos_iguales": "Equiponderado con rebalanceo en cada barra. Comparado con el "
                     "anterior, dice cuánto cuesta rebalancear.",
    "cruce_medias": "Dentro cuando la media rápida supera a la lenta. Genera "
                    "operaciones: sirve para ver el peso de los costes.",
    "liquidez": "No hace nada. Su equity debe salir plana; si no, el motor está roto.",
}


def _clase_estrategia(nombre: str):
    from tbot.strategies import basicas
    return {"comprar_y_mantener": basicas.ComprarYMantener,
            "pesos_iguales": basicas.PesosIguales,
            "cruce_medias": basicas.CruceMedias,
            "liquidez": basicas.Liquidez}[nombre]

RUTA_CONFIG = TBOT / "config" / "config.yaml"
MAX_PUNTOS_CURVA = 1500

AUTH: dict = {"cfg": None, "exige": False}
log = logging.getLogger("panel")


# --------------------------------------------------------------------- tareas
class Tarea:
    """Un trabajo en segundo plano con su registro en vivo y su resultado."""

    def __init__(self, accion: str, params: dict):
        self.id = uuid.uuid4().hex[:12]
        self.accion = accion
        self.params = params
        self.estado = "en_curso"          # en_curso | hecho | error
        self.log: list = []
        self.resultado = None
        self.error = None
        self.inicio = time.time()
        self.fin = None
        self.hilo = None
        self._lock = threading.Lock()

    def escribe(self, linea: str, nivel: str = "info") -> None:
        with self._lock:
            self.log.append({"t": time.time(), "nivel": nivel, "texto": linea})
            if len(self.log) > 4000:
                del self.log[:1000]

    def instantanea(self, desde: int = 0) -> dict:
        with self._lock:
            lineas = self.log[desde:]
            total = len(self.log)
        return {
            "id": self.id, "accion": self.accion, "estado": self.estado,
            "lineas": lineas, "total_lineas": total,
            "segundos": round((self.fin or time.time()) - self.inicio, 1),
            "resultado": self.resultado, "error": self.error,
        }


TAREAS: dict = {}
TAREAS_ORDEN = deque(maxlen=60)
_LOCK_TAREAS = threading.Lock()
_POR_HILO: dict = {}


class ManejadorLog(logging.Handler):
    """Encamina cada línea de logging a la tarea del hilo que la emitió."""

    def emit(self, record):
        tarea = _POR_HILO.get(threading.get_ident())
        if tarea is None:
            return
        tarea.escribe(self.format(record), record.levelname.lower())


def _instalar_logging() -> None:
    h = ManejadorLog()
    h.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.addHandler(h)

    # Los sucesos del panel (arranques, contraseñas falladas) van además a la
    # salida estándar, que es lo que recoge journalctl en el servidor.
    consola = logging.StreamHandler(sys.stderr)
    consola.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                                           datefmt="%Y-%m-%d %H:%M:%S"))
    log.addHandler(consola)
    log.propagate = False


def lanzar(accion: str, params: dict, funcion) -> Tarea:
    t = Tarea(accion, params)

    def correr():
        _POR_HILO[threading.get_ident()] = t
        try:
            t.resultado = funcion(t, params)
            t.estado = "hecho"
        except Exception as e:
            t.estado = "error"
            t.error = f"{type(e).__name__}: {e}"
            t.escribe(traceback.format_exc(), "error")
        finally:
            t.fin = time.time()
            _POR_HILO.pop(threading.get_ident(), None)

    t.hilo = threading.Thread(target=correr, daemon=True)
    with _LOCK_TAREAS:
        TAREAS[t.id] = t
        TAREAS_ORDEN.append(t.id)
        for viejo in [k for k in TAREAS if k not in TAREAS_ORDEN]:
            TAREAS.pop(viejo, None)
    t.hilo.start()
    return t


# ------------------------------------------------------------------ utilidades
def _conf() -> dict:
    from tbot import config as cfg
    return cfg.cargar(RUTA_CONFIG)


def _store(conf: dict):
    from tbot.data.store import ParquetStore
    raiz = Path(conf["paths"]["data_root"])
    if not raiz.is_absolute():
        raiz = TBOT / raiz
    return ParquetStore(raiz)


def _ms(ts) -> int:
    return int(ts.timestamp() * 1000)


def _diezmar(pares: list, maximo: int = MAX_PUNTOS_CURVA) -> list:
    """Reduce la serie para el navegador conservando SIEMPRE el último punto."""
    if len(pares) <= maximo:
        return pares
    paso = len(pares) / float(maximo)
    fuera = [pares[int(i * paso)] for i in range(maximo)]
    if fuera[-1] != pares[-1]:
        fuera[-1] = pares[-1]
    return fuera


def _fuente(market: str, conf: dict):
    if market == "crypto":
        from tbot.data.sources.crypto_ccxt import CryptoSource
        return CryptoSource(conf["universo"]["crypto"]["exchange"])
    if market == "equity":
        from tbot.data.sources.equity_alpaca import EquitySource
        return EquitySource()
    if market == "synthetic":
        from tbot.data.sources.synthetic import SyntheticSource
        return SyntheticSource()
    raise ValueError("mercado desconocido: %s" % market)


# -------------------------------------------------------------------- acciones
def accion_ingest(t: Tarea, p: dict) -> dict:
    from tbot.data.ingest import ingestar
    conf = _conf()
    market = p["market"]
    u = conf["universo"][market]
    simbolos = p.get("symbols") or u["simbolos"]
    tf = p.get("timeframe") or u["timeframe"]
    desde = p.get("desde") or u["desde"]
    t.escribe("Descargando %d símbolo(s) de %s %s desde %s"
              % (len(simbolos), market, tf, desde))
    res = ingestar(_fuente(market, conf), _store(conf), simbolos, tf, desde)
    filas = res.to_dict("records")
    nuevas = int(res["nuevas"].sum())
    fallos = [f for f in filas if str(f["estado"]).startswith("ERROR")]
    t.escribe("%d velas nuevas. %d símbolo(s) con error." % (nuevas, len(fallos)))
    return {"tipo": "ingest", "market": market, "timeframe": tf,
            "filas": filas, "nuevas": nuevas, "fallos": len(fallos)}


def accion_info(t: Tarea, p: dict) -> dict:
    conf = _conf()
    df = _store(conf).info()
    filas = []
    for f in df.to_dict("records"):
        f["desde"] = str(f["desde"])
        f["hasta"] = str(f["hasta"])
        filas.append(f)
    t.escribe("Almacén vacío." if not filas else "%d serie(s) en el almacén." % len(filas))
    return {"tipo": "info", "filas": filas}


def accion_validate(t: Tarea, p: dict) -> dict:
    from tbot.data import quality
    conf = _conf()
    store = _store(conf)
    market = p["market"]
    u = conf["universo"][market]
    tf = p.get("timeframe") or u["timeframe"]
    simbolos = p.get("symbols") or store.symbols(market, tf) or u["simbolos"]
    q = conf.get("calidad", {})
    informes, fallos = [], 0
    for s in simbolos:
        rep = quality.validar(
            store.read(market, tf, s), s, tf,
            max_gap_ratio=q.get("max_gap_ratio", 0.02),
            max_retorno_barra=q.get("max_retorno_barra", 0.50))
        fallos += (not rep.ok)
        t.escribe("%s: %d velas -> %s" % (s, rep.rows, "OK" if rep.ok else "FALLA"),
                  "info" if rep.ok else "error")
        for i in rep.issues:
            t.escribe("   %s" % i, "warning" if i.severity == quality.AVISO else "error")
        informes.append({
            "symbol": s, "velas": rep.rows, "ok": bool(rep.ok),
            "desde": str(rep.start), "hasta": str(rep.end),
            "issues": [{"severity": i.severity, "code": i.code, "message": i.message,
                        "count": i.count, "sample": list(i.sample)} for i in rep.issues],
        })
    t.escribe("%d/%d símbolos válidos" % (len(simbolos) - fallos, len(simbolos)))
    return {"tipo": "validate", "market": market, "timeframe": tf,
            "informes": informes, "validos": len(simbolos) - fallos,
            "total": len(simbolos)}


def _serializa_resultado(res, market: str, tf: str, simbolos: list, etiqueta: str,
                         costes_activos: bool) -> dict:
    from tbot.backtest.metrics import drawdown_series
    eq = res.equity.dropna()
    curva = _diezmar([[_ms(ts), round(float(v), 4)] for ts, v in eq.items()])
    dd = drawdown_series(eq)
    curva_dd = _diezmar([[_ms(ts), round(float(v), 6)] for ts, v in dd.items()])

    ops = []
    if len(res.trades):
        tr = res.trades.tail(500)
        for r in tr.to_dict("records"):
            pnl = r.get("pnl")
            ops.append({
                "ts": str(r["ts"])[:19], "symbol": r["symbol"], "lado": r["lado"],
                "unidades": round(float(r["unidades"]), 8),
                "precio": round(float(r["precio"]), 6),
                "notional": round(float(r["notional"]), 2),
                "comision": round(float(r["comision"]), 4),
                "pnl": None if pnl is None or pnl != pnl else round(float(pnl), 2),
            })

    metricas = {}
    for k, v in res.metricas.items():
        metricas[k] = None if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))) else v
    return {
        "etiqueta": etiqueta,
        "estrategia": res.estrategia,
        "market": market, "timeframe": tf, "symbols": simbolos,
        "capital_inicial": float(res.capital_inicial),
        "equity_final": float(eq.iloc[-1]),
        "desde": str(eq.index[0])[:19], "hasta": str(eq.index[-1])[:19],
        "costes_activos": costes_activos,
        "metricas": metricas, "curva": curva, "drawdown": curva_dd,
        "operaciones": ops, "n_operaciones": int(len(res.trades)),
    }


def _prepara_backtest(p: dict):
    from tbot.backtest.costs import CostModel
    from tbot.backtest.engine import Backtester
    conf = _conf()
    store = _store(conf)
    market = p["market"]
    u = conf["universo"][market]
    tf = p.get("timeframe") or u["timeframe"]
    simbolos = p.get("symbols") or u["simbolos"]
    datos = {s: df for s, df in store.read_many(
        market, tf, simbolos, p.get("desde") or None, p.get("hasta") or None).items()
        if not df.empty}
    if not datos:
        raise RuntimeError("No hay datos para %s %s. Descarga primero el histórico "
                           "con «Descargar histórico»." % (market, tf))
    c = conf["costes"][market]
    sin_costes = bool(p.get("sin_costes"))
    bt = Backtester(
        costes=CostModel.sin_costes() if sin_costes
        else CostModel(c["comision_bps"], c["slippage_bps"], c["spread_bps"]),
        capital_inicial=float(p.get("capital") or conf["backtest"]["capital_inicial"]),
        banda_rebalanceo=0.0 if p.get("rebalanceo_exacto")
        else conf["backtest"].get("banda_rebalanceo", 0.0),
    )
    return conf, bt, datos, market, tf, list(datos), not sin_costes


def _crear_estrategia(nombre: str, p: dict):
    clase = _clase_estrategia(nombre)
    if nombre == "cruce_medias":
        return clase(rapida=int(p.get("rapida") or 20), lenta=int(p.get("lenta") or 50))
    return clase()


def accion_backtest(t: Tarea, p: dict) -> dict:
    conf, bt, datos, market, tf, simbolos, con_costes = _prepara_backtest(p)
    nombre = p.get("estrategia") or "comprar_y_mantener"
    if nombre not in ESTRATEGIAS:
        raise ValueError("estrategia desconocida: %s" % nombre)
    t.escribe("Backtest %s sobre %s (%s) · %s → %s · %s"
              % (nombre, ", ".join(simbolos), tf, p.get("desde") or "inicio",
                 p.get("hasta") or "final", "con costes" if con_costes else "SIN COSTES"))
    res = bt.run(datos, _crear_estrategia(nombre, p), timeframe=tf, market=market)
    etiqueta = nombre + ("" if con_costes else " (sin costes)")
    fuera = _serializa_resultado(res, market, tf, simbolos, etiqueta, con_costes)
    t.escribe("Equity %.2f → %.2f | CAGR %.2f%% | máxDD %.2f%% | Sharpe %.2f | %d ops"
              % (fuera["capital_inicial"], fuera["equity_final"],
                 100 * (fuera["metricas"].get("cagr") or 0),
                 100 * (fuera["metricas"].get("max_drawdown") or 0),
                 fuera["metricas"].get("sharpe") or 0, fuera["n_operaciones"]))
    return {"tipo": "backtest", "resultados": [fuera]}


def accion_comparar(t: Tarea, p: dict) -> dict:
    """Corre todas las estrategias sobre los mismos datos y las superpone.

    Es la comparación que importa: una curva sola no dice nada si no está al
    lado de comprar y mantener.
    """
    conf, bt, datos, market, tf, simbolos, con_costes = _prepara_backtest(p)
    salida = []
    for nombre in ESTRATEGIAS:
        t.escribe("— %s" % nombre)
        res = bt.run(datos, _crear_estrategia(nombre, p), timeframe=tf, market=market)
        fuera = _serializa_resultado(res, market, tf, simbolos,
                                     nombre + ("" if con_costes else " (sin costes)"),
                                     con_costes)
        m = fuera["metricas"]
        t.escribe("   final %.2f | CAGR %.2f%% | máxDD %.2f%% | Sharpe %.2f | %d ops"
                  % (fuera["equity_final"], 100 * (m.get("cagr") or 0),
                     100 * (m.get("max_drawdown") or 0), m.get("sharpe") or 0,
                     fuera["n_operaciones"]))
        salida.append(fuera)
    salida.sort(key=lambda r: r["equity_final"], reverse=True)
    return {"tipo": "comparar", "resultados": salida}


ACCIONES = {
    "ingest": accion_ingest, "info": accion_info, "validate": accion_validate,
    "backtest": accion_backtest, "comparar": accion_comparar,
}


# ------------------------------------------------------------------- servidor
ENTRADA = """<!doctype html><html lang=es><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Bot de compraventa</title><style>
:root{color-scheme:dark;--f:#0d1117;--f2:#141b24;--f3:#1b2430;--b:#263241;
--t:#e6edf3;--t2:#9aa8b8;--a:#4c9aff;--r:#e5606b}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--f);
color:var(--t);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
form{background:var(--f2);border:1px solid var(--b);border-radius:12px;padding:28px;
width:min(94vw,340px);display:flex;flex-direction:column;gap:14px}
h1{margin:0;font:600 19px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:-.02em}
p{margin:0;color:var(--t2);font-size:12.5px}
input{padding:10px 12px;background:var(--f3);color:var(--t);border:1px solid var(--b);
border-radius:8px;font:inherit;font-size:15px}
input:focus{outline:2px solid var(--a);outline-offset:-1px}
button{padding:10px;border:0;border-radius:8px;background:var(--a);color:#fff;
font:inherit;font-size:14px;font-weight:600;cursor:pointer}
.err{color:var(--r);font-size:12.5px}
</style>
<form method=post action=/entrar>
<h1>bot</h1>
<p>Panel privado. Introduce la contrase&#241;a.</p>
<input type=password name=clave autocomplete=current-password autofocus required>
<button type=submit>Entrar</button>
<span class=err>%s</span>
</form></html>"""


class Manejador(BaseHTTPRequestHandler):
    server_version = "tbot-panel"

    def log_message(self, formato, *args):     # silencio: el log útil es el de las tareas
        pass

    # ------------------------------------------------------------ respuestas
    def _json(self, datos, codigo: int = 200) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    # ------------------------------------------------------------- sesión
    def _ip(self) -> str:
        reenviada = self.headers.get("X-Forwarded-For", "")
        if reenviada:
            return reenviada.split(",")[0].strip()
        return self.client_address[0]

    def _https(self) -> bool:
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def _autenticado(self) -> bool:
        if not AUTH["exige"]:
            return True
        cfg = AUTH["cfg"]
        if not cfg:
            return False
        return auth.sesion_valida(auth.cookie_de(self.headers.get("Cookie", "")), cfg)

    def _entrada(self, mensaje: str = "", codigo: int = 200) -> None:
        cuerpo = (ENTRADA % mensaje).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _cerrar_sesion(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/entrar")
        self.send_header("Set-Cookie",
                         "sesion=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")
        self.end_headers()

    def _fichero(self, nombre: str) -> None:
        ruta = (ESTATICO / nombre).resolve()
        if not str(ruta).startswith(str(ESTATICO.resolve())) or not ruta.is_file():
            self.send_error(404)
            return
        tipos = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
        cuerpo = ruta.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipos.get(ruta.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(cuerpo)

    # ------------------------------------------------------------------- GET
    def do_GET(self):
        u = urlparse(self.path)
        ruta, q = u.path, parse_qs(u.query)

        if ruta == "/entrar":
            if not AUTH["exige"] or self._autenticado():
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
                return
            return self._entrada()
        if ruta == "/salir":
            return self._cerrar_sesion()

        if not self._autenticado():
            if ruta.startswith("/api/"):
                return self._json({"error": "sesión caducada", "entrar": True}, 401)
            self.send_response(303)
            self.send_header("Location", "/entrar")
            self.end_headers()
            return

        if ruta in ("/", "/index.html"):
            return self._fichero("index.html")
        if ruta.startswith("/estatico/"):
            return self._fichero(ruta[len("/estatico/"):])

        if ruta == "/api/arranque":
            try:
                conf = _conf()
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            universo = {}
            for market, u2 in conf["universo"].items():
                universo[market] = {
                    "simbolos": u2["simbolos"], "timeframe": u2["timeframe"],
                    "desde": u2.get("desde"), "costes": conf["costes"].get(market, {}),
                }
            return self._json({
                "universo": universo,
                "estrategias": [{"id": k, "descripcion": v} for k, v in ESTRATEGIAS.items()],
                "backtest": conf["backtest"],
                "calidad": conf.get("calidad", {}),
                "alpaca": bool(os.environ.get("APCA_API_KEY_ID")
                               and os.environ.get("APCA_API_SECRET_KEY")),
                "autenticado": bool(AUTH["exige"]),
                "python": "%d.%d.%d" % sys.version_info[:3],
                "raiz_datos": str(_store(conf).root),
            })

        if ruta == "/api/vivo":
            try:
                return self._json({"agentes": vivo.listar(), "catalogo": vivo.catalogo()})
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        if ruta.startswith("/api/vivo/"):
            try:
                return self._json(vivo.detalle(ruta.split("/", 3)[3]))
            except Exception as e:
                return self._json({"error": str(e)}, 404)

        if ruta.startswith("/api/tareas/"):
            tid = ruta.split("/")[3]
            t = TAREAS.get(tid)
            if not t:
                return self._json({"error": "tarea desconocida"}, 404)
            return self._json(t.instantanea(int((q.get("desde") or ["0"])[0])))

        self.send_error(404)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        ruta = urlparse(self.path).path

        if ruta == "/entrar":
            return self._intento_entrada()

        if not self._autenticado():
            return self._json({"error": "sesión caducada", "entrar": True}, 401)

        if ruta not in ("/api/tareas", "/api/vivo/arrancar", "/api/vivo/parar",
                        "/api/vivo/borrar"):
            return self.send_error(404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            cuerpo = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "JSON inválido"}, 400)

        if ruta.startswith("/api/vivo/"):
            accion = ruta.rsplit("/", 1)[1]
            try:
                if accion == "arrancar":
                    return self._json(vivo.arrancar(cuerpo))
                if accion == "parar":
                    return self._json(vivo.parar(cuerpo.get("nombre") or ""))
                return self._json(vivo.borrar(cuerpo.get("nombre") or ""))
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        accion = cuerpo.get("accion")
        if accion not in ACCIONES:
            return self._json({"error": "acción desconocida: %s" % accion}, 400)
        t = lanzar(accion, cuerpo, ACCIONES[accion])
        return self._json({"id": t.id, "accion": accion}, 202)

    def _intento_entrada(self):
        cfg = AUTH["cfg"]
        if not AUTH["exige"] or not cfg:
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return
        espera = auth.bloqueado(self._ip())
        if espera > 0:
            return self._entrada("Demasiados intentos. Espera %d min."
                                 % max(1, round(espera / 60)), 429)
        n = min(int(self.headers.get("Content-Length") or 0), 4096)
        clave = _leer_formulario(self.rfile.read(n)).get("clave", "")
        if not auth.comprobar(clave, cfg):
            auth.anota_fallo(self._ip())
            log.warning("contraseña incorrecta desde %s", self._ip())
            return self._entrada("Contraseña incorrecta.", 401)

        auth.limpia_fallos(self._ip())
        galleta = ("sesion=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Strict%s"
                   % (auth.crear_sesion(cfg), auth.DURACION_SESION,
                      "; Secure" if self._https() else ""))
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", galleta)
        self.end_headers()


def _leer_formulario(datos: bytes) -> dict:
    from urllib.parse import parse_qsl
    return dict(parse_qsl(datos.decode("utf-8", "replace")))


def main() -> int:
    ap = argparse.ArgumentParser(description="Panel web del bot de compraventa")
    ap.add_argument("--puerto", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1",
                    help="dirección donde escuchar. 127.0.0.1 = sólo este equipo")
    ap.add_argument("--sin-navegador", action="store_true")
    a = ap.parse_args()

    if not RUTA_CONFIG.exists():
        print("No encuentro %s" % RUTA_CONFIG, file=sys.stderr)
        return 1

    cfg_auth, exige = auth.estado(a.host)
    if exige and not cfg_auth:
        print("Te niego el arranque: --host %s expone el panel fuera de este equipo\n"
              "y no hay contraseña definida. Cualquiera que dé con la dirección\n"
              "podría arrancar, pausar y borrar agentes.\n\n"
              "  python web/clave.py\n" % a.host, file=sys.stderr)
        return 1
    AUTH["cfg"], AUTH["exige"] = cfg_auth, exige

    _instalar_logging()
    vueltos = vivo.resucitar()
    if vueltos:
        log.info("agentes reanudados tras reinicio: %s", ", ".join(vueltos))
    vivo.iniciar_muestreador()

    puerto = a.puerto
    for intento in range(20):
        try:
            srv = ThreadingHTTPServer((a.host, puerto), Manejador)
            break
        except OSError:
            puerto += 1
    else:
        print("No hay puertos libres entre %d y %d" % (a.puerto, a.puerto + 20),
              file=sys.stderr)
        return 1

    visible = "127.0.0.1" if a.host in ("0.0.0.0", "::") else a.host
    url = "http://%s:%d/" % (visible, puerto)
    print("Panel en %s" % url)
    print("Acceso: %s" % ("con contraseña" if exige else
                          "sin contraseña (sólo este equipo)"))
    print("Ctrl-C para parar.")
    log.info("panel escuchando en %s:%d (contraseña: %s)", a.host, puerto,
             "sí" if exige else "no")
    if not a.sin_navegador and a.host in ("127.0.0.1", "localhost"):
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
