# agente-cartera

Un agente autónomo que nace con una cartera de X €, intenta multiplicarla y
**muere solo si se arruina**. La muerte es definitiva: deja una lápida en disco
y cualquier intento de reanudarlo se niega a operar.

Sin dependencias: Python 3.9+ y nada más. Ni numpy, ni pandas, ni cuentas de API.

```
python3 -m agente torneo    --simbolo BTCEUR --capital 1000    # ¿qué estrategia aguanta?
python3 -m agente backtest  --simbolo BTCEUR --capital 1000 --estrategia tendencia_vol
python3 -m agente papel     --dir ejecuciones/btc --simbolo BTCEUR --capital 1000
python3 -m agente cementerio --agentes 50 --estrategia todas    # ¿cuántos sobreviven?
python3 -m agente estado    --dir ejecuciones/btc
```

## Cómo está montado

| Pieza | Archivo | Responsabilidad |
|---|---|---|
| Cartera | `agente/core/cartera.py` | Caja, posiciones, PnL. Sólo contabiliza. |
| Vida y muerte | `agente/core/vida.py` | Cuándo sigue vivo, de qué muere, la lápida. |
| Riesgo | `agente/core/riesgo.py` | Stops, exposición máxima, banda de rebalanceo. |
| Ejecución | `agente/core/broker.py` | Papel (comisiones + slippage) y real, desarmado. |
| Datos | `agente/core/datos.py` | Binance, Yahoo, CSV, mercado sintético. |
| Motor | `agente/core/motor.py` | El bucle de vida. El mismo para backtest y vivo. |
| Estrategias | `agente/estrategias/` | Lo único que cambias a menudo. |

La separación importante: **la estrategia no manda órdenes**. Sólo dice qué
fracción del patrimonio quiere tener invertida (0 a 1). El riesgo y el motor
traducen ese deseo en órdenes. Así todas las estrategias son comparables entre
sí y la protección del capital vive en un único sitio.

## Cómo muere

Se evalúa en cada vela, después de operar y de pagar el coste de existir:

| Causa | Cuándo |
|---|---|
| `ruina` | El equity cae al umbral (`--ruina 0.10` = 10 % del capital inicial). |
| `drawdown_maximo` | Pierde más del `--max-dd` desde su máximo histórico. |
| `inanicion` | Se queda sin caja para pagar el coste de vida. |
| `polvo` | Equity por debajo del mínimo con el que se puede operar. |
| `edad_maxima` | Alcanza el horizonte configurado, si lo pones. |

Al morir liquida la posición a mercado (para que la cifra final sea real),
escribe `LAPIDA.json` y no vuelve a operar. Para empezar de cero: `--reencarnar`,
o mejor, otro directorio.

**El coste de vida** (`--coste-vida 0.02`, 2 % anual del capital) es lo que hace
que la mortalidad tenga sentido: sin él, un agente que no hiciera nada sería
inmortal y "ganar dinero" no sería un objetivo, sería un adorno. Con él, quedarse
quieto también cuesta.

Detalle que conviene entender: como la cartera es **long-only al contado y sin
apalancamiento**, el equity nunca puede ser negativo de verdad. Por eso "llegar
a cero" se define como caer por debajo de un umbral de ruina, no como equity < 0.
Si algún día metes apalancamiento, el cero literal sí es alcanzable — y llega antes
de lo que crees.

## Las estrategias que trae

| Nombre | Idea |
|---|---|
| `comprar_y_aguantar` | La referencia. Si no la bates, no tienes estrategia. |
| `cruce_medias` | Tendencia: dentro si la EMA rápida supera a la lenta. |
| `ruptura_canal` | Momentum tipo Donchian: entra en máximos, sale en mínimos. |
| `reversion_media` | Compra caídas, pero sólo dentro de tendencia alcista. |
| `tendencia_vol` | Tendencia dosificada por volatilidad. La más sensata. |
| `azar` | Control negativo. Está para morirse y recordarte el listón. |

### Añadir la tuya

```python
from agente.estrategias.base import Estrategia
from agente.core import indicadores as ind

class MiIdea(Estrategia):
    nombre = "mi_idea"
    velas_minimas = 50

    def objetivo(self, ctx):          # 0..1, o None para "no opino"
        if ind.rsi(ctx.cierres, 14) < 30:
            return 1.0
        return 0.0
```

Regístrala en `CATALOGO` (`agente/estrategias/catalogo.py`) y ya aparece en el
torneo y en el cementerio.

## El paso a dinero real

`BrokerReal` (`agente/core/broker.py`) tiene la misma interfaz que el de papel y
nace **desarmado**. Para que mande una sola orden hacen falta cuatro cosas a la vez:

1. `export AGENTE_DINERO_REAL=SI_ENTIENDO_EL_RIESGO`
2. `armado=True`
3. Un `limite_orden` por operación
4. Una lista blanca de símbolos

Falta a propósito lo último: la llamada al exchange. Está marcada en `_enviar`,
pensada para `ccxt`. Cuando la escribas, dos reglas que no son negociables:

- **Claves de sólo trading, nunca con permiso de retirada**, y con la IP fijada.
- **La cartera local se reconcilia con el fill real del exchange, nunca al revés.**
  Si tu contabilidad y la del exchange discrepan, la que manda es la del exchange.

Y antes de eso, tres cosas que conviene mirar con calma: en España las ganancias
patrimoniales de cripto y valores tributan en la base del ahorro y hay que
declarar **cada operación** (un bot puede generarte cientos de apuntes al año);
un bot desatendido puede perder dinero mucho más rápido de lo que tú reaccionas;
y un backtest bueno no predice nada — sobre todo si lo has optimizado hasta que
salió bonito.

## Lo que este proyecto no es

No es una máquina de hacer dinero, y ninguna de estas estrategias tiene ventaja
demostrada. Lo que sí es: un banco de pruebas honesto, con costes realistas,
mortalidad de verdad y trazabilidad completa, donde puedes medir si una idea
tuya aguanta antes de que te cueste un euro. El `cementerio` está precisamente
para eso — para que veas cuántos de tus agentes mueren cuando repites el
experimento 50 veces en lugar de mirar el backtest que salió bien.

## Salida y trazabilidad

Con `--dir`, cada ejecución deja:

```
diario.jsonl    un evento por línea: nacimiento, operaciones, rechazos, muerte
estado.json     cartera, vitales y curva de equity (permite reanudar)
resumen.json    métricas finales
velas.csv       los datos exactos con los que se operó
LAPIDA.json     sólo si murió: causa, detalle y resumen
```

```bash
jq -r 'select(.tipo=="operacion") | "\(.lado) \(.cantidad) @ \(.precio)"' diario.jsonl
```

## Tests

```bash
python3 -m unittest discover -s tests -v      # 23 tests, sin dependencias
```
