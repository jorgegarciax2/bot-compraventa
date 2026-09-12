"""Ejecución de órdenes.

`BrokerPapel` simula con comisiones y deslizamiento realistas y es el único
que se usa por defecto. `BrokerReal` tiene la misma interfaz y está pensado
para enchufar un exchange vía ccxt, pero nace *desarmado*: sin variable de
entorno explícita y sin límites configurados, se niega a mandar una orden.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .cartera import Cartera

COMPRA = "compra"
VENTA = "venta"


@dataclass
class Orden:
    simbolo: str
    lado: str                 # COMPRA | VENTA
    cantidad: float           # en unidades del activo
    motivo: str = ""

    def valida(self) -> None:
        if self.lado not in (COMPRA, VENTA):
            raise ValueError(f"Lado inválido: {self.lado}")
        if self.cantidad <= 0:
            raise ValueError("La cantidad debe ser > 0")


@dataclass
class Ejecucion:
    orden: Orden
    cantidad: float
    precio: float
    comision: float
    ts: int
    aceptada: bool = True
    rechazo: str = ""


@dataclass
class CostesMercado:
    comision_bps: float = 10.0     # 0,10 % por operación (típico exchange retail)
    deslizamiento_bps: float = 5.0 # 0,05 % de slippage contra ti
    minimo_operacion: float = 10.0 # importe mínimo por orden, en divisa


class Broker:
    def ejecutar(self, orden: Orden, precio_ref: float, ts: int,
                 cartera: Cartera) -> Ejecucion:
        raise NotImplementedError


class BrokerPapel(Broker):
    """Ejecuta contra el precio de referencia, siempre en tu contra.

    Compra un poco más caro y vende un poco más barato que el precio de
    pantalla; así el backtest no miente por defecto.
    """

    def __init__(self, costes: Optional[CostesMercado] = None) -> None:
        self.costes = costes or CostesMercado()

    def ejecutar(self, orden: Orden, precio_ref: float, ts: int,
                 cartera: Cartera) -> Ejecucion:
        orden.valida()
        desl = self.costes.deslizamiento_bps / 10_000
        precio = precio_ref * (1 + desl) if orden.lado == COMPRA else precio_ref * (1 - desl)
        cantidad = orden.cantidad

        if orden.lado == COMPRA:
            bruto = cantidad * precio
            comision = bruto * self.costes.comision_bps / 10_000
            # recorta al máximo financiable con la caja disponible
            if bruto + comision > cartera.caja:
                factor = 1 + self.costes.comision_bps / 10_000
                cantidad = max(0.0, (cartera.caja / factor) / precio)
                bruto = cantidad * precio
                comision = bruto * self.costes.comision_bps / 10_000
            if bruto < self.costes.minimo_operacion:
                return Ejecucion(orden, 0, precio, 0, ts, False,
                                 f"importe {bruto:.2f} < mínimo "
                                 f"{self.costes.minimo_operacion:.2f}")
            cartera.aplicar_compra(orden.simbolo, cantidad, precio, comision)
        else:
            pos = cartera.posicion(orden.simbolo)
            cantidad = min(cantidad, pos.cantidad)
            bruto = cantidad * precio
            comision = bruto * self.costes.comision_bps / 10_000
            if cantidad <= 0:
                return Ejecucion(orden, 0, precio, 0, ts, False, "sin posición que vender")
            # el mínimo no aplica al cierre total: hay que poder salir siempre
            cierra_todo = abs(cantidad - pos.cantidad) < 1e-12
            if bruto < self.costes.minimo_operacion and not cierra_todo:
                return Ejecucion(orden, 0, precio, 0, ts, False,
                                 f"importe {bruto:.2f} < mínimo "
                                 f"{self.costes.minimo_operacion:.2f}")
            cartera.aplicar_venta(orden.simbolo, cantidad, precio, comision)

        return Ejecucion(orden, cantidad, precio, comision, ts, True)


class BrokerRealDesarmado(RuntimeError):
    pass


class BrokerReal(Broker):
    """Ejecución con dinero real. Desarmado salvo que se arme a propósito.

    Requiere, TODO a la vez:
      1. la variable de entorno AGENTE_DINERO_REAL="SI_ENTIENDO_EL_RIESGO"
      2. `armado=True` al construirlo
      3. un `limite_orden` y una lista blanca de símbolos

    La implementación de red se deja fuera a propósito: enchufa ccxt en
    `_enviar` cuando decidas dar el paso, con tus claves en el entorno y
    permisos de sólo trading (nunca de retirada).
    """
    CENTINELA = "SI_ENTIENDO_EL_RIESGO"

    def __init__(self, exchange: str = "binance", armado: bool = False,
                 limite_orden: float = 0.0, simbolos_permitidos=(),
                 costes: Optional[CostesMercado] = None) -> None:
        self.exchange = exchange
        self.armado = armado
        self.limite_orden = limite_orden
        self.simbolos_permitidos = set(s.upper() for s in simbolos_permitidos)
        self.costes = costes or CostesMercado()
        self._cliente = None

    def _comprobar_armado(self, orden: Orden, importe: float) -> None:
        if os.environ.get("AGENTE_DINERO_REAL") != self.CENTINELA:
            raise BrokerRealDesarmado(
                "Broker real desarmado: falta AGENTE_DINERO_REAL="
                f"{self.CENTINELA} en el entorno.")
        if not self.armado:
            raise BrokerRealDesarmado("Broker real desarmado: armado=False.")
        if self.limite_orden <= 0:
            raise BrokerRealDesarmado("Define un limite_orden > 0 antes de operar.")
        if importe > self.limite_orden:
            raise BrokerRealDesarmado(
                f"Orden de {importe:.2f} supera el límite por orden "
                f"({self.limite_orden:.2f}).")
        if orden.simbolo.upper() not in self.simbolos_permitidos:
            raise BrokerRealDesarmado(
                f"{orden.simbolo} no está en la lista blanca "
                f"{sorted(self.simbolos_permitidos)}.")

    def ejecutar(self, orden: Orden, precio_ref: float, ts: int,
                 cartera: Cartera) -> Ejecucion:
        orden.valida()
        self._comprobar_armado(orden, orden.cantidad * precio_ref)
        return self._enviar(orden, precio_ref, ts, cartera)

    def _enviar(self, orden: Orden, precio_ref: float, ts: int,
                cartera: Cartera) -> Ejecucion:
        # Punto de enchufe. Con ccxt sería, a grandes rasgos:
        #   import ccxt
        #   cli = getattr(ccxt, self.exchange)({"apiKey": ..., "secret": ...})
        #   r = cli.create_order(orden.simbolo, "market", orden.lado_ccxt, cantidad)
        #   ...y luego reconciliar la cartera local con el fill devuelto.
        raise NotImplementedError(
            "Conecta aquí tu exchange (ccxt) antes de operar en real. "
            "La cartera local debe reconciliarse siempre con el fill real, "
            "no al revés.")
