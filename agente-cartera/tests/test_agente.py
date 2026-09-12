"""Tests del núcleo. `python -m unittest discover -s tests -v`"""
import unittest

from agente.core.broker import COMPRA, VENTA, BrokerPapel, CostesMercado, Orden, BrokerReal, BrokerRealDesarmado
from agente.core.cartera import Cartera
from agente.core.datos import Sintetica, Vela
from agente.core.metricas import resumen
from agente.core.motor import Agente, Config
from agente.core.riesgo import GestorRiesgo, ReglasRiesgo
from agente.core.vida import CausaMuerte, ReglasVida, SoporteVital
from agente.estrategias.catalogo import crear


def velas_lineales(precios):
    return [Vela(1_700_000_000 + i * 3600, p, p, p, p, 1.0)
            for i, p in enumerate(precios)]


class TestCartera(unittest.TestCase):
    def test_compra_y_venta_cuadran(self):
        c = Cartera.nueva(1000)
        c.aplicar_compra("X", 2, 100, 1)
        self.assertAlmostEqual(c.caja, 799.0)
        self.assertAlmostEqual(c.posicion("X").precio_medio, 100)
        realizado = c.aplicar_venta("X", 2, 120, 1)
        self.assertAlmostEqual(realizado, 39.0)        # 40 de plusvalía - 1 comisión
        self.assertAlmostEqual(c.caja, 1038.0)
        self.assertFalse(c.posicion("X").abierta)

    def test_precio_medio_pondera(self):
        c = Cartera.nueva(1000)
        c.aplicar_compra("X", 1, 100, 0)
        c.aplicar_compra("X", 1, 200, 0)
        self.assertAlmostEqual(c.posicion("X").precio_medio, 150)

    def test_no_se_puede_gastar_lo_que_no_hay(self):
        c = Cartera.nueva(100)
        with self.assertRaises(ValueError):
            c.aplicar_compra("X", 10, 50, 0)

    def test_no_se_puede_vender_lo_que_no_se_tiene(self):
        c = Cartera.nueva(100)
        with self.assertRaises(ValueError):
            c.aplicar_venta("X", 1, 50, 0)

    def test_equity_y_serializacion(self):
        c = Cartera.nueva(1000)
        c.aplicar_compra("X", 5, 100, 0)
        self.assertAlmostEqual(c.equity({"X": 110}), 1050)
        c2 = Cartera.de_dict(c.a_dict())
        self.assertAlmostEqual(c2.equity({"X": 110}), 1050)


class TestBroker(unittest.TestCase):
    def setUp(self):
        self.b = BrokerPapel(CostesMercado(comision_bps=10, deslizamiento_bps=50,
                                           minimo_operacion=10))

    def test_deslizamiento_siempre_en_contra(self):
        c = Cartera.nueva(1000)
        e = self.b.ejecutar(Orden("X", COMPRA, 1), 100, 0, c)
        self.assertGreater(e.precio, 100)              # compra más caro
        e2 = self.b.ejecutar(Orden("X", VENTA, 1), 100, 0, c)
        self.assertLess(e2.precio, 100)                # vende más barato

    def test_recorta_la_compra_a_la_caja_disponible(self):
        c = Cartera.nueva(100)
        e = self.b.ejecutar(Orden("X", COMPRA, 10), 100, 0, c)
        self.assertTrue(e.aceptada)
        self.assertGreaterEqual(c.caja, -1e-9)         # nunca deja la caja negativa
        self.assertLess(e.cantidad, 10)

    def test_rechaza_por_debajo_del_minimo(self):
        c = Cartera.nueva(1000)
        e = self.b.ejecutar(Orden("X", COMPRA, 0.01), 100, 0, c)
        self.assertFalse(e.aceptada)

    def test_siempre_se_puede_cerrar_del_todo(self):
        c = Cartera.nueva(1000)
        c.aplicar_compra("X", 0.05, 100, 0)            # posición de 5 €, bajo mínimo
        e = self.b.ejecutar(Orden("X", VENTA, 0.05), 100, 0, c)
        self.assertTrue(e.aceptada, "cerrar una posición nunca debe bloquearse")


class TestBrokerReal(unittest.TestCase):
    def test_nace_desarmado(self):
        br = BrokerReal(armado=True, limite_orden=100, simbolos_permitidos=["X"])
        with self.assertRaises(BrokerRealDesarmado):
            br.ejecutar(Orden("X", COMPRA, 1), 10, 0, Cartera.nueva(1000))


