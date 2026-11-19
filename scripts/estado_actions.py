"""Restaura estado de la última ejecución exitosa; no reinicia silenciosamente."""
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True, encoding='utf-8')


def restaurar():
    branch = os.environ['RADAR_BRANCH']
    runs = json.loads(gh('run', 'list', '--workflow', 'radar.yml', '--branch', branch,
                         '--status', 'success', '--limit', '1', '--json', 'databaseId'))
    if not runs:
        print('Primera ejecución exitosa pendiente: se inicia sin estado anterior.')
        return
    folder = Path('_estado_anterior'); folder.mkdir(exist_ok=True)
    gh('run', 'download', str(runs[0]['databaseId']), '-n', 'estado-radar', '-D', str(folder))
    # Si el artefacto caducó o no está disponible, gh falla y detiene el workflow.
    with zipfile.ZipFile(folder / 'estado.zip') as z:
        for item in z.infolist():
            path = Path(item.filename)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'estado':
                raise ValueError('Ruta inesperada dentro del estado.')
        z.extractall('.')
    if not Path('estado/historial.sqlite').is_file():
        raise RuntimeError('Estado restaurado sin historial; revisar antes de continuar.')


def empaquetar():
    if not Path('estado/historial.sqlite').is_file():
        raise RuntimeError('No hay historial para conservar.')
    with zipfile.ZipFile('estado.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for p in Path('estado').rglob('*'):
            if p.is_file():
                z.write(p, p.as_posix())


if __name__ == '__main__':
    {'restaurar': restaurar, 'empaquetar': empaquetar}[sys.argv[1]]()
