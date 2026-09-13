# Bot de compraventa

Una página web local con dos pestañas:

- **En vivo** — el bot operando. Nace con un capital ficticio, analiza el mercado
  vela a vela y compra y vende por su cuenta. Es lo que quieres mirar cada día.
- **Laboratorio** — backtests sobre el pasado. Sirve para decidir qué estrategia
  merece que le dejes dinero, aunque sea ficticio. Aquí no opera nadie.

```bash
./lanzar.command
```

Doble clic en el Finder hace lo mismo. Abre <http://127.0.0.1:8765>.

## Cómo funciona el agente en vivo

Cada agente es un proceso independiente que **respira una vez por vela**:

1. Valora la cartera a precio de mercado.
2. Pregunta a la estrategia qué fracción del patrimonio quiere invertida (0 a 1).
3. La capa de riesgo traduce ese deseo en órdenes: recorta por exposición máxima,
   dispara stop-loss y trailing stop, e ignora los ajustes pequeños para no
   sangrar comisiones.
4. Ejecuta en papel, pagando comisión y deslizamiento en tu contra.
5. Paga el **coste de vida** (2 % anual del capital): quedarse quieto también cuesta.
6. Comprueba si sigue vivo.

**La estrategia no manda órdenes.** Sólo dice cuánto quiere estar dentro. Por eso
todas son comparables entre sí y la protección del capital vive en un único sitio.

### Estar fuera del mercado es una decisión, no un fallo

Si el agente marca «fuera / todo en caja» y no opera durante horas, está
funcionando. `tendencia_vol` sólo entra cuando la media rápida supera a la lenta;
si no hay tendencia, se queda en caja. Un bot que compra siempre no es un bot, es
comprar y aguantar con pasos intermedios.

### Cómo muere

Se comprueba en cada latido, después de operar y de pagar por existir:

| Causa | Cuándo |
|---|---|
| `ruina` | El patrimonio cae al 10 % del capital inicial. |
| `drawdown_maximo` | Pierde más del 50 % desde su máximo histórico. |
| `inanicion` | Se queda sin caja para pagar el coste de vida. |
| `polvo` | Patrimonio por debajo del mínimo operable. |

Al morir liquida la posición a mercado y deja una lápida. **La muerte es
definitiva**: sólo puedes empezar de cero, y eso borra el historial.

## Ver el bot operando ahora mismo

Un agente sobre Binance con velas de 15 minutos late cuatro veces por hora: es lo
correcto, pero no se ve nada en un rato. Para entender la mecánica en un minuto,
crea uno con **fuente «Ensayo»**: usa un mercado generado que avanza varias velas
por segundo, así ves compras, ventas, comisiones y la curva moverse en directo.

Un experimento que enseña más que cualquier explicación: lanza un agente de ensayo
con la estrategia `azar`. Opera a cara o cruz y se muere. En una prueba de este
panel murió en 808 latidos con un patrimonio de 502 € de los 1.000 iniciales,
**de los cuales 279 € se los llevaron las comisiones**. Ése es el listón que
cualquier estrategia tiene que batir.

## Qué hay en cada carpeta

```
lanzar.command        arranque de un clic (crea el entorno si hace falta)
web/servidor.py       servidor local: sirve la página y coordina todo
web/vivo.py           arrancar, pausar y observar agentes en vivo
web/estatico/         la página (HTML + CSS + JS, sin dependencias externas)
agente-cartera/       el bot que opera: bucle de vida, riesgo, broker de papel
tbot/                 el laboratorio: almacén de velas, validación y backtester
ejecuciones/<nombre>/ todo lo de cada agente (ver abajo)
.venv/                entorno de Python
```

Cada agente deja su rastro completo en `ejecuciones/<nombre>/`:

| Fichero | Qué es |
|---|---|
| `estado.json` | Cartera, vitales y curva de patrimonio. Permite reanudar. |
| `diario.jsonl` | Un evento por línea: nacimiento, operaciones, rechazos, muerte. |
| `serie.jsonl` | Patrimonio con hora real, muestreado por el panel. De aquí salen el gráfico y el «día a día». |
| `LAPIDA.json` | Sólo si murió: causa, detalle y resumen final. |
| `salida.log` | Lo que el proceso escribió por pantalla. |

Los agentes son procesos aparte: **siguen operando aunque cierres el navegador o
pares el panel**. Para pararlos de verdad, usa «Pausar» en la página.

## El bot en la nube, gratis (GitHub Actions)

Corriendo ya en <https://jorgegarciax2.github.io/bot-compraventa/>

