"""Restauración segura del histórico desde un release del MISMO repositorio público.

El respaldo inicial versionado solo se utiliza con --inicializar y si el
release todavía no existe. Nunca se reinicia silenciosamente el histórico.
"""
import argparse
import os
import shutil
import subprocess
from pathlib import Path

import pandas as pd

TAG = "estado-geca"
FILE = "geca_steam_historico.xlsx"
MIN = (4323, 22283, 21)


def verificar(book):
    with pd.ExcelFile(book, engine="openpyxl") as xls:
        required = {"vigente", "historial", "ejecuciones"}
        if not required.issubset(xls.sheet_names):
            raise RuntimeError(f"Faltan hojas del histórico: {required - set(xls.sheet_names)}")
        counts = tuple(len(pd.read_excel(xls, sheet_name=k, usecols=["appid"] if k != "ejecuciones" else None)) for k in ("vigente", "historial", "ejecuciones"))
    if any(a < b for a,b in zip(counts, MIN)):
        raise RuntimeError(f"El respaldo está incompleto: {counts} < {MIN}")
    return counts


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--inicializar", action="store_true", help="Solo para el primer arranque, desde bootstrap")
    args=parser.parse_args()
    repo=os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY debe identificar el repositorio público")
    dest=Path("transfer") / FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    env=os.environ.copy()
    env["GH_TOKEN"] = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    probe=subprocess.run(["gh","release","view",TAG,"--repo",repo],capture_output=True,text=True,env=env)
    if probe.returncode == 0:
        result=subprocess.run(["gh","release","download",TAG,"--repo",repo,"--pattern",FILE,"--dir",str(dest.parent),"--clobber"],capture_output=True,text=True,env=env)
        if result.returncode or not dest.is_file():
            raise RuntimeError("No se pudo descargar el histórico existente. No se hará reinicialización automática: " + result.stderr[:350])
        method="release publicado"
    elif args.inicializar:
        seed=Path("bootstrap") / FILE
        if not seed.is_file():
            raise RuntimeError("No se encuentra el archivo histórico inicial en bootstrap/")
        shutil.copy2(seed,dest)
        method="respaldo inicial (arranque explícito)"
    else:
        raise RuntimeError("Falta el release histórico 'estado-geca'. Si es el primer arranque, ejecuta manualmente con inicializar_desde_respaldo=true; de lo contrario, investiga el fallo sin sobrescribirlo.")
    counts=verificar(dest)
    print(f"Histórico recuperado de {method}: juegos={counts[0]}, observaciones={counts[1]}, ejecuciones={counts[2]}",flush=True)

if __name__ == '__main__':
    main()
