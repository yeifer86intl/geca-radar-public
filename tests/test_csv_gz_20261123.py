"""Regresión del error IllegalCharacterError del 22 de noviembre."""
import pandas as pd
from steam_pipeline.exportaciones import exportar_formatos


def test_csv_gz_conserva_control_y_texto_extenso(tmp_path):
    raw = 'more \x03frequently' + (' descripción con saltos\n y "comillas"' * 2000)
    listado = pd.DataFrame([{'appid': 4413220, 'nombre': 'Streetball Legends',
        'lanzamiento_texto':'1 DIC 2026', 'consultado_utc':'2026-11-22T23:00:00Z'}])
    fichas = pd.DataFrame([{'appid':4413220,'ficha_estado':'ok',
        'steam.detailed_description':raw, 'proximo_lanzamiento':True,
        'lanzamiento_ficha_texto':'1 DIC 2026'}])
    result = exportar_formatos(listado, fichas, {'pais':'es','desde':'2026-11-23','hasta':'2027-05-23'}, tmp_path)
    assert set(result) == {'catalogo_new','fichas_new','verificacion'}
    for path in result.values():
        assert path.endswith('.csv.gz')
        assert pd.read_csv(path, compression='gzip', low_memory=False).shape[0] == 1
    actual = pd.read_csv(result['fichas_new'], compression='gzip').loc[0,'steam.detailed_description']
    assert actual == raw


def test_limpieza_xlsx_no_modifica_original():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from build_light_catalog import excel_safe
    original = pd.DataFrame({'nombre':['x\x03y', '=1+2', 'texto normal']})
    limpio = excel_safe(original)
    assert limpio['nombre'].tolist() == ['xy', "'=1+2", 'texto normal']
    assert original.loc[0,'nombre'] == 'x\x03y'