No hay servidor. Una tarea programada despierta cada hora, da **un latido**,
guarda el estado en el propio repositorio y regenera el tablero. El motor y las
reglas son exactamente los mismos que en el panel local: lo único que cambia es
quién lleva el reloj.

```
github/latido.py               un latido: carga estado, opera, lo guarda
github/tablero.py              genera docs/index.html (SVG en Python, sin JS)
.github/workflows/latido.yml   el cron: minuto 11 de cada hora
configuracion.json             los mandos, ya que aquí no hay botones
estado/btc/                    el rastro del bot, versionado en git
```

### Cómo se maneja

No hay botones: se edita [configuracion.json](configuracion.json), se hace commit
y el siguiente latido lo usa.

| Quiero… | Cambio |
|---|---|
| Que deje de operar sin perder nada | `"pausado": true` |
| Otra estrategia | `"estrategia": "cruce_medias"` |
| Otro activo | `"simbolo": "ETH-EUR"` |
| Empezar un agente nuevo | borra `estado/btc/` y cambia `"nombre"` |

Para forzar un latido sin esperar a la hora: pestaña **Actions → latido → Run
workflow**.

### Qué está operando, y por qué ése

`tendencia_vol` sobre **velas de 4 horas**. No es un capricho: es lo único que
sobrevivió a la validación por ventanas (`python github/validar.py`), que mide
cada estrategia en 30 pruebas independientes — 5 activos × 6 ventanas de 90 días:

| estrategia | mediana | peor | positiva | bate B&H |
|---|---|---|---|---|
| **tendencia_vol** | **+4,2 %** | −24,3 % | 17/30 | **22/30** |
| cruce_medias | +0,4 % | −36,0 % | 15/30 | 21/30 |
| ruptura_canal | +0,1 % | −20,2 % | 15/30 | 16/30 |
| reversion_media | −0,9 % | **−6,5 %** | 13/30 | 19/30 |
| estructura | −1,7 % | −24,1 % | 13/30 | 19/30 |
| comprar_y_aguantar | −3,0 % | −38,0 % | 11/30 | — |
| azar | −44,3 % | −50,1 % | 0/30 | 2/30 |

La columna que decide es **peor**, no mejor: es lo que te puede pasar. Y el
`azar` está ahí como control: si una estrategia no lo bate con holgura, es ruido.

Dos avisos sobre esos números. Treinta pruebas sobre cinco criptomonedas **no
son treinta muestras independientes**: se mueven todas juntas, así que la
muestra efectiva es bastante menor. Y una mediana de +4,2 % por ventana de 90
días convive con una peor ventana de −24,3 %.

### El cron es un vigilante, no un metrónomo

Sondea cada 30 minutos pero el agente **late una vez por vela**. Esto importa
porque se midió: manteniendo la ventana de análisis igual en tiempo real y
multiplicando por doce las lecturas del mercado, el número de operaciones no se
movió (65 → 61 → 63). Mirar más a menudo no hace operar más; **acortar la vela
sí**, porque encoge lo que la estrategia es capaz de ver.

Yahoo no sirve velas de 4h, así que se piden de 1h y se agrupan
(`remuestrear_desde` en la configuración).

### La pestaña de acciones

Segundo agente, con su propio capital y su propio historial. En acciones hay
mucho más que mirar que en cripto, y se mira todo lo que se puede conseguir
gratis y sin claves:

| qué | de dónde | qué papel juega |
|---|---|---|
| Precio y **volumen** | Yahoo Finance | La señal: tendencia, niveles, OBV |
| **Fundamentales** | **SEC EDGAR** — cuentas oficiales auditadas | Filtro: si suspende, no se opera |
| **Noticias** | RSS de Yahoo | Freno: con revuelo no abre, pero sí cierra |

**Por qué EDGAR y no los ratios de Yahoo.** Yahoo cerró su endpoint de ratios.
EDGAR es lo que la empresa presenta al regulador: auditado, estructurado y sin
intermediario. Dos límites: sólo cubre EE. UU., y **cambia cada trimestre** —
sirve para decidir *qué* operar, nunca *cuándo*.

**Qué NO hace con las noticias.** No interpreta si un titular es bueno o malo.
Hacerlo bien requiere un modelo de lenguaje, y aquí no hay ninguno sin clave de
pago; contar palabras «positivas» daría una cifra con aspecto de análisis y
valor de moneda al aire. Lo único que mide es el **repunte de cobertura** — y ni
eso puede hacerlo el primer día: el baremo lo construye el propio bot latido a
latido, porque el RSS sólo devuelve veinte titulares recientes y calcular la
«media» con ellos daría revuelo siempre.

