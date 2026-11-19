"""Guarda el histórico públicamente en un release del mismo repositorio.

Hace copia inmutable del respaldo anterior antes de actualizar estado-geca.
Los releases son públicos: no subir datos privados ni secretos.
"""
import os
import subprocess
from pathlib import Path
import pandas as pd

FILE="geca_steam_historico.xlsx"

def counts(p):
    with pd.ExcelFile(p, engine="openpyxl") as book:
        return tuple(len(pd.read_excel(book, sheet_name=s, usecols=["appid"] if s != "ejecuciones" else None)) for s in ("vigente", "historial", "ejecuciones"))

def call(*args, allow_fail=False):
    env = os.environ.copy()
    env["GH_TOKEN"]=os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN", "")
    proc=subprocess.run(["gh",*args],env=env,text=True,capture_output=True)
    if proc.returncode and not allow_fail:
        raise RuntimeError(f"GitHub CLI falló: {proc.stderr[:400]}")
    return proc

def main():
    repo=os.environ.get("GITHUB_REPOSITORY","")
    run=os.environ.get("GITHUB_RUN_ID","")
    if not repo or not run:
        raise RuntimeError("Se necesitan GITHUB_REPOSITORY y GITHUB_RUN_ID")
    before=Path('transfer/geca_steam_anterior.xlsx')
    after=Path('transfer') / FILE
    if not before.is_file() or not after.is_file():
        raise RuntimeError("Falta copia anterior o catálogo nuevo")
    old,new=counts(before),counts(after)
    if any(n<o for n,o in zip(new,old)):
        raise RuntimeError(f"Prohibido publicar menos datos: {old} -> {new}")
    # Publicar primero una copia inmutable para que siempre haya recuperación posible.
    backup_tag='respaldo-geca-'+run
    call('release','create',backup_tag,str(before),'--repo',repo,
         '--title',f'Respaldo previo a {run}', '--notes','Respaldo inmutable del catálogo anterior.')
    if call('release','view','estado-geca','--repo',repo,allow_fail=True).returncode:
        call('release','create','estado-geca',str(after),'--repo',repo,
             '--title','GECA estado histórico actual', '--notes','Estado ligero compartido con Twitch.')
    else:
        call('release','upload','estado-geca',str(after),'--repo',repo,'--clobber')
    print(f"Publicado catálogo público: {old} -> {new}",flush=True)

if __name__=='__main__':
    main()
