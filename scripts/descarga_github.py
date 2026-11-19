
import argparse
import csv
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ============================================
# CONFIGURACION GECA RADAR
# ============================================

REPO = "yeifer86intl/geca-radar"
WORKFLOW = "radar.yml"

SHAREPOINT = Path(
    r"C:\Users\pc\OneDrive - Imagina Media Audiovisual S.L\GECA_radar"
)

ARTIFACTS = ["resultados-radar", "estado-radar"]

HORA_VENEZUELA = timezone(timedelta(hours=-4))


# ============================================
# GITHUB CLI
# ============================================

def gh(*args):
    resultado = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if resultado.returncode != 0:
        raise RuntimeError(
            resultado.stderr.strip()
            or f"Error ejecutando GitHub CLI"
        )

    return resultado.stdout


def obtener_ejecuciones():
    """Consulta ejecuciones exitosas y sus metadatos."""

    salida = gh(
        "api",
        "--paginate",
        f"repos/{REPO}/actions/workflows/"
        f"{WORKFLOW}/runs?per_page=100&status=success",
        "--jq",
        ".workflow_runs[] | @json",
    )

    ejecuciones = [
        json.loads(linea)
        for linea in salida.splitlines()
        if linea.strip()
    ]

    return sorted(
        ejecuciones,
        key=lambda x: x["id"],
        reverse=True,
    )


def obtener_artifacts(run_id):
    """Consulta artifacts vigentes en GitHub."""

    salida = gh(
        "api",
        "--paginate",
        f"repos/{REPO}/actions/runs/"
        f"{run_id}/artifacts?per_page=100",
        "--jq",
        ".artifacts[] | @json",
    )

    artifacts = {}

    for linea in salida.splitlines():
        if not linea.strip():
            continue

        artifact = json.loads(linea)

        if (
            artifact["name"] in ARTIFACTS
            and not artifact.get("expired", False)
        ):
            artifacts[artifact["name"]] = artifact

    return artifacts


# ============================================
# FECHAS Y METADATOS
# ============================================

def convertir_fecha(fecha_utc):
    if not fecha_utc:
        return None

    fecha = datetime.fromisoformat(
        fecha_utc.replace("Z", "+00:00")
    )

    return fecha.astimezone(HORA_VENEZUELA)


