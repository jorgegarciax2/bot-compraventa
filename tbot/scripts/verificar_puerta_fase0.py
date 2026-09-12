#!/usr/bin/env python3
"""PUERTA DE LA FASE 0, con datos reales.

Baja el histórico real de BTC y comprueba que el backtester reproduce comprar y
mantener con error despreciable. Con datos sintéticos ya se comprueba en los
tests; esto lo repite contra el mercado de verdad, con sus huecos y sus rarezas.

    python scripts/verificar_puerta_fase0.py

Requiere conexión a Binance. No usa claves de API: solo datos públicos.
"""
from __future__ import annotations

import sys

import pandas as pd

from tbot.backtest.costs import CostModel
from tbot.backtest.engine import Backtester
from tbot.data import quality
from tbot.data.sources.crypto_ccxt import CryptoSource
from tbot.strategies.basicas import ComprarYMantener

SIMBOLO = "BTC/USDT"
DESDE = "2019-01-01"
TOLERANCIA = 1e-6


def main() -> int:
    print(f"Descargando {SIMBOLO} desde {DESDE} ...")
    src = CryptoSource("binance")
    df = src.fetch_ohlcv(SIMBOLO, "1d", pd.Timestamp(DESDE, tz="UTC"))
    print(f"  {len(df)} velas [{df['ts'].min()} .. {df['ts'].max()}]\n")

    print("Validando calidad de los datos ...")
    rep = quality.validar(df, SIMBOLO, "1d")
    print(rep, "\n")
    if not rep.ok:
        print("FALLA: los datos no pasan la validación.")
        return 1

    print("Ejecutando comprar y mantener sin costes ...")
    res = Backtester(costes=CostModel.sin_costes(), capital_inicial=10_000.0).run(
        {SIMBOLO: df}, ComprarYMantener(), timeframe="1d"
    )

    entrada = float(df["open"].iloc[1])   # la señal es del cierre de la barra 0
    salida = float(df["close"].iloc[-1])
    esperado = salida / entrada - 1.0
    obtenido = res.metricas["retorno_total"]
    error = abs(obtenido - esperado)

    print(f"  entrada (apertura barra 1): {entrada:,.2f}")
    print(f"  salida  (cierre final):     {salida:,.2f}")
    print(f"  retorno esperado:           {esperado:>12.8%}")
    print(f"  retorno del backtester:     {obtenido:>12.8%}")
    print(f"  error absoluto:             {error:.2e}\n")

    if error > TOLERANCIA:
        print(f"FALLA: error {error:.2e} por encima de la tolerancia {TOLERANCIA:.0e}.")
        return 1

    print("PUERTA DE FASE 0 SUPERADA: el backtester replica el mercado real.\n")

    print("Mismo activo, ahora con costes reales de Binance:")
    con_costes = Backtester(
        costes=CostModel(comision_bps=10, slippage_bps=5, spread_bps=2),
        capital_inicial=10_000.0,
    ).run({SIMBOLO: df}, ComprarYMantener(), timeframe="1d")
    print(con_costes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
