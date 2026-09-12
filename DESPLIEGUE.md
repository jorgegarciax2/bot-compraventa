# Desplegar el bot en Oracle Cloud (gratis, 24/7)

El objetivo: que el bot siga operando con el portátil apagado, sin pagar nada, y
que puedas mirar el panel desde el móvil con `https://` y contraseña.

Tiempo: unos 40 minutos la primera vez. Después, actualizar es un comando.

---

## Por qué Oracle y no otro

| | |
|---|---|
| **Render / Fly.io gratis** | Render duerme el servicio a los 15 min de inactividad y no da disco persistente; Fly.io eliminó su plan gratuito en octubre de 2024. El agente dejaría de latir y perdería el estado. |
| **Google Cloud siempre gratis** | Existe, pero la máquina gratuita sólo está en regiones de EE. UU., y **Binance responde HTTP 451 a las IP estadounidenses**. |
| **Oracle siempre gratis** | Sigue vigente, tiene **regiones en la UE** (Madrid, Fráncfort) y da disco persistente. |

### Elige la máquina AMD, no la ARM

Oracle puede **recuperar máquinas inactivas**, pero esa política **sólo se aplica
a las ARM (Ampere A1)**: se consideran inactivas si durante 7 días la CPU, la red
y la memoria se quedan por debajo del 20 %. Un bot que late cada 15 minutos está
muy por debajo de eso, así que una ARM acabaría recuperada.

Las **AMD `VM.Standard.E2.1.Micro` están exentas**. Tienen 1 GB de RAM, que es
poco — por eso el panel carga pandas sólo cuando abres el Laboratorio (arranca
con unos 20 MB) y el instalador añade 2 GB de intercambio.

---

## 1. Cuenta de Oracle Cloud

1. Entra en <https://www.oracle.com/cloud/free/> y crea la cuenta.
2. **La región de origen no se puede cambiar después.** Elige
   **Spain Central (Madrid)** o **Germany Central (Frankfurt)**. Si eliges una de
   EE. UU., Binance te bloqueará y habrá que empezar de cero.
3. Pide una tarjeta para verificar identidad. No cobra nada mientras te quedes
   en los recursos «Always Free».

## 2. Crear la máquina

En **Compute → Instances → Create instance**:

- **Image**: Canonical Ubuntu 24.04
- **Shape**: `VM.Standard.E2.1.Micro` (AMD, marcada como *Always Free eligible*)
- **SSH keys**: «Generate a key pair for me» y **descarga la clave privada**
  antes de seguir. Es la única vez que te la ofrece.
- Deja la red virtual que te propone, con IP pública.

Guarda la clave donde no se pierda y dale permisos:

```bash
mkdir -p ~/.ssh && mv ~/Downloads/ssh-key-*.key ~/.ssh/oracle-bot.key
chmod 600 ~/.ssh/oracle-bot.key
```

Comprueba que entras (la IP pública sale en la ficha de la instancia):

```bash
ssh -i ~/.ssh/oracle-bot.key ubuntu@TU.IP.PUBLICA
```

Para no repetir la clave cada vez, añade esto a `~/.ssh/config`:

```
Host bot
    HostName TU.IP.PUBLICA
    User ubuntu
    IdentityFile ~/.ssh/oracle-bot.key
```

## 2b. Cuando Oracle dice «Out of capacity»

Es lo más probable que te pase, y no es culpa tuya ni de la configuración:

```
Out of capacity for shape VM.Standard.E2.1.Micro in availability domain AD-1
```

Oracle reserva un cupo limitado de máquinas gratuitas por región. Cuando se
agota, rechaza la creación. Madrid tiene **un solo dominio de disponibilidad**,
así que el consejo del error («prueba en otro») no aplica, y las demás regiones
tampoco valen: los recursos Always Free sólo existen en tu región de origen.

Los huecos aparecen sin avisar, cuando alguien destruye su instancia. La única
salida es insistir, y para eso está el cazador:

```bash
~/.local/share/oci-sdk/venv/bin/python despliegue/cazar-maquina.py
```

Pide una máquina cada 5 minutos, alternando AMD y ARM, hasta que haya suerte.
Cuando lo consigue escribe `~/.oci/bot-maquina.json` con la IP y te avisa con una
notificación de macOS.

**Por qué 5 minutos y no 30 segundos.** Oracle limita las peticiones de creación
**por cuenta**, no por forma de máquina. Medido en esta cuenta: los intentos
separados menos de ~90 s devuelven 429, y los de más de ~2 min reciben respuesta
real. Y un 429 **no llega a comprobar la capacidad**: sólo renueva el castigo.
Insistir más rápido no encuentra el hueco antes — lo esconde. Si Oracle protesta,
el cazador dobla la espera hasta un tope de 30 minutos.

```bash
despliegue/cazar-maquina.py --formas amd      # sólo la AMD, sin prisa
despliegue/cazar-maquina.py --intervalo 600   # aún más suave
despliegue/cazar-maquina.py --max-horas 12    # se rinde a las 12 h
```

**AMD o ARM.** La AMD (`E2.1.Micro`, 1 GB) está exenta de la recuperación por
inactividad. La ARM (`A1.Flex`, 6 GB) es mejor máquina pero Oracle **puede
recuperarla** si pasa 7 días con CPU, red y memoria por debajo del 20 % — que es
justo el perfil de este bot. Por defecto el cazador acepta las dos para que algo
eche a andar cuanto antes, y avisa si te toca la ARM. Si te toca y quieres
blindarla, la salida documentada por Oracle es pasar la cuenta a *Pay As You Go*:
no cobra mientras te mantengas en los límites Always Free, pero es una decisión
tuya sobre facturación.

**Que sobreviva a un reinicio del Mac** (opcional):

