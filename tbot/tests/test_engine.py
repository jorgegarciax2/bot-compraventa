"""Tests del motor. El primero es la PUERTA DE LA FASE 0."""
import numpy as np
import pandas as pd
import pytest

from tbot.backtest.costs import CostModel
from tbot.backtest.engine import Backtester, Context, Strategy
from tbot.strategies.basicas import ComprarYMantener, CruceMedias, Liquidez


# ---------------------------------------------------------- PUERTA DE FASE 0
def test_puerta_fase0_replica_buy_and_hold(datos, serie):
    """PUERTA DE FASE 0.

    Sin costes, comprar y mantener debe rendir exactamente lo mismo que el activo
    entre el precio de entrada real (apertura de la barra 1, porque la señal se
    emite al cierre de la barra 0) y el cierre final.

    Si el motor no sabe replicar lo trivial, no sirve para medir lo complejo.
    """
    bt = Backtester(costes=CostModel.sin_costes(), capital_inicial=10_000.0)
    res = bt.run(datos, ComprarYMantener(), timeframe="1d")

    precio_entrada = serie["open"].iloc[1]
    precio_salida = serie["close"].iloc[-1]
    esperado = precio_salida / precio_entrada - 1.0

    assert res.metricas["retorno_total"] == pytest.approx(esperado, rel=1e-9), (
        f"obtenido {res.metricas['retorno_total']:.10f} vs esperado {esperado:.10f}"
    )


def test_buy_and_hold_no_sobreopera(datos):
    """Un peso constante no debe generar más de una operación: la de entrada.
    Si el motor rebalancea contra sí mismo, sangra comisiones de la nada."""
    bt = Backtester(costes=CostModel.sin_costes())
    res = bt.run(datos, ComprarYMantener(), timeframe="1d")
    assert len(res.trades) == 1


def test_liquidez_mantiene_capital(datos):
    bt = Backtester(capital_inicial=10_000.0)
    res = bt.run(datos, Liquidez(), timeframe="1d")
    assert res.equity.nunique() == 1
    assert res.equity.iloc[-1] == 10_000.0
    assert len(res.trades) == 0


# ------------------------------------------------------------------- costes
def test_los_costes_restan(datos):
    sin = Backtester(costes=CostModel.sin_costes()).run(datos, CruceMedias(), timeframe="1d")
    con = Backtester(costes=CostModel(10, 5, 2)).run(datos, CruceMedias(), timeframe="1d")
    assert con.equity.iloc[-1] < sin.equity.iloc[-1]
    assert con.trades["comision"].sum() > 0


def test_precio_ejecucion_penaliza_ambos_lados():
    c = CostModel(comision_bps=10, slippage_bps=5, spread_bps=2)
    assert c.precio_ejecucion(100.0, 1) > 100.0    # compras más caro
    assert c.precio_ejecucion(100.0, -1) < 100.0   # vendes más barato
    assert c.comision(1000.0) == pytest.approx(1.0)


# ------------------------------------------------------------- anti-lookahead
def test_la_estrategia_no_ve_el_futuro(datos, serie):
    """El Contexto no puede entregar ni una vela por delante de la barra actual."""
    vistos = []

    class Espia(Strategy):
        nombre = "espia"

        def target_weights(self, ctx: Context):
            h = ctx.history("SYN/USD")
            vistos.append((ctx.now, h["close"].index[-1], len(h)))
            return {"SYN/USD": 0.0}

    Backtester().run(datos, Espia(), timeframe="1d")
    for ahora, ultima_vista, n in vistos:
        assert ultima_vista == ahora, "la estrategia vio una vela futura"
    assert [n for _, _, n in vistos] == list(range(1, len(serie)))


def test_ejecucion_en_la_barra_siguiente(datos, serie):
    """La orden emitida en la barra 0 se ejecuta a la APERTURA de la barra 1."""
    bt = Backtester(costes=CostModel.sin_costes())
    res = bt.run(datos, ComprarYMantener(), timeframe="1d")
    t0 = res.trades.iloc[0]
    assert t0["ts"] == serie["ts"].iloc[1]
    assert t0["precio"] == pytest.approx(serie["open"].iloc[1])


