# Desplegar el bot en una máquina propia

> **Estado: aparcado.** El bot vive en GitHub Actions, y eso ya cumple el
> objetivo — opera con el portátil apagado y sin pagar nada. Esta guía sirve
> para el día que tengas una máquina propia: una Raspberry Pi, un portátil
> viejo, un mini PC o un VPS. Nada de lo que hay aquí es específico de ningún
> proveedor.

## Qué te daría una máquina propia que GitHub Actions no da

| | GitHub Actions | Máquina propia |
|---|---|---|
| Fuente de precios | Yahoo (los ejecutores son de EE. UU. y Binance los bloquea) | **Binance**, con IP española |
| Control | Editar un fichero y hacer commit | **Panel web con botones**: arrancar, pausar, crear agentes |
| Laboratorio | No | **Backtests desde el navegador** |
| Latido | Una vez por vela, sondeando cada 30 min | Proceso vivo, reacción inmediata |
| Coste | 0 € | 0 € si el trasto ya lo tienes |

## Lo que hay preparado

```
despliegue/instalar.sh      instala todo en un Ubuntu limpio, de un comando
despliegue/subir.sh         sube el código desde el Mac y reinstala
despliegue/bot-panel.service  servicio de systemd, con reinicio automático
despliegue/Caddyfile        HTTPS automático con Let's Encrypt
web/clave.py                pone la contraseña del panel
```

Todo probado salvo `instalar.sh` contra un Ubuntu real, que nunca llegó a
ejecutarse por falta de máquina.

## Cómo se haría

```bash
./despliegue/subir.sh usuario@ip
ssh usuario@ip
sudo -u bot /opt/bot/.venv/bin/python /opt/bot/web/clave.py
sudo systemctl start bot-panel
```

No hace falta dominio: el instalador usa `sslip.io`, que resuelve
`88-12-34-56.sslip.io` a esa IP sin registrarse en nada, y Let's Encrypt emite
el certificado contra ese nombre.

El panel **se niega a escuchar fuera del equipo sin contraseña**, así que no se
puede publicar por accidente. La contraseña se guarda como hash PBKDF2 con sal
(400.000 iteraciones) y la sesión va firmada con HMAC.

## Por qué se descartó Oracle Cloud

La capa «siempre gratis» de Oracle era, sobre el papel, la única opción gratuita
de verdad con IP europea. En la práctica **no tiene máquinas libres**:

```
133 intentos entre las 00:53 y las 16:20, alternando las dos formas gratuitas
Out of capacity for shape VM.Standard.E2.1.Micro in availability domain AD-1
Out of capacity for shape VM.Standard.A1.Flex    in availability domain AD-1
```

Madrid tiene un único dominio de disponibilidad y el cupo gratuito está agotado.
La región de origen no se puede cambiar después, y los recursos Always Free sólo
existen en ella. No es un problema de configuración: es que no hay sitio.

Lo que sí quedó montado en esa cuenta, por si algún día se libera: red `vcn-bot`
con subred pública, pasarela de internet y los puertos 22, 80 y 443 abiertos.
Son recursos gratuitos y no caducan.

`despliegue/cazar-maquina.py` sigue ahí y funciona — pide una máquina cada 5
minutos hasta que haya hueco, con espera creciente si Oracle limita las
peticiones. Si algún día quieres volver a intentarlo:

```bash
~/.local/share/oci-sdk/venv/bin/python despliegue/cazar-maquina.py
```

### Lo que aprendimos de Oracle, por si vuelve a hacer falta

- El límite de peticiones es **por cuenta** y sobre la creación de instancias,
  no por forma de máquina. Medido: por debajo de ~90 s entre intentos devuelve
  429, por encima de ~2 min responde de verdad. Y un 429 **no llega a comprobar
  la capacidad**: insistir más rápido esconde el hueco en vez de encontrarlo.
- La recuperación de máquinas inactivas se aplica **sólo a las ARM**. Las AMD
  `E2.1.Micro` están exentas, y un bot que late cada 4 horas entra de lleno en
  la definición de inactivo.
- Binance responde HTTP 451 a las IP de EE. UU. La región tiene que ser europea.
