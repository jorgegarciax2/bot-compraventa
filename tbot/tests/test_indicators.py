import numpy as np
import pandas as pd

from tbot.features import indicators as ind


def test_sma_valor_conocido():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert ind.sma(s, 3).iloc[-1] == 4.0
    assert pd.isna(ind.sma(s, 3).iloc[1])


def test_rsi_en_rango(serie):
    r = ind.rsi(serie["close"], 14)
    assert r.between(0, 100).all()


def test_rsi_tendencia_alcista_pura():
    s = pd.Series(np.arange(1, 100), dtype=float)
    assert ind.rsi(s, 14).iloc[-1] > 95


def test_atr_positivo(serie):
    a = ind.atr(serie["high"], serie["low"], serie["close"], 14).dropna()
    assert (a > 0).all()


def test_donchian_no_usa_barra_actual(serie):
    """El canal debe excluir la barra actual: si no, cualquier breakout se
    'detecta' con el dato que lo provoca y la estrategia parece infalible."""
    d = ind.donchian(serie["high"], serie["low"], 20)
    i = 100
    esperado = serie["high"].iloc[i - 20 : i].max()
    assert np.isclose(d["techo"].iloc[i], esperado)


def test_indicadores_no_miran_al_futuro(serie):
    """Recortar la serie no puede cambiar los valores pasados de un indicador."""
    corte = 200
    for f in (lambda s: ind.sma(s, 20), lambda s: ind.ema(s, 20),
              lambda s: ind.rsi(s, 14), lambda s: ind.momentum(s, 10)):
        completo = f(serie["close"]).iloc[:corte]
        truncado = f(serie["close"].iloc[:corte])
        pd.testing.assert_series_equal(completo, truncado)