**Qué estrategia opera las acciones, y por qué otra distinta.** `estructura`
—soportes, resistencias, HCH y ADX—, que fracasó en cripto pero es la mejor de
las activas en acciones. Validación sobre 80 pruebas de 10 años y 8 valores:

| estrategia | mediana | PEOR | bate B&H | muertes |
|---|---|---|---|---|
| comprar_y_aguantar | **+8,9 %** | **−50,6 %** | — | **3** |
| cruce_medias | +1,9 % | −34,7 % | 19/80 | 0 |
| **estructura** | +1,3 % | **−18,2 %** | **27/80** | 0 |
| tendencia_volumen | +0,6 % | −25,9 % | 18/80 | 0 |
| azar | −9,5 % | −31,3 % | 9/80 | 0 |

Conviene leerla bien: **en acciones las estrategias no ganan más, pierden
menos**. Comprar y aguantar da más rentabilidad de mediana y a cambio te lleva a
un −50,6 % y mató al agente tres veces. Si lo que buscas es máxima rentabilidad
y aguantas la caída, comprar y aguantar es difícil de batir en bolsa
estadounidense. El bot cambia rentabilidad por supervivencia.

### Peajes de esta vía, dichos por adelantado

**Yahoo en vez de Binance.** Los ejecutores de GitHub están en EE. UU. y Binance
responde HTTP 451 a esas IP. Yahoo sirve `BTC-EUR` igual de bien y sin claves.

**El reloj de GitHub no es puntual.** Las tareas programadas se retrasan cuando
hay cola, a veces media hora. Con velas de una hora da igual, pero no esperes
precisión de reloj suizo.

**El repositorio es público.** Es lo que hace que Pages sea gratis. No hay
contraseñas ni claves dentro — está auditado — pero cualquiera puede ver cómo le
va al bot.

**Se apaga solo a los 60 días de inactividad.** GitHub desactiva las tareas
programadas si el repositorio no recibe actividad humana en dos meses, y los
commits del propio bot no cuentan. Si un día ves que dejó de latir, es esto:
se reactiva con un botón en la pestaña Actions.

## Ponerlo en un servidor 24/7

Para que el bot siga operando con el portátil apagado, hay una guía completa en
[DESPLIEGUE.md](DESPLIEGUE.md): máquina gratuita de Oracle Cloud en una región
europea, HTTPS automático y panel con contraseña. Resumen:

```bash
python web/clave.py                                    # elegir contraseña
./despliegue/subir.sh bot                              # subir e instalar
```

El panel **se niega a escuchar fuera de este equipo si no hay contraseña**: en
local sigue funcionando sin nada, pero no se puede publicar por accidente.

## Lo que esto NO hace

**No manda una sola orden a ningún bróker.** La ejecución es simulada de principio
a fin. `agente-cartera` trae un `BrokerReal` preparado para enchufar un exchange,
pero nace desarmado y le falta a propósito la llamada de red.

Ninguna de estas estrategias tiene ventaja demostrada, y un backtest bueno no
predice nada — menos aún si lo has optimizado hasta que salió bonito. Eso es
precisamente para lo que está el dinero ficticio: para medir antes de que te
cueste un euro.

Y antes de pensar en dinero real, dos cosas concretas: en España las ganancias
patrimoniales de cripto y valores tributan en la base del ahorro y hay que
declarar **cada operación** (un bot puede generarte cientos de apuntes al año), y
un bot desatendido puede perder dinero mucho más rápido de lo que tú reaccionas.
No soy asesor financiero y esto no es una recomendación de inversión.

## Notas técnicas

El servidor escucha sólo en `127.0.0.1`: no es accesible desde fuera de este Mac.

Este Mac trae Python 3.9.6 y no hay Homebrew ni pyenv. `tbot` declara
`requires-python >= 3.11`, pero no usa nada exclusivo de 3.10+, así que el panel
instala las dependencias sueltas en vez de `pip install -e .`, que rechazaría
3.9. `agente-cartera` no necesita ninguna dependencia. Verificado end-to-end en
3.9.6: ingesta real de Binance, backtests, y agentes operando en vivo.

Para acciones y ETFs en vivo, la fuente **Yahoo** no necesita claves (símbolos
tipo `AAPL`, `SPY`, `SAN.MC`). El laboratorio usa Alpaca para acciones, y ésa sí
pide credenciales en el entorno (`APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`).
