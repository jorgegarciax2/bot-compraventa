"""Operativa en vivo (papel): arrancar, parar y observar agentes.

Cada agente es un proceso aparte (`python -m agente papel`), no un hilo de este
servidor. Así sigue operando aunque cierres el navegador o pares el panel, y si
se cae, se cae él solo.

El agente guarda `estado.json` en cada tick, pero su curva de patrimonio es una
lista de números sin fecha. Por eso este módulo lleva su propio muestreador: cada
pocos segundos mira si el agente ha latido y, si ha latido, apunta el patrimonio
con la hora real en `serie.jsonl`. De ahí salen el gráfico y el resultado por día.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

RAIZ = Path(__file__).resolve().parent.parent
AGENTE = RAIZ / "agente-cartera"
EJECUCIONES = RAIZ / "ejecuciones"
PYTHON = RAIZ / ".venv" / "bin" / "python"

SEGUNDOS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600,
            "4h": 14400, "1d": 86400}
FUENTES = {
    "binance": "Cripto en tiempo real (API pública de Binance, sin claves).",
    "yahoo": "Acciones y ETFs en tiempo real (Yahoo Finance, sin claves).",
    "sintetica": "Ensayo: mercado generado que avanza deprisa. Para ver al "
                 "agente operar en minutos en vez de en días.",
}

sys.path.insert(0, str(AGENTE))

from agente.estrategias.catalogo import CATALOGO      # noqa: E402
from agente.core.metricas import resumen as resumen_metricas  # noqa: E402

DESCRIPCIONES = {
    "comprar_y_aguantar": "Compra todo lo permitido y no vuelve a tocar nada. "
                          "La referencia: si una estrategia no bate a esto, sobra.",
    "cruce_medias": "Dentro cuando la media rápida supera a la lenta. "
                    "Seguimiento de tendencia clásico.",
    "ruptura_canal": "Entra al romper máximos de N velas y sale al perder mínimos. "
                     "Momentum tipo Donchian.",
    "reversion_media": "Compra caídas, pero sólo si la tendencia larga es alcista. "
                       "El filtro evita comprar barato todo el camino hacia cero.",
    "tendencia_vol": "Tendencia dosificada por volatilidad: cuanto más vuela el "
                     "precio, menos peso. La más sensata del catálogo.",
    "azar": "Control negativo: decide a cara o cruz. Está para morirse y "
            "recordarte el listón.",
}


# ------------------------------------------------------------------- procesos
def _dir(nombre: str) -> Path:
    limpio = "".join(c for c in nombre if c.isalnum() or c in "-_") or "agente"
    return EJECUCIONES / limpio


def _leer_json(ruta: Path) -> Optional[dict]:
    if not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _pid_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def en_marcha(nombre: str) -> Optional[dict]:
    """Devuelve la ficha del proceso si el agente está operando ahora mismo."""
    p = _leer_json(_dir(nombre) / "proceso.json")
    if p and p.get("pid") and _pid_vivo(int(p["pid"])):
        return p
    return None


def listar() -> List[dict]:
    if not EJECUCIONES.exists():
        return []
    fuera = []
    for d in sorted(EJECUCIONES.iterdir()):
        if not d.is_dir():
            continue
        est = _leer_json(d / "estado.json") or {}
        lap = _leer_json(d / "LAPIDA.json")
        vit = est.get("vitales", {})
        cfg = est.get("config", {})
        cart = est.get("cartera", {})
        fuera.append({
            "nombre": d.name,
            "simbolo": cfg.get("simbolo"),
            "estrategia": cfg.get("estrategia"),
            "intervalo": cfg.get("intervalo"),
            "capital": cart.get("capital_inicial"),
            "equity": vit.get("equity"),
            "ticks": vit.get("ticks", 0),
            "vivo": bool(lap is None and vit.get("vivo", True)),
            "muerto": lap is not None,
            "causa": (lap or {}).get("vitales", {}).get("causa_muerte"),
            "operando": en_marcha(d.name) is not None,
        })
    return fuera


def arrancar(p: dict) -> dict:
    nombre = p.get("nombre") or "agente"
    d = _dir(nombre)
    if en_marcha(nombre):
        raise RuntimeError("«%s» ya está operando. Párale antes de volver a "
                           "arrancarlo." % nombre)
    lap = _leer_json(d / "LAPIDA.json")
    if lap and not p.get("reencarnar"):
        v = lap["vitales"]
        raise RuntimeError(
            "«%s» está muerto (causa: %s). %s  La muerte es definitiva: marca "
            "«empezar de cero» para lanzar un agente nuevo."
            % (nombre, v.get("causa_muerte"), v.get("detalle_muerte") or ""))

    d.mkdir(parents=True, exist_ok=True)
    fuente = p.get("fuente") or "binance"
    intervalo = p.get("intervalo") or "15m"

    argv = [str(PYTHON), "-u", "-m", "agente", "papel",
            "--dir", str(d),
            "--simbolo", str(p.get("simbolo") or "BTCEUR"),
            "--divisa", str(p.get("divisa") or "EUR"),
            "--capital", str(float(p.get("capital") or 1000)),
            "--intervalo", intervalo,
            "--fuente", fuente,
            "--estrategia", str(p.get("estrategia") or "tendencia_vol"),
            "--ruina", str(float(p.get("ruina") or 0.10)),
            "--max-dd", str(float(p.get("max_dd") or 0.50)),
            "--coste-vida", str(float(p.get("coste_vida") or 0.02)),
            "--max-exposicion", str(float(p.get("max_exposicion") or 0.95)),
            "--stop-loss", str(float(p.get("stop_loss") or 0.15)),
            "--trailing-stop", str(float(p.get("trailing_stop") or 0.25)),
            "--banda", str(float(p.get("banda") or 0.10)),
            "--comision-bps", str(float(p.get("comision_bps") or 10)),
            "--slippage-bps", str(float(p.get("slippage_bps") or 5)),
            "--minimo-operacion", str(float(p.get("minimo_operacion") or 10))]
    if fuente == "sintetica":
        argv += ["--velas", str(int(p.get("velas") or 3000)),
                 "--paso-seg", str(float(p.get("paso_seg") or 0.4)),
                 "--semilla", str(int(p.get("semilla") or 7))]
    if p.get("reencarnar"):
        argv.append("--reencarnar")
        for f in ("serie.jsonl", "salida.log"):
            (d / f).unlink(missing_ok=True)

    log = (d / "salida.log").open("a", encoding="utf-8")
    log.write("\n%s  $ %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(argv[3:])))
    log.flush()
    proc = subprocess.Popen(argv, cwd=str(AGENTE), stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    ficha = {"pid": proc.pid, "iniciado": time.time(), "argv": argv[1:],
             "deberia_operar": True,
             "intervalo": intervalo, "fuente": fuente,
             "paso_seg": float(p.get("paso_seg") or 0.4) if fuente == "sintetica" else None}
    (d / "proceso.json").write_text(json.dumps(ficha, indent=2), encoding="utf-8")

    time.sleep(1.2)                      # margen para que falle de forma visible
    if proc.poll() is not None:
        cola = (d / "salida.log").read_text(encoding="utf-8", errors="replace")[-1200:]
        raise RuntimeError("El agente ha terminado nada más arrancar:\n" + cola)
    return {"nombre": nombre, "pid": proc.pid}


def parar(nombre: str) -> dict:
    """Pausa: manda Ctrl-C, que el agente entiende como «guarda y para».

    No mata al agente: su estado queda en disco y puede continuar donde lo dejó.
    """
    ficha = en_marcha(nombre)
    if not ficha:
        return {"nombre": nombre, "parado": False, "motivo": "no estaba operando"}
    pid = int(ficha["pid"])
    try:
        os.kill(pid, signal.SIGINT)
    except OSError as e:
        return {"nombre": nombre, "parado": False, "motivo": str(e)}
    for _ in range(40):
        if not _pid_vivo(pid):
            break
        time.sleep(0.1)
    if _pid_vivo(pid):
        os.kill(pid, signal.SIGTERM)
    # Una pausa es deliberada: que un reinicio de la máquina no la deshaga.
    ficha["deberia_operar"] = False
    (_dir(nombre) / "proceso.json").write_text(json.dumps(ficha, indent=2),
                                               encoding="utf-8")
    return {"nombre": nombre, "parado": True}


def borrar(nombre: str) -> dict:
    """Elimina el directorio del agente. Sólo si no está operando."""
    if en_marcha(nombre):
        raise RuntimeError("«%s» está operando: párale antes de borrarlo." % nombre)
    d = _dir(nombre)
    if not d.exists():
        raise RuntimeError("No existe «%s»." % nombre)
    for f in sorted(d.iterdir()):
        if f.is_file():
            f.unlink()
    d.rmdir()
    return {"nombre": nombre, "borrado": True}


def resucitar() -> List[str]:
    """Tras un reinicio de la máquina, vuelve a lanzar los agentes que operaban.

    Sólo los que estaban operando cuando se fueron: si los pausaste tú, siguen
    pausados. Y nunca con --reencarnar, que borraría el historial.
    """
    if not EJECUCIONES.exists():
        return []
    vueltos = []
    for d in sorted(EJECUCIONES.iterdir()):
        if not d.is_dir():
            continue
        ficha = _leer_json(d / "proceso.json")
        if not ficha:
            continue
        # Sólo una pausa deliberada escribe False. Una ficha antigua sin la marca
        # es un agente que estaba operando: resucitarlo es lo correcto.
        if ficha.get("deberia_operar") is False:
            continue
        if ficha.get("pid") and _pid_vivo(int(ficha["pid"])):
            continue                                  # sigue vivo: nada que hacer
        if (d / "LAPIDA.json").exists():
            continue                                  # muerto es muerto
        argv = [a for a in (ficha.get("argv") or []) if a != "--reencarnar"]
        if not argv:
            continue
        try:
            log = (d / "salida.log").open("a", encoding="utf-8")
            log.write("\n%s  $ reanudado tras reinicio\n"
                      % time.strftime("%Y-%m-%d %H:%M:%S"))
            log.flush()
            proc = subprocess.Popen([str(PYTHON)] + argv, cwd=str(AGENTE),
                                    stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        except OSError:
            continue
        ficha["pid"] = proc.pid
        ficha["iniciado"] = time.time()
        ficha["deberia_operar"] = True       # deja la ficha sin ambigüedad
        (d / "proceso.json").write_text(json.dumps(ficha, indent=2), encoding="utf-8")
        vueltos.append(d.name)
    return vueltos


# ---------------------------------------------------------------- muestreador
_PARAR = threading.Event()


def _muestrear_uno(d: Path) -> None:
    est = _leer_json(d / "estado.json")
    if not est:
        return
    vit = est.get("vitales", {})
    tick = int(vit.get("ticks", 0))
    if tick <= 0:
        return

    serie = d / "serie.jsonl"
    ultimo = -1
    if serie.exists():
        try:
            with serie.open("rb") as f:                 # última línea sin leer todo
                f.seek(0, os.SEEK_END)
                fin = f.tell()
                salto = min(fin, 4096)
                f.seek(fin - salto)
                lineas = [l for l in f.read().decode("utf-8", "replace").splitlines() if l.strip()]
            if lineas:
                ultimo = int(json.loads(lineas[-1]).get("tick", -1))
        except (OSError, ValueError, json.JSONDecodeError):
            ultimo = -1
    if tick == ultimo:
        return

    cart = est.get("cartera", {})
    cfg = est.get("config", {})
    simbolo = cfg.get("simbolo", "")
    pos = (cart.get("posiciones") or {}).get(simbolo, {})
    cantidad = float(pos.get("cantidad") or 0.0)
    equity = float(vit.get("equity") or 0.0)
    caja = float(cart.get("caja") or 0.0)
    # El precio de marcado no se guarda, pero se deduce: equity = caja + cantidad × precio.
    precio = ((equity - caja) / cantidad) if cantidad > 1e-12 else None

    with serie.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": time.time(), "tick": tick, "equity": round(equity, 6),
            "caja": round(caja, 6), "cantidad": cantidad,
            "precio": None if precio is None else round(precio, 8),
            "drawdown": round(float(vit.get("drawdown") or 0.0), 6),
        }) + "\n")


def _bucle_muestreo() -> None:
    while not _PARAR.wait(3.0):
        if not EJECUCIONES.exists():
            continue
        for d in EJECUCIONES.iterdir():
            if d.is_dir():
                try:
                    _muestrear_uno(d)
                except Exception:                       # el panel nunca debe caerse por esto
                    pass


def iniciar_muestreador() -> None:
    threading.Thread(target=_bucle_muestreo, daemon=True).start()


# -------------------------------------------------------------------- lectura
def _cola(ruta: Path, n: int) -> List[dict]:
    if not ruta.exists():
        return []
    try:
        lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    fuera = []
    for l in lineas[-n:]:
        l = l.strip()
        if not l:
            continue
        try:
            fuera.append(json.loads(l))
        except json.JSONDecodeError:
            pass
    return fuera


def _por_dias(serie: List[dict]) -> List[dict]:
    """Resultado día a día, que es como quiere mirarse esto."""
    dias: Dict[str, dict] = {}
    for m in serie:
        clave = time.strftime("%Y-%m-%d", time.localtime(m["ts"]))
        d = dias.get(clave)
        if d is None:
            dias[clave] = {"dia": clave, "apertura": m["equity"], "cierre": m["equity"],
                           "maximo": m["equity"], "minimo": m["equity"],
                           "tick0": m["tick"], "tick1": m["tick"]}
        else:
            d["cierre"] = m["equity"]
            d["maximo"] = max(d["maximo"], m["equity"])
            d["minimo"] = min(d["minimo"], m["equity"])
            d["tick1"] = m["tick"]
    fuera = []
    previo = None
    for clave in sorted(dias):
        d = dias[clave]
        base = previo if previo is not None else d["apertura"]
        d["base"] = base
        d["ticks"] = d.pop("tick1") - d.pop("tick0") + 1
        d["pnl"] = d["cierre"] - base
        d["pnl_pct"] = (d["cierre"] / base - 1.0) if base else 0.0
        previo = d["cierre"]
        fuera.append(d)
    return fuera


def detalle(nombre: str) -> dict:
    d = _dir(nombre)
    if not d.exists():
        raise RuntimeError("No existe el agente «%s»." % nombre)

    est = _leer_json(d / "estado.json")
    lap = _leer_json(d / "LAPIDA.json")
    ficha = en_marcha(nombre)
    serie = _cola(d / "serie.jsonl", 6000)
    eventos = _cola(d / "diario.jsonl", 400)

    if not est:
        return {"nombre": nombre, "arrancando": True, "operando": ficha is not None,
                "serie": [], "eventos": eventos, "dias": [],
                "salida": (d / "salida.log").read_text(encoding="utf-8", errors="replace")[-3000:]
                if (d / "salida.log").exists() else ""}

    cfg = est.get("config", {})
    cart = est.get("cartera", {})
    vit = est.get("vitales", {})
    simbolo = cfg.get("simbolo", "")
    pos = (cart.get("posiciones") or {}).get(simbolo, {}) or {}

    capital = float(cart.get("capital_inicial") or 0.0)
    equity = float(vit.get("equity") or capital)
    caja = float(cart.get("caja") or 0.0)
    cantidad = float(pos.get("cantidad") or 0.0)
    valor_pos = max(0.0, equity - caja)
    precio = (valor_pos / cantidad) if cantidad > 1e-12 else None
    precio_medio = float(pos.get("precio_medio") or 0.0)

    hoy = time.strftime("%Y-%m-%d")
    de_hoy = [m for m in serie if time.strftime("%Y-%m-%d", time.localtime(m["ts"])) == hoy]
    dias = _por_dias(serie)
    base_hoy = next((x["base"] for x in dias if x["dia"] == hoy), None)

    curva = est.get("curva_equity") or []
    metricas = resumen_metricas(curva, _ticks_anio(cfg.get("intervalo", "1h")),
                                est.get("operaciones") or []) if len(curva) >= 2 else {}

    intervalo_seg = SEGUNDOS.get(cfg.get("intervalo", "1h"), 3600)
    if ficha and ficha.get("paso_seg"):        # en ensayo manda --paso-seg
        intervalo_seg = float(ficha["paso_seg"])
    guardado = float(est.get("guardado") or 0)

    return {
        "nombre": nombre,
        "operando": ficha is not None,
        "pid": (ficha or {}).get("pid"),
        "fuente": (ficha or {}).get("fuente"),
        "muerto": lap is not None or not vit.get("vivo", True),
        "causa_muerte": vit.get("causa_muerte") or (lap or {}).get("vitales", {}).get("causa_muerte"),
        "detalle_muerte": vit.get("detalle_muerte") or (lap or {}).get("vitales", {}).get("detalle_muerte"),
        "config": cfg,
        "simbolo": simbolo,
        "divisa": cart.get("divisa", "EUR"),
        "capital_inicial": capital,
        "equity": equity,
        "caja": caja,
        "posicion": {
            "cantidad": cantidad, "precio_medio": precio_medio,
            "valor": valor_pos, "precio": precio,
            "pnl_no_realizado": (precio - precio_medio) * cantidad if (precio and cantidad) else 0.0,
            "maximo_favorable": float(pos.get("maximo_favorable") or 0.0),
        },
        "exposicion": (valor_pos / equity) if equity > 0 else 0.0,
        "pnl_total": equity - capital,
        "pnl_total_pct": (equity / capital - 1.0) if capital else 0.0,
        "pnl_hoy": (equity - base_hoy) if base_hoy else 0.0,
        "pnl_hoy_pct": (equity / base_hoy - 1.0) if base_hoy else 0.0,
        "ticks_hoy": (de_hoy[-1]["tick"] - de_hoy[0]["tick"] + 1) if de_hoy else 0,
        "ticks": int(vit.get("ticks") or 0),
        "drawdown": float(vit.get("drawdown") or 0.0),
        "equity_maximo": float(vit.get("equity_maximo") or capital),
        "umbral_ruina": capital * float((cfg.get("reglas_vida") or {}).get("ruina_relativa", 0.10)),
        "max_drawdown_permitido": float((cfg.get("reglas_vida") or {}).get("max_drawdown", 0.50)),
        "comisiones": float(cart.get("comisiones_pagadas") or 0.0),
        "coste_vida": float(cart.get("coste_vida_pagado") or 0.0),
        "pnl_realizado": float(cart.get("pnl_realizado") or 0.0),
        "n_operaciones": int(cart.get("operaciones") or 0),
        "operaciones": (est.get("operaciones") or [])[-200:],
        "metricas": metricas,
        "serie": [[int(m["ts"] * 1000), m["equity"]] for m in serie],
        "dias": dias,
        "eventos": eventos[-120:],
        "guardado": guardado,
        "segundos_desde_tick": max(0.0, time.time() - guardado) if guardado else None,
        "intervalo_seg": intervalo_seg,
    }


def _ticks_anio(intervalo: str) -> float:
    from agente.core.motor import TICKS_POR_ANIO
    return TICKS_POR_ANIO.get(intervalo, 8760)


def catalogo() -> dict:
    return {
        "estrategias": [{"id": k, "descripcion": DESCRIPCIONES.get(k, "")}
                        for k in sorted(CATALOGO)],
        "fuentes": [{"id": k, "descripcion": v} for k, v in FUENTES.items()],
        "intervalos": sorted(SEGUNDOS, key=lambda k: SEGUNDOS[k]),
    }
