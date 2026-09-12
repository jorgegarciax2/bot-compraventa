# tbot — Fase 0

Fundamentos del sistema de trading automatizado: **capa de datos, validación de
calidad y backtester**. Todavía no hay estrategias de verdad ni ejecución real:
eso es la fase 1 en adelante. Lo que hay aquí es la base sobre la que se puede
medir honestamente si una estrategia funciona.

## Qué incluye

| Módulo | Qué hace |
|---|---|
| `data/schema.py` | Esquema canónico de velas, común a cripto y acciones |
| `data/sources/` | Cripto (ccxt), acciones (Alpaca) y sintética (para tests) |
| `data/store.py` | Almacén Parquet particionado + consultas DuckDB, con lectura *point-in-time* |
| `data/quality.py` | Validadores: huecos, OHLC incoherente, precios imposibles, saltos anómalos |
| `data/ingest.py` | Descarga incremental, reanudable e idempotente |
| `features/indicators.py` | SMA, EMA, RSI, ATR, Bollinger, Donchian, momentum, z-score |
| `backtest/engine.py` | Motor event-driven sin lookahead, ejecución en la barra siguiente |
| `backtest/costs.py` | Comisión + slippage + spread |
| `backtest/metrics.py` | CAGR, Sharpe, Sortino, max drawdown, Calmar, profit factor |
| `strategies/basicas.py` | Referencias: comprar y mantener, equiponderado, cruce de medias |

## Instalación

```bash
cd tbot
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Uso

```bash
# Descargar histórico (se puede interrumpir y relanzar sin duplicar nada)
tbot ingest crypto
tbot ingest crypto --symbols BTC/USDT ETH/USDT --desde 2020-01-01

# Ver qué hay en el almacén
tbot info

# Validar la calidad antes de fiarse de un backtest
tbot validate crypto

# Backtest
tbot backtest crypto --estrategia comprar_y_mantener
tbot backtest crypto --estrategia cruce_medias --desde 2022-01-01
tbot backtest crypto --estrategia cruce_medias --sin-costes   # cuánto se lleva la fricción
```

Para acciones hacen falta credenciales de Alpaca en el entorno (nunca en el repositorio):

```bash
export APCA_API_KEY_ID=...
export APCA_API_SECRET_KEY=...
tbot ingest equity
```

## Verificación

```bash
pytest -q                                  # 46 tests, sin red
python scripts/verificar_puerta_fase0.py   # la puerta, contra datos reales de BTC
```

## Las tres reglas que sostienen todo esto

**1. La estrategia no puede ver el futuro.** No es una convención: el `Context`
que recibe la estrategia solo contiene datos hasta la barra actual, porque
físicamente no tiene el resto. `test_el_pasado_no_depende_del_futuro` lo
comprueba a nivel de sistema completo: ejecutar el backtest sobre media serie
debe dar exactamente la misma equity que sobre la serie entera.

**2. La señal se calcula al cierre de `t` y se ejecuta en la apertura de `t+1`.**
Cuando ves el cierre ya no puedes operar a ese precio. Los backtests que ejecutan
al mismo close que generó la señal inventan rentabilidad que no existe.

**3. Los costes se pagan siempre.** Comisión, slippage y medio spread, en cada
operación y desde el primer backtest. La mayoría de estrategias que funcionan en
papel mueren aquí, y es mejor que mueran ahora.

## La puerta de la fase 0

> El backtester debe reproducir comprar y mantener con error despreciable.

Si el motor no sabe replicar lo trivial, no sirve para medir lo complejo. Está
cubierta por `test_puerta_fase0_replica_buy_and_hold` (datos sintéticos,
tolerancia relativa 1e-9) y por `scripts/verificar_puerta_fase0.py` (BTC real).

## Siguiente fase

Fase 1: las tres estrategias base (momentum, reversión a la media, breakout de
volatilidad), la capa de riesgo completa (sizing por ATR, stops, límites de
correlación, kill switch) y validación walk-forward. La puerta de esa fase pide
Sharpe > 1 y drawdown < 25 % **fuera de muestra**, en dos regímenes de mercado
distintos, y que el resultado no se desmorone al mover un parámetro un 10 %.
