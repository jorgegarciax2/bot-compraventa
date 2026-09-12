"""Interfaz de línea de comandos: `tbot <comando>`."""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from tbot import config as cfg
from tbot.data import quality
from tbot.data.ingest import ingestar
from tbot.data.store import ParquetStore


def _log(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


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
    raise ValueError(f"mercado desconocido: {market}")


def cmd_ingest(a) -> int:
    conf = cfg.cargar(a.config)
    store = ParquetStore(conf["paths"]["data_root"])
    u = conf["universo"][a.market]
    symbols = a.symbols or u["simbolos"]
    res = ingestar(_fuente(a.market, conf), store, symbols,
                   a.timeframe or u["timeframe"], a.desde or u["desde"])
    print(res.to_string(index=False))
    return 0 if not res["estado"].str.startswith("ERROR").any() else 1


def cmd_info(a) -> int:
    conf = cfg.cargar(a.config)
    df = ParquetStore(conf["paths"]["data_root"]).info()
    print("Almacén vacío." if df.empty else df.to_string(index=False))
    return 0


def cmd_validate(a) -> int:
    conf = cfg.cargar(a.config)
    store = ParquetStore(conf["paths"]["data_root"])
    u = conf["universo"][a.market]
    tf = a.timeframe or u["timeframe"]
    symbols = a.symbols or store.symbols(a.market, tf) or u["simbolos"]
    q = conf.get("calidad", {})
    fallos = 0
    for s in symbols:
        rep = quality.validar(
            store.read(a.market, tf, s), s, tf,
            max_gap_ratio=q.get("max_gap_ratio", 0.02),
            max_retorno_barra=q.get("max_retorno_barra", 0.50),
        )
        print(rep, "\n")
        fallos += (not rep.ok)
    print(f"{len(symbols) - fallos}/{len(symbols)} símbolos válidos")
    return 1 if fallos else 0


def cmd_backtest(a) -> int:
    from tbot.backtest.costs import CostModel
    from tbot.backtest.engine import Backtester
    from tbot.strategies.basicas import ComprarYMantener, CruceMedias, Liquidez, PesosIguales

    conf = cfg.cargar(a.config)
    store = ParquetStore(conf["paths"]["data_root"])
    u = conf["universo"][a.market]
    tf = a.timeframe or u["timeframe"]
    symbols = a.symbols or u["simbolos"]

    datos = {s: df for s, df in store.read_many(a.market, tf, symbols, a.desde, a.hasta).items()
             if not df.empty}
    if not datos:
        print("No hay datos. Ejecuta primero: tbot ingest", file=sys.stderr)
        return 1

    estrategias = {"comprar_y_mantener": ComprarYMantener, "cruce_medias": CruceMedias,
                   "liquidez": Liquidez, "pesos_iguales": PesosIguales}
    if a.estrategia not in estrategias:
        print(f"Estrategia desconocida. Opciones: {list(estrategias)}", file=sys.stderr)
        return 1

    c = conf["costes"][a.market]
    bt = Backtester(
        costes=CostModel.sin_costes() if a.sin_costes
        else CostModel(c["comision_bps"], c["slippage_bps"], c["spread_bps"]),
        capital_inicial=conf["backtest"]["capital_inicial"],
        banda_rebalanceo=0.0 if a.rebalanceo_exacto
        else conf["backtest"].get("banda_rebalanceo", 0.0),
    )
    res = bt.run(datos, estrategias[a.estrategia](), timeframe=tf, market=a.market)
    print(f"\nSímbolos: {', '.join(datos)}")
    print(f"Periodo:  {res.equity.index[0]} .. {res.equity.index[-1]}")
    print(f"Capital:  {res.capital_inicial:,.2f} -> {res.equity.iloc[-1]:,.2f}\n")
    print(res)
    if a.guardar:
        res.equity.to_csv(a.guardar)
        print(f"\nEquity guardada en {a.guardar}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tbot", description="Sistema de trading automatizado")
    p.add_argument("-c", "--config", default="config/config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def comun(sp):
        sp.add_argument("market", choices=["crypto", "equity", "synthetic"])
        sp.add_argument("--symbols", nargs="+")
        sp.add_argument("--timeframe")

    s = sub.add_parser("ingest", help="descargar y almacenar velas")
    comun(s); s.add_argument("--desde"); s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("info", help="inventario del almacén")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("validate", help="validar calidad de los datos")
    comun(s); s.set_defaults(func=cmd_validate)

    s = sub.add_parser("backtest", help="ejecutar un backtest")
    comun(s)
    s.add_argument("--estrategia", default="comprar_y_mantener")
    s.add_argument("--desde"); s.add_argument("--hasta")
    s.add_argument("--sin-costes", action="store_true",
                   help="desactiva comisiones y slippage (solo para diagnóstico)")
    s.add_argument("--rebalanceo-exacto", action="store_true",
                   help="ignora la banda de rebalanceo y persigue el peso exacto")
    s.add_argument("--guardar", help="CSV donde volcar la curva de equity")
    s.set_defaults(func=cmd_backtest)

    a = p.parse_args(argv)
    _log(a.verbose)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
