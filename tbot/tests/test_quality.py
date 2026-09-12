import pandas as pd
import pytest

from tbot.data import quality


def test_datos_limpios(serie):
    rep = quality.validar(serie, "SYN/USD", "1d")
    assert rep.ok, str(rep)


def test_detecta_huecos(serie):
    roto = serie.drop(serie.index[50:120]).reset_index(drop=True)
    rep = quality.validar(roto, "SYN/USD", "1d")
    assert not rep.ok
    assert any(i.code == "huecos" for i in rep.issues)


def test_detecta_ohlc_incoherente(serie):
    malo = serie.copy()
    malo.loc[10, "high"] = malo.loc[10, "low"] * 0.5
    rep = quality.validar(malo, "SYN/USD", "1d")
    assert not rep.ok
    assert any(i.code in ("high_incoherente", "high_menor_low") for i in rep.issues)


def test_detecta_precio_no_positivo(serie):
    malo = serie.copy()
    malo.loc[5, "close"] = 0.0
    rep = quality.validar(malo, "SYN/USD", "1d")
    assert not rep.ok
    assert any(i.code == "precio_no_positivo" for i in rep.issues)


def test_detecta_salto_extremo(serie):
    """Un split sin ajustar se ve exactamente así."""
    malo = serie.copy()
    malo.loc[100:, ["open", "high", "low", "close"]] /= 4.0
    rep = quality.validar(malo, "SYN/USD", "1d")
    assert any(i.code == "retorno_extremo" for i in rep.issues)


def test_vacio_es_error():
    from tbot.data.schema import empty_frame
    rep = quality.validar(empty_frame(), "X", "1d")
    assert not rep.ok and rep.issues[0].code == "vacio"
