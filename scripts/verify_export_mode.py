"""Fail fast when GitHub is running the old Excel exporter."""
from pathlib import Path
import inspect
from steam_pipeline.exportaciones import exportar_formatos

source = inspect.getsource(exportar_formatos)
if '.csv.gz' not in source or 'to_csv(' not in source:
    raise SystemExit('ERROR: exportaciones.py antiguo: no exporta CSV.GZ')
if 'to_excel(' in source or 'ExcelWriter(' in source:
    raise SystemExit('ERROR: exportaciones.py aun escribe Excel')
workflow = Path('.github/workflows/radar.yml').read_text(encoding='utf-8')
if 'data/04_radar/**/*.csv.gz' not in workflow:
    raise SystemExit('ERROR: el workflow no publica los CSV.GZ')
print('OK: exportaciones.py usa CSV.GZ y radar.yml publica los archivos')
