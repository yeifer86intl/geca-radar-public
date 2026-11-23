"""Steam: solo dos activos en UN release, no cientos de backups completos."""
import hashlib, os, subprocess, tempfile
from pathlib import Path
import pandas as pd

TAG='estado-geca'

def gh(*args):
    p=subprocess.run(['gh',*args],capture_output=True,text=True,encoding='utf-8')
    if p.returncode:raise RuntimeError('GitHub CLI: '+' '.join(args)+'\n'+p.stderr)
    return p.stdout

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def counts(p):
    with pd.ExcelFile(p,engine='openpyxl') as w:
        return tuple(len(pd.read_excel(w,sheet_name=s,usecols=['appid'] if s!='ejecuciones' else None)) for s in ('vigente','historial','ejecuciones'))

def main():
    repo=os.environ['GITHUB_REPOSITORY']
    old=Path('transfer/geca_steam_anterior.xlsx')
    current=Path('transfer/geca_steam_historico.xlsx')
    if not old.is_file() or not current.is_file():raise RuntimeError('Falta original o actualización')
    if any(a<b for a,b in zip(counts(current),counts(old))):raise RuntimeError('Pérdida de filas: no publicar')
    q=subprocess.run(['gh','release','view',TAG,'-R',repo],capture_output=True)
    if q.returncode:
        gh('release','create',TAG,'-R',repo,'--title','GECA Steam estado vigente',
           '--notes','Solo estado vigente y copia de seguridad inmediata.','--latest=false')
    # Publicar PRIMERO una copia verificada antes de modificar el estado actual.
    gh('release','upload',TAG,str(old),'-R',repo,'--clobber')
    with tempfile.TemporaryDirectory() as tmp:
        gh('release','download',TAG,'-R',repo,'--pattern',old.name,'--dir',tmp)
        if sha(Path(tmp)/old.name)!=sha(old):raise RuntimeError('Backup previo no verificable')
    gh('release','upload',TAG,str(current),'-R',repo,'--clobber')
    with tempfile.TemporaryDirectory() as tmp:
        gh('release','download',TAG,'-R',repo,'--pattern',current.name,'--dir',tmp)
        if sha(Path(tmp)/current.name)!=sha(current):raise RuntimeError('Estado nuevo no verificable')
    print('Steam publicado: solo respaldo previo + estado actual')

if __name__=='__main__':main()