def crear_metadata(run, artifacts):
    """Genera información de trazabilidad."""

    run_id = run["id"]

    inicio = convertir_fecha(
        run.get("run_started_at")
        or run.get("created_at")
    )

    creacion = convertir_fecha(
        run.get("created_at")
    )

    metadata = {
        "run_id": run_id,
        "run_number": run.get("run_number"),
        "workflow": WORKFLOW,
        "repositorio": REPO,
        "fecha_creacion_venezuela": (
            creacion.strftime("%Y-%m-%d %H:%M:%S")
            if creacion else None
        ),
        "fecha_inicio_venezuela": (
            inicio.strftime("%Y-%m-%d")
            if inicio else None
        ),
        "hora_inicio_venezuela": (
            inicio.strftime("%H:%M:%S")
            if inicio else None
        ),
        "zona_horaria": "America/Caracas UTC-04:00",
        "fecha_inicio_utc": run.get("run_started_at"),
        "estado": run.get("conclusion"),
        "evento": run.get("event"),
        "rama": run.get("head_branch"),
        "commit": run.get("head_sha"),
        "url_github": run.get("html_url"),
        "artifacts": [
            {
                "nombre": a["name"],
                "id": a["id"],
                "tamano_comprimido_bytes": a.get(
                    "size_in_bytes"
                ),
                "fecha_creacion_utc": a.get("created_at"),
            }
            for a in artifacts.values()
        ],
    }

    carpeta = SHAREPOINT / str(run_id)
    carpeta.mkdir(parents=True, exist_ok=True)

    ruta = carpeta / "metadata.json"

    ruta.write_text(
        json.dumps(
            metadata,
            indent=4,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return metadata


# ============================================
# DESCARGA DE ARTIFACTS
# ============================================

def descargar_artifact(run_id, nombre):
    destino = SHAREPOINT / str(run_id) / nombre
    marcador = destino / ".descarga_completa"

    if marcador.exists():
        print(f"  Ya descargado: {nombre}")
        return False

    destino.mkdir(parents=True, exist_ok=True)

    print(f"  Descargando: {nombre}")

    # GitHub CLI extrae los archivos directamente
    # respetando las carpetas internas del artifact.
    gh(
        "run",
        "download",
        str(run_id),
        "--repo",
        REPO,
        "--name",
        nombre,
        "--dir",
        str(destino),
    )

    archivos = [
        p for p in destino.rglob("*")
        if p.is_file() and p != marcador
    ]

    if not archivos:
        raise RuntimeError(
            f"El artifact {nombre} no contiene archivos."
        )

    marcador.write_text(
        f"run_id={run_id}\nartifact={nombre}\n",
        encoding="utf-8",
    )

    print(f"  OK: {nombre} ({len(archivos)} archivos)")
    return True


# ============================================
# HISTORIAL GENERAL CSV
# ============================================

def guardar_historial(registros):
    ruta = SHAREPOINT / "historial_geca.csv"

    columnas = [
        "run_id",
        "run_number",
        "fecha_inicio_venezuela",
        "hora_inicio_venezuela",
        "estado",
        "evento",
        "rama",
        "commit",
        "url_github",
        "artifacts_disponibles",
    ]

    # Conservar también registros anteriores.
    anteriores = {}

    if ruta.exists():
        with ruta.open(
            "r", encoding="utf-8-sig", newline=""
        ) as archivo:
            for fila in csv.DictReader(archivo):
                anteriores[str(fila["run_id"])] = fila

    for registro in registros:
        anteriores[str(registro["run_id"])] = registro

    with ruta.open(
        "w", encoding="utf-8-sig", newline=""
    ) as archivo:
        escritor = csv.DictWriter(
            archivo,
            fieldnames=columnas,
            extrasaction="ignore",
        )

        escritor.writeheader()

        for fila in sorted(
            anteriores.values(),
            key=lambda x: int(x["run_id"]),
            reverse=True,
        ):
            escritor.writerow(fila)

    print(f"\nHistorial actualizado: {ruta}")


# ============================================
# PROCESAMIENTO
# ============================================

def procesar_run(run):
    run_id = run["id"]

    print("\n" + "=" * 50)
    print(f"RUN ID: {run_id}")
    print(f"RUN NUMERO: {run.get('run_number')}")

    inicio = convertir_fecha(
        run.get("run_started_at")
        or run.get("created_at")
    )

    if inicio:
        print(
            "FECHA Y HORA VENEZUELA: "
            f"{inicio:%Y-%m-%d %H:%M:%S}"
        )

    print(f"ESTADO: {run.get('conclusion')}")
    print(f"GITHUB: {run.get('html_url')}")

    artifacts = obtener_artifacts(run_id)

    # Siempre actualizar metadata, incluso si los
    # artifacts ya se habían descargado.
    metadata = crear_metadata(run, artifacts)

    descargados = 0
    existentes = 0

    for nombre in ARTIFACTS:
        if nombre not in artifacts:
            print(f"  No disponible: {nombre}")
            continue

        if descargar_artifact(run_id, nombre):
            descargados += 1
        else:
            existentes += 1

    registro = {
        "run_id": run_id,
        "run_number": run.get("run_number"),
        "fecha_inicio_venezuela": metadata[
            "fecha_inicio_venezuela"
        ],
        "hora_inicio_venezuela": metadata[
            "hora_inicio_venezuela"
        ],
        "estado": run.get("conclusion"),
        "evento": run.get("event"),
        "rama": run.get("head_branch"),
        "commit": run.get("head_sha"),
        "url_github": run.get("html_url"),
        "artifacts_disponibles": ", ".join(
            artifacts.keys()
        ),
    }

    return registro, descargados, existentes


# ============================================
# MENU PRINCIPAL
# ============================================

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--ultimo", action="store_true"
    )
    parser.add_argument(
        "--todos", action="store_true"
    )

    args = parser.parse_args()

    if args.ultimo and args.todos:
        parser.error(
            "Selecciona --ultimo o --todos, no ambos."
        )

    print("\n=== GECA RADAR -> SHAREPOINT ===")

    if not SHAREPOINT.is_dir():
        raise RuntimeError(
            f"No existe OneDrive: {SHAREPOINT}"
        )

    if args.ultimo:
        opcion = "1"
    elif args.todos:
        opcion = "2"
    else:
        print("\n1. Descargar el último")
        print("2. Descargar todos")
        print("0. Salir")

        opcion = input(
            "\nSelecciona una opción: "
        ).strip()

    if opcion == "0":
        return

    if opcion not in {"1", "2"}:
        raise ValueError("Opción inválida.")

    ejecuciones = obtener_ejecuciones()

    if not ejecuciones:
        print("No hay ejecuciones exitosas.")
        return

    if opcion == "1":
        ejecuciones = ejecuciones[:1]

    registros = []
    descargados = 0
    existentes = 0
    errores = 0

    for run in ejecuciones:
        try:
            registro, nuevos, previos = procesar_run(run)

            registros.append(registro)
            descargados += nuevos
            existentes += previos

        except Exception as error:
            errores += 1
            print(f"ERROR en run {run['id']}: {error}")

    if registros:
        guardar_historial(registros)

    print("\n========== RESUMEN ==========")
    print(f"Ejecuciones consultadas: {len(ejecuciones)}")
    print(f"Artifacts descargados: {descargados}")
    print(f"Artifacts ya existentes: {existentes}")
    print(f"Errores: {errores}")
    print(f"Destino: {SHAREPOINT}")
    print(
        "Verifica la sincronización en OneDrive."
    )

    if errores:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
