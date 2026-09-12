import numpy as np
import pandas as pd
import pytest

from tbot.backtest import metrics


def test_max_drawdown_conocido():
    eq = pd.Series([100, 120, 60, 80, 130], dtype=float)
    assert metrics.max_drawdown(eq) == pytest.approx(-0.5)


def test_sin_drawdown():
    assert metrics.max_drawdown(pd.Series([1, 2, 3, 4], dtype=float)) == 0.0


def test_retorno_y_cagr():
    idx = pd.date_range("2022-01-01", periods=366, freq="D", tz="UTC")
    eq = pd.Series(np.linspace(100, 200, 366), index=idx)
    m = metrics.calcular(eq, timeframe="1d")
    assert m["retorno_total"] == pytest.approx(1.0)
    assert m["cagr"] == pytest.approx(1.0, rel=0.02)


def test_sharpe_de_serie_sin_riesgo_es_enorme():
    idx = pd.date_range("2022-01-01", periods=365, freq="D", tz="UTC")
    eq = pd.Series(100 * 1.0002 ** np.arange(365), index=idx)
    assert metrics.calcular(eq, timeframe="1d")["sharpe"] > 50


def test_periodos_por_anyo():
    assert metrics.periodos_anyo("1d", "crypto") == 365
    assert metrics.periodos_anyo("1d", "equity") == 252


def test_serie_corta_no_revienta():
    assert "error" in metrics.calcular(pd.Series([100.0]))