```bash
cp despliegue/com.jorge.cazador-oracle.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jorge.cazador-oracle.plist
```

Para pararlo: `launchctl unload ~/Library/LaunchAgents/com.jorge.cazador-oracle.plist`.

El cazador necesita una clave de API de Oracle, que ya está puesta en
`~/.oci/config` (la privada en `~/.oci/oci_api_key.pem`, con permisos 600), y los
identificadores del destino en `~/.oci/bot-objetivo.json`.

## 3. Abrir los puertos 80 y 443

Esto hay que hacerlo **en dos sitios**, y olvidar uno es el fallo más común:

1. **En la consola de Oracle**: Networking → Virtual Cloud Networks → tu VCN →
   Security Lists → Default Security List → *Add Ingress Rules*. Dos reglas:
   origen `0.0.0.0/0`, protocolo TCP, puerto destino `80` y otra igual con `443`.
2. **En la propia máquina**: lo hace el instalador (las imágenes de Ubuntu en
   Oracle traen iptables cerrado salvo SSH).

## 4. Subir el bot e instalarlo

Desde el portátil, en la carpeta del proyecto:

```bash
./despliegue/subir.sh bot
```

**No hace falta dominio ni cuenta de DNS.** El instalador averigua la IP pública
de la máquina y usa `sslip.io`, un servicio que resuelve `88-12-34-56.sslip.io`
a esa misma IP sin registrarse en nada. Let's Encrypt emite el certificado contra
ese nombre por desafío HTTP-01, así que tendrás HTTPS de verdad.

Si algún día quieres un dominio propio, apúntalo a la IP y pásalo como segundo
argumento: `./despliegue/subir.sh bot bot.midominio.com`.

Eso copia el código, instala Python, Caddy y las dependencias, crea el usuario
del servicio, añade el intercambio, abre el cortafuegos y deja el panel como
servicio de systemd. **No sube tu contraseña ni el estado de los agentes**, así
que puedes repetirlo cuando quieras para actualizar sin romper nada.

## 5. Poner la contraseña y arrancar

El instalador se para aquí a propósito: el panel **se niega a escuchar fuera de
casa sin contraseña**.

```bash
ssh bot
sudo -u bot /opt/bot/.venv/bin/python /opt/bot/web/clave.py
sudo systemctl start bot-panel
```

Ya está. La dirección te la dice el propio instalador al terminar:
**https://TU-IP-CON-GUIONES.sslip.io**

El certificado lo pide y lo renueva Caddy solo. La sesión dura 30 días, así que
desde el móvil entras una vez y te olvidas.

---

## Vida diaria

```bash
ssh bot

sudo systemctl status bot-panel        # ¿está en marcha?
sudo journalctl -u bot-panel -f        # registro en vivo (incluye claves falladas)
sudo systemctl restart bot-panel       # reiniciar el panel
ls /opt/bot/ejecuciones/               # los agentes y su rastro
free -h                                # memoria, que es lo justo
```

**Actualizar tras tocar el código en el portátil:**

```bash
./despliegue/subir.sh bot
```

**Copia de seguridad del historial** (los agentes y sus diarios):

```bash
rsync -az bot:/opt/bot/ejecuciones/ ./copia-ejecuciones/
```

---

## Detalles que conviene saber

**Los agentes sobreviven al reinicio.** Son procesos independientes del panel.
Si la máquina se reinicia, el panel los vuelve a lanzar al arrancar — pero sólo
los que estaban operando: si pausaste uno, sigue pausado. Y nunca los reanuda
con «empezar de cero», que borraría el historial.

**Si reinicias sólo el panel, los agentes ni se enteran.** La unidad de systemd
usa `KillMode=process` justo para eso.

**La hora.** El servicio va con `TZ=Europe/Madrid`, así que el «día a día» del
panel cuadra con tu día, no con UTC.

**La contraseña** se guarda en `/opt/bot/panel.json` como hash PBKDF2 con sal
(400.000 iteraciones), con permisos 600. Si la olvidas, vuelve a ejecutar
`clave.py`. Tras 4 intentos fallidos la espera crece, y a partir de 8 se bloquea
esa IP 15 minutos.

**El nombre depende de sslip.io.** Es un servicio gratuito de terceros. Si
desapareciera, la web seguiría funcionando hasta que caducase el certificado
(90 días), y bastaría con apuntar un dominio propio y reinstalar. Es el precio
de no tener que registrarse en nada.

**El Laboratorio consume memoria.** Un backtest carga pandas y puede subir a
unos 400 MB. Con 1 GB de RAM y 2 GB de intercambio aguanta, pero irá lento. Si lo
usas mucho, hazlo en el portátil y deja el servidor sólo para operar.

**Sigue sin haber dinero real.** El despliegue no cambia nada de eso: la
ejecución es simulada de principio a fin, y `BrokerReal` sigue desarmado y sin
implementar la llamada al exchange.

---

## Si algo falla

| Síntoma | Causa casi segura |
|---|---|
| El navegador no conecta | Falta la regla de entrada en la consola de Oracle (paso 3.1). |
| «connection refused» por SSH pero la web sí | El servicio no arrancó: `journalctl -u bot-panel -n 50`. |
| Caddy no consigue certificado | El puerto 80 no está abierto en la consola de Oracle: el desafío de Let's Encrypt entra por ahí. |
| El panel arranca y se para solo | Falta `panel.json`: pon la contraseña (paso 6). |
| Binance devuelve 451 | La máquina está en una región de EE. UU. Hay que recrearla en la UE, o cambiar la fuente a Yahoo (`BTC-EUR`). |
| El agente no opera nunca | Puede ser correcto: mira el diario. `tendencia_vol` se queda en caja si no hay tendencia. |