class TestRiesgo(unittest.TestCase):
    def test_el_stop_loss_manda_sobre_la_estrategia(self):
        g = GestorRiesgo(ReglasRiesgo(stop_loss=0.10, trailing_stop=None,
                                      banda_rebalanceo=0.05))
        c = Cartera.nueva(1000)
        c.aplicar_compra("X", 5, 100, 0)
        ordenes = g.ordenes("X", 1.0, 85, c, 925)      # la estrategia quiere seguir
        self.assertEqual(len(ordenes), 1)
        self.assertEqual(ordenes[0].lado, VENTA)
        self.assertIn("stop-loss", ordenes[0].motivo)

    def test_la_banda_evita_operar_por_nada(self):
        g = GestorRiesgo(ReglasRiesgo(banda_rebalanceo=0.20, stop_loss=None,
                                      trailing_stop=None))
        c = Cartera.nueva(1000)
        c.aplicar_compra("X", 5, 100, 0)
        self.assertEqual(g.ordenes("X", 0.55, 100, c, 1000), [])

    def test_nunca_supera_la_exposicion_maxima(self):
        g = GestorRiesgo(ReglasRiesgo(max_exposicion=0.5, banda_rebalanceo=0.01,
                                      stop_loss=None, trailing_stop=None))
        o = g.ordenes("X", 1.0, 100, Cartera.nueva(1000), 1000)
        self.assertAlmostEqual(o[0].cantidad * 100, 500, places=6)


class TestVida(unittest.TestCase):
    def test_muere_por_ruina(self):
        s = SoporteVital(ReglasVida(ruina_relativa=0.10, max_drawdown=0.99), 1000)
        s.latir(500, 500)
        self.assertTrue(s.vivo)
        v = s.latir(99, 99)
        self.assertFalse(v.vivo)
        self.assertEqual(v.causa_muerte, CausaMuerte.RUINA)

    def test_muere_por_drawdown(self):
        s = SoporteVital(ReglasVida(ruina_relativa=0.0, max_drawdown=0.30), 1000)
        s.latir(2000, 100)
        v = s.latir(1300, 100)
        self.assertFalse(v.vivo)
        self.assertEqual(v.causa_muerte, CausaMuerte.DRAWDOWN)

    def test_muere_de_inanicion_con_caja_negativa(self):
        s = SoporteVital(ReglasVida(), 1000)
        v = s.latir(900, -0.01)
        self.assertEqual(v.causa_muerte, CausaMuerte.INANICION)

    def test_la_muerte_es_irreversible(self):
        s = SoporteVital(ReglasVida(), 1000)
        s.matar()
        ticks = s.v.ticks
        s.latir(10_000, 10_000)                        # aunque el mercado despegue
        self.assertFalse(s.vivo)
        self.assertEqual(s.v.ticks, ticks)


class TestMotor(unittest.TestCase):
    def test_gana_dinero_en_mercado_alcista(self):
        precios = [100 * (1.01 ** i) for i in range(120)]
        cfg = Config(capital=1000, simbolo="X", coste_vida_anual=0.0)
        ag = Agente(cfg, crear("comprar_y_aguantar"))
        ag.vivir(velas_lineales(precios))
        self.assertGreater(ag.resumen()["equity_final"], 1000)
        self.assertTrue(ag.vivo)

    def test_muere_y_deja_de_operar_en_mercado_catastrofico(self):
        precios = [100 * (0.97 ** i) for i in range(200)]
        cfg = Config(capital=1000, simbolo="X", coste_vida_anual=0.0,
                     reglas_vida=ReglasVida(ruina_relativa=0.10, max_drawdown=0.99))
        ag = Agente(cfg, crear("comprar_y_aguantar"))
        ag.vivir(velas_lineales(precios))
        self.assertFalse(ag.vivo)
        ticks = ag.soporte.v.ticks
        ag.tick(velas_lineales(precios))               # intentar revivirlo no hace nada
        self.assertEqual(ag.soporte.v.ticks, ticks)

    def test_al_morir_liquida_y_no_quedan_posiciones(self):
        precios = [100 * (0.97 ** i) for i in range(200)]
        cfg = Config(capital=1000, simbolo="X", coste_vida_anual=0.0,
                     reglas_vida=ReglasVida(ruina_relativa=0.10, max_drawdown=0.99))
        ag = Agente(cfg, crear("comprar_y_aguantar"))
        ag.vivir(velas_lineales(precios))
        self.assertFalse(ag.cartera.posicion("X").abierta)

    def test_el_coste_de_vida_mata_al_agente_pasivo(self):
        precios = [100.0] * 5000                       # mercado plano
        cfg = Config(capital=1000, simbolo="X", coste_vida_anual=2.0,
                     reglas_vida=ReglasVida(ruina_relativa=0.10, max_drawdown=0.99))
        ag = Agente(cfg, crear("azar", prob_dentro=0.0))
        ag.vivir(velas_lineales(precios))
        self.assertFalse(ag.vivo, "sin ingresos, el coste de existir debe matarlo")

    def test_es_reproducible(self):
        velas = Sintetica(semilla=3).historico(limite=1500)
        finales = []
        for _ in range(2):
            ag = Agente(Config(capital=1000, simbolo="SINT"), crear("cruce_medias"))
            ag.vivir(velas)
            finales.append(ag.resumen()["equity_final"])
        self.assertAlmostEqual(finales[0], finales[1])


class TestMetricas(unittest.TestCase):
    def test_drawdown_conocido(self):
        m = resumen([100, 200, 100, 150], 365)
        self.assertAlmostEqual(m["max_drawdown"], 0.5)
        self.assertAlmostEqual(m["retorno_total"], 0.5)


if __name__ == "__main__":
    unittest.main()
