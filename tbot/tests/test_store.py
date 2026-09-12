import pandas as pd

from tbot.data.store import ParquetStore, symbol_a_ruta


def test_ruta_segura():
    assert symbol_a_ruta("BTC/USDT") == "BTC-USDT"


def test_escribir_y_leer(tmp_path, serie):
    st = ParquetStore(tmp_path)
    n = st.write(serie, "synthetic", "1d", "SYN/USD")
    assert n == len(serie)
    leido = st.read("synthetic", "1d", "SYN/USD")
    assert len(leido) == len(serie)
    pd.testing.assert_series_equal(leido["close"], serie["close"], check_names=False)


def test_escritura_idempotente(tmp_path, serie):
    """Reingestar lo mismo no debe duplicar ni una vela."""
    st = ParquetStore(tmp_path)
    st.write(serie, "synthetic", "1d", "SYN/USD")
    nuevas = st.write(serie, "synthetic", "1d", "SYN/USD")
    assert nuevas == 0
    assert len(st.read("synthetic", "1d", "SYN/USD")) == len(serie)


def test_ingesta_incremental(tmp_path, serie):
    st = ParquetStore(tmp_path)
    st.write(serie.iloc[:100], "synthetic", "1d", "SYN/USD")
    assert st.last_timestamp("synthetic", "1d", "SYN/USD") == serie["ts"].iloc[99]
    st.write(serie.iloc[100:], "synthetic", "1d", "SYN/USD")
    assert len(st.read("synthetic", "1d", "SYN/USD")) == len(serie)


def test_filtro_temporal(tmp_path, serie):
    st = ParquetStore(tmp_path)
    st.write(serie, "synthetic", "1d", "SYN/USD")
    desde, hasta = serie["ts"].iloc[10], serie["ts"].iloc[20]
    out = st.read("synthetic", "1d", "SYN/USD", start=desde, end=hasta)
    assert len(out) == 11 and out["ts"].min() == desde and out["ts"].max() == hasta


def test_as_of_point_in_time(tmp_path, serie):
    """Leer 'as of' una fecha anterior a la ingesta no debe devolver nada:
    es la garantía de que se puede auditar qué sabíamos y cuándo."""
    st = ParquetStore(tmp_path)
    st.write(serie, "synthetic", "1d", "SYN/USD")
    antes = serie["ingested_at"].min() - pd.Timedelta(days=1)
    assert st.read("synthetic", "1d", "SYN/USD", as_of=antes).empty
    assert len(st.read("synthetic", "1d", "SYN/USD", as_of=pd.Timestamp.now(tz="UTC"))) == len(serie)


def test_almacen_vacio(tmp_path):
    st = ParquetStore(tmp_path)
    assert st.read("synthetic", "1d", "NADA").empty
    assert st.last_timestamp("synthetic", "1d", "NADA") is None
    assert st.info().empty