def test_una_estrategia_con_futuro_no_puede_construirse(datos):
    """Comprobación explícita: pedir más historia de la que hay devuelve solo
    lo disponible, nunca datos posteriores."""
    class Tramposa(Strategy):
        nombre = "tramposa"

        def target_weights(self, ctx: Context):
            assert len(ctx.history("SYN/USD", 10_000)) <= len(ctx.history("SYN/USD"))
            return {}

    Backtester().run(datos, Tramposa(), timeframe="1d")


# -------------------------------------------------------------- restricciones
def test_sin_apalancamiento(datos):
    class Avariciosa(Strategy):
        nombre = "avariciosa"

        def target_weights(self, ctx):
            return {s: 5.0 for s in ctx.symbols}

    bt = Backtester(costes=CostModel.sin_costes(), max_exposicion=1.0)
    res = bt.run(datos, Avariciosa(), timeframe="1d")
    # Con exposición tope de 1.0 el resultado es el de comprar y mantener.
    ref = bt.run(datos, ComprarYMantener(), timeframe="1d")
    assert res.metricas["retorno_total"] == pytest.approx(ref.metricas["retorno_total"], rel=1e-9)


def test_cortos_bloqueados_por_defecto(datos):
    class Bajista(Strategy):
        nombre = "bajista"

        def target_weights(self, ctx):
            return {s: -1.0 for s in ctx.symbols}

    res = Backtester().run(datos, Bajista(), timeframe="1d")
    assert len(res.trades) == 0  # el peso negativo se recorta a 0


def test_simbolo_desconocido_falla(datos):
    class Rara(Strategy):
        nombre = "rara"

        def target_weights(self, ctx):
            return {"NO/EXISTE": 1.0}

    with pytest.raises(KeyError):
        Backtester().run(datos, Rara(), timeframe="1d")


# ------------------------------------------------------------------ multiactivo
def test_multiactivo_reparte(serie):
    from tbot.data.sources.synthetic import SyntheticSource

    src = SyntheticSource(seed=3)
    datos = {
        s: src.fetch_ohlcv(s, "1d", pd.Timestamp("2022-01-01", tz="UTC"),
                           pd.Timestamp("2023-01-01", tz="UTC"))
        for s in ("A/USD", "B/USD", "C/USD")
    }
    res = Backtester(costes=CostModel.sin_costes()).run(datos, ComprarYMantener(), timeframe="1d")
    assert len(res.trades) == 3
    # Cada posición arranca con ~1/3 del capital.
    notional = res.trades["notional"].abs()
    assert (notional / notional.sum()).round(3).nunique() == 1


def test_huecos_no_rompen_el_motor(datos):
    """Un símbolo sin vela en una fecha no debe operarse en ella ni romper nada."""
    from tbot.data.sources.synthetic import SyntheticSource

    src = SyntheticSource(seed=11)
    a = src.fetch_ohlcv("A/USD", "1d", pd.Timestamp("2022-01-01", tz="UTC"),
                        pd.Timestamp("2022-06-01", tz="UTC"))
    b = src.fetch_ohlcv("B/USD", "1d", pd.Timestamp("2022-01-01", tz="UTC"),
                        pd.Timestamp("2022-06-01", tz="UTC")).drop(index=range(30, 60))
    res = Backtester().run({"A/USD": a, "B/USD": b}, ComprarYMantener(), timeframe="1d")
    assert res.equity.notna().all()
    assert np.isfinite(res.equity.iloc[-1])


