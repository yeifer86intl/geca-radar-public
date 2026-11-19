"""Pruebas sin conexión: ejecutan los descargadores con respuestas simuladas."""
import inspect
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import pandas as pd
import pytest
from kedro.config import OmegaConfigLoader
from kedro.io import DataCatalog, MemoryDataset
from kedro.runner import SequentialRunner
from steam_pipeline.descargas import steam_proximos_paginados as proximos
from steam_pipeline.descargas import steam_resenas as resenas
from steam_pipeline.descargas import steam_fichas_completas as fichas
from steam_pipeline.pipelines.steam.pipeline import create_pipeline
from steam_pipeline.pipelines.steam.nodes import seleccionar_juegos

ROOT = Path(__file__).resolve().parents[1]

def configuracion():
    loader = OmegaConfigLoader(str(ROOT / 'conf'), base_env='base', default_run_env='local')
    return loader['parameters'], loader['catalog']

def test_parametros_completos():
    params, _ = configuracion()
    for nombre, funcion in [('proximos',proximos.descargar_proximos_steam),
                            ('resenas',resenas.extraer_resenas),
                            ('fichas',fichas.descargar_fichas_completas)]:
        esperados = set(inspect.signature(funcion).parameters) - {'df_juegos'}
        assert set(params[nombre]) == esperados

@pytest.mark.parametrize('vacio', [False, True])
def test_pipeline_completo(tmp_path, monkeypatch, vacio):
    params, config = configuracion()
    monkeypatch.chdir(tmp_path)
    def pagina(url, pausa):
        fechas = ['22 oct 2026', '15 mar 2027', '16 mar 2027', 'Próximamente']
        html = ''.join(f'<a class="search_result_row" href="https://store.steampowered.com/app/{i}/">'
                       f'<span class="title">Juego {i}</span><div class="search_released">{f}</div></a>'
                       for i, f in enumerate(fechas, 1)) if not vacio else ''
        return {'results_html':html, 'total_count': 0 if vacio else 4, 'start':0}
    monkeypatch.setattr(proximos, '_obtener_json', pagina)
    llamados = {'resenas':[], 'fichas':[]}
    def opiniones(p, *args):
        llamados['resenas'].append(p['appid'])
        return {'query_summary':{'total_reviews':1,'total_positive':1,'total_negative':0},
                'reviews':[{'recommendationid':'1','review':'Texto simulado','voted_up':True}]}, '2026-10-27T00:00:00Z'
    def ficha(url, pausa):
        appid = parse_qs(urlparse(url).query)['appids'][0]
        llamados['fichas'].append(int(appid))
        return {appid:{'success':True, 'data':{'name':'Juego simulado','genres':[{'id':'1','description':'Acción'}]}}}
    monkeypatch.setattr(resenas, '_consultar', opiniones)
    monkeypatch.setattr(fichas, '_consulta', ficha)
    params['proximos'].update(desde='2026-10-22', hasta='2027-03-15')
    params['resenas']['descargar_comentarios'] = True
    params['seleccion']['incluir_sin_fecha'] = False
    catalog = DataCatalog.from_config(config)
    for k,v in params.items():
        catalog[f'params:{k}'] = MemoryDataset(data=v)
    SequentialRunner().run(create_pipeline(), catalog)
    final = pd.read_csv('data/03_primary/juegos_enriquecidos.csv')
    esperados = [] if vacio else [1,2]
    assert final.appid.tolist() == esperados
    assert llamados['resenas'] == esperados
    assert llamados['fichas'] == esperados
    assert len(pd.read_csv('data/02_intermediate/comentarios.csv')) == len(esperados)
    assert json.loads(Path('data/02_intermediate/resumen_descarga.json').read_text())['completo']
    if not vacio:
        assert json.loads(final.iloc[0]['steam.genres'])[0]['id'] == '1'

def test_seleccion():
    juegos = pd.DataFrame({'appid':[1,2]})
    sin_fecha = pd.DataFrame({'appid':[2,3]})
    assert seleccionar_juegos(juegos,sin_fecha,{'incluir_sin_fecha':True,'limite_juegos':None}).appid.tolist()==[1,2,3]
    assert seleccionar_juegos(juegos,sin_fecha,{'incluir_sin_fecha':False,'limite_juegos':1}).appid.tolist()==[1]

def test_fecha_invalida():
    with pytest.raises(ValueError, match='posterior'):
        proximos.descargar_proximos_steam(desde='2027-03-15', hasta='2026-10-22')

def test_entorno_prueba():
    from steam_pipeline.settings import CONFIG_LOADER_ARGS
    loader = OmegaConfigLoader(str(ROOT / 'conf'), env='prueba', **CONFIG_LOADER_ARGS)
    params = loader['parameters']
    assert params['proximos']['max_paginas'] == 2
    assert params['proximos']['max_paginas'] == 2
    assert params['seleccion']['limite_juegos'] == 5
    assert params['seleccion']['incluir_sin_fecha'] is True
