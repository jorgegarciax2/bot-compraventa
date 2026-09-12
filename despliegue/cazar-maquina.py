#!/usr/bin/env python3
"""Pide una máquina gratuita a Oracle una y otra vez hasta que haya hueco.

El *free tier* de Oracle reserva un cupo limitado por región. Cuando se agota,
`LaunchInstance` responde «Out of capacity» y no queda otra que insistir: los
huecos aparecen cuando alguien destruye su instancia, sin previo aviso.

    python3 despliegue/cazar-maquina.py                  # prueba AMD y, si no, ARM
    python3 despliegue/cazar-maquina.py --formas amd     # sólo la AMD
    python3 despliegue/cazar-maquina.py --intervalo 600   # aún más suave

Al conseguirla escribe ~/.oci/bot-maquina.json con la IP y avisa por pantalla y
con una notificación de macOS. No borra ni toca nada más: si ya existe una
instancia con el mismo nombre, se planta y avisa.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".local/share/oci-sdk/venv/lib/python3.9/site-packages"))
import oci                                                        # noqa: E402

OBJETIVO = Path.home() / ".oci" / "bot-objetivo.json"
RESULTADO = Path.home() / ".oci" / "bot-maquina.json"
CLAVE_PUB = Path.home() / ".ssh" / "oracle-bot.pub"
NOMBRE = "bot-compraventa"

FORMAS = {
    "amd": {"shape": "VM.Standard.E2.1.Micro", "imagen": "imagen_amd", "config": None,
            "nota": "1 GB, exenta de recuperación por inactividad"},
    "arm": {"shape": "VM.Standard.A1.Flex", "imagen": "imagen_arm",
            "config": {"ocpus": 1.0, "memory_in_gbs": 6.0},
            "nota": "6 GB, pero Oracle puede recuperarla si queda inactiva 7 días"},
}


def ahora() -> str:
    return datetime.now().strftime("%H:%M:%S")


def avisar(titulo: str, texto: str) -> None:
    """Notificación de macOS. Si falla, no pasa nada: el registro ya lo dice."""
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification {json.dumps(texto)} with title {json.dumps(titulo)}'],
                       check=False, capture_output=True, timeout=10)
    except Exception:
        pass
    print("\a", end="", flush=True)


def ya_existe(cmp_, compartimento: str):
    for i in cmp_.list_instances(compartment_id=compartimento).data:
        if i.display_name == NOMBRE and i.lifecycle_state not in ("TERMINATED", "TERMINATING"):
            return i
    return None


def intentar(cmp_, obj: dict, forma: str, clave: str):
    f = FORMAS[forma]
    detalles = oci.core.models.LaunchInstanceDetails(
        availability_domain=obj["ad"],
        compartment_id=obj["tenancy"],
        display_name=NOMBRE,
        shape=f["shape"],
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=obj[f["imagen"]]),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=obj["subnet"], assign_public_ip=True),
        metadata={"ssh_authorized_keys": clave},
    )
    if f["config"]:
        detalles.shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(**f["config"])
    return cmp_.launch_instance(detalles).data


def esperar_ip(cmp_, net, obj: dict, instancia_id: str) -> str | None:
    """Espera a que arranque y devuelve su IP pública."""
    for _ in range(60):
        inst = cmp_.get_instance(instancia_id).data
        if inst.lifecycle_state == "RUNNING":
            break
        time.sleep(10)
    for _ in range(30):
        vnics = cmp_.list_vnic_attachments(compartment_id=obj["tenancy"],
                                           instance_id=instancia_id).data
        for v in vnics:
            if v.lifecycle_state == "ATTACHED":
                ip = net.get_vnic(v.vnic_id).data.public_ip
                if ip:
                    return ip
        time.sleep(10)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Insiste hasta conseguir una máquina gratuita")
    ap.add_argument("--formas", default="amd,arm",
                    help="orden de preferencia: amd, arm, o amd,arm")
    ap.add_argument("--intervalo", type=float, default=300.0,
                    help="segundos entre intentos. Medido en esta cuenta: por debajo "
                         "de ~120 s Oracle devuelve 429 y el intento se desperdicia")
    ap.add_argument("--max-horas", type=float, default=0, help="0 = sin límite")
    a = ap.parse_args()

    if not OBJETIVO.exists():
        print(f"Falta {OBJETIVO}.", file=sys.stderr)
        return 1
    obj = json.loads(OBJETIVO.read_text())
    clave = CLAVE_PUB.read_text().strip()
    orden = [f.strip() for f in a.formas.split(",") if f.strip() in FORMAS]
    if not orden:
        print("--formas debe incluir amd y/o arm", file=sys.stderr)
        return 1

    cfg = oci.config.from_file()
    cmp_ = oci.core.ComputeClient(cfg)
    net = oci.core.VirtualNetworkClient(cfg)

    existente = ya_existe(cmp_, obj["tenancy"])
    if existente:
        print(f"Ya hay una instancia «{NOMBRE}» ({existente.lifecycle_state}). No hago nada.")
        return 0

    print(f"Cazando máquina gratuita en {cfg['region']}. Orden: {', '.join(orden)}.")
    for f in orden:
        print(f"  {FORMAS[f]['shape']:24s} — {FORMAS[f]['nota']}")
    print(f"Una ronda cada ~{a.intervalo:.0f} s. Ctrl-C para parar.\n")

    # El límite de Oracle es POR CUENTA y sobre LaunchInstance, no por forma:
    # medido en esta cuenta, los intentos separados menos de ~90 s devuelven 429
    # y los de más de ~2 min reciben respuesta real. Y un 429 no comprueba la
    # capacidad: sólo renueva el castigo. Por eso conviene ir despacio — insistir
    # más rápido no encuentra el hueco antes, lo esconde.
    ESPERA_MAXIMA = 1800.0      # tope de 30 min tras varios 429 seguidos

    inicio = time.time()
    intento = 0
    castigo = 0.0
    siguiente = 0.0
    while True:
        espera = siguiente - time.time()
        if espera > 0:
            time.sleep(min(espera, 60.0))
            continue

        forma = orden[intento % len(orden)]
        intento += 1
        try:
            inst = intentar(cmp_, obj, forma, clave)
            print(f"\n[{ahora()}] ¡CONSEGUIDA! {FORMAS[forma]['shape']} — {inst.id}")
            avisar("Bot de compraventa", f"Máquina conseguida ({forma.upper()}). Buscando IP…")
            ip = esperar_ip(cmp_, net, obj, inst.id)
            RESULTADO.write_text(json.dumps({
                "id": inst.id, "forma": FORMAS[forma]["shape"], "familia": forma,
                "ip": ip, "conseguida": datetime.now().isoformat(timespec="seconds"),
            }, indent=2))
            print(f"[{ahora()}] IP pública: {ip}")
            print(f"[{ahora()}] Guardado en {RESULTADO}")
            if forma == "arm":
                print("\n  AVISO: es la ARM. Oracle puede recuperarla si pasa 7 días\n"
                      "  con CPU, red y memoria por debajo del 20 %. Las AMD están exentas.")
            avisar("Bot de compraventa", f"Lista en {ip}" if ip else "Lista (sin IP aún)")
            return 0

        except oci.exceptions.ServiceError as e:
            msg = (e.message or "").lower()
            if "out of capacity" in msg or (e.status == 500 and "capacity" in msg):
                castigo = 0.0
                siguiente = time.time() + a.intervalo + random.uniform(0, 30)
                print(f"[{ahora()}] #{intento} {forma}: sin capacidad · "
                      f"siguiente en {a.intervalo/60:.0f} min", flush=True)
            elif e.status == 429 or "too many requests" in msg:
                castigo = min(ESPERA_MAXIMA, max(a.intervalo, castigo * 2))
                siguiente = time.time() + castigo + random.uniform(0, 60)
                print(f"[{ahora()}] #{intento} {forma}: limitada por Oracle "
                      f"(no ha llegado a mirar capacidad) · espero "
                      f"{castigo/60:.0f} min", flush=True)
            elif e.status in (401, 403):
                print(f"\n[{ahora()}] Sin autorización: {e.message}", file=sys.stderr)
                return 1
            elif "limitexceeded" in (e.code or "").lower():
                print(f"\n[{ahora()}] Límite de la cuenta alcanzado: {e.message}",
                      file=sys.stderr)
                return 1
            else:
                siguiente = time.time() + a.intervalo
                print(f"[{ahora()}] #{intento} {forma}: {e.status} {e.code} "
                      f"— {e.message}", flush=True)

        if a.max_horas and (time.time() - inicio) > a.max_horas * 3600:
            print(f"\n[{ahora()}] Alcanzadas {a.max_horas} h sin suerte. Lo dejo.")
            return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nParado. Vuelve a lanzarlo cuando quieras: no se pierde nada.")