def test_rebalancear_genera_operaciones_y_comisiones(serie):
    """El equiponderado rebalanceado opera en cada barra y paga por ello.

    Ojo: NO se afirma que termine por debajo de comprar y mantener. Rebalancear
    entre activos volátiles captura parte de esa volatilidad y puede ganarle
    incluso pagando comisiones. Un test debe comprobar cómo funciona el motor,
    no una intuición sobre el mercado.
    """
    from tbot.data.sources.synthetic import SyntheticSource
    from tbot.strategies.basicas import PesosIguales

    src = SyntheticSource(seed=5)
    datos = {
        s: src.fetch_ohlcv(s, "1d", pd.Timestamp("2022-01-01", tz="UTC"),
                           pd.Timestamp("2023-01-01", tz="UTC"))
        for s in ("A/USD", "B/USD")
    }
    bt = Backtester(costes=CostModel(10, 5, 2))
    byh = bt.run(datos, ComprarYMantener(), timeframe="1d")
    reb = bt.run(datos, PesosIguales(), timeframe="1d")
    assert len(reb.trades) > len(byh.trades) * 10      # opera cada barra
    assert reb.trades["comision"].sum() > byh.trades["comision"].sum()


def test_none_significa_no_tocar_nada(datos):
    class Indecisa(Strategy):
        nombre = "indecisa"

        def target_weights(self, ctx):
            return None

    res = Backtester().run(datos, Indecisa(), timeframe="1d")
    assert len(res.trades) == 0
    assert res.equity.nunique() == 1


def test_banda_de_rebalanceo_reduce_operaciones(serie):
    """Con banda muerta debe haber muchas menos operaciones y menos comisiones,
    sin cambiar la lógica de la estrategia."""
    from tbot.data.sources.synthetic import SyntheticSource
    from tbot.strategies.basicas import PesosIguales

    src = SyntheticSource(seed=9)
    datos = {
        s: src.fetch_ohlcv(s, "1d", pd.Timestamp("2021-01-01", tz="UTC"),
                           pd.Timestamp("2024-01-01", tz="UTC"))
        for s in ("A/USD", "B/USD")
    }
    costes = CostModel(10, 5, 2)
    exacto = Backtester(costes=costes, banda_rebalanceo=0.0).run(datos, PesosIguales(), timeframe="1d")
    banda = Backtester(costes=costes, banda_rebalanceo=0.05).run(datos, PesosIguales(), timeframe="1d")
    assert len(banda.trades) < len(exacto.trades) / 5
    assert banda.trades["comision"].sum() < exacto.trades["comision"].sum()


def test_la_banda_no_impide_cerrar_posiciones(datos):
    """Salir del mercado debe ejecutarse siempre, por pequeña que sea la posición."""
    class EntraYSale(Strategy):
        nombre = "entra_y_sale"

        def target_weights(self, ctx):
            return {s: (1.0 if ctx.barras_disponibles(s) < 50 else 0.0) for s in ctx.symbols}

    res = Backtester(banda_rebalanceo=0.5).run(datos, EntraYSale(), timeframe="1d")
    assert (res.posiciones.filter(like="pos_").iloc[-1] == 0).all()


def test_el_pasado_no_depende_del_futuro(serie):
    """Test de no-lookahead a nivel de sistema completo.

    Se ejecuta el mismo backtest sobre la serie entera y sobre la serie cortada
    por la mitad. La curva de equity de la primera mitad tiene que ser IDÉNTICA
    en ambos casos: si alguna pieza del sistema (indicador, motor o estrategia)
    usara información posterior, aquí aparecería la diferencia.

    Es la prueba más importante del repositorio.
    """
    from tbot.strategies.basicas import CruceMedias

    corte = len(serie) // 2
    datos_completo = {"SYN/USD": serie}
    datos_truncado = {"SYN/USD": serie.iloc[:corte].reset_index(drop=True)}

    bt = Backtester(costes=CostModel(10, 5, 2), banda_rebalanceo=0.05)
    completo = bt.run(datos_completo, CruceMedias(20, 50), timeframe="1d")
    truncado = bt.run(datos_truncado, CruceMedias(20, 50), timeframe="1d")

    pd.testing.assert_series_equal(
        completo.equity.iloc[:corte], truncado.equity, check_freq=False
    )
