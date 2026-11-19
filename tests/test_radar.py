import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
import pytest
from steam_pipeline.frescura import leer_cache_vigente
from steam_pipeline import radar
from steam_pipeline.descargas import steam_fichas_completas as fichas

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)

@pytest.mark.parametrize('edad,esperado', [(0, True), (7, True), (7.001, False), (-1, False)])
def test_caducidad(tmp_path, edad, esperado):
    p = tmp_path/'1.json'
    p.write_text(json.dumps(dict(url='u', consultado_utc=(NOW-timedelta(days=edad)).isoformat(),
                                respuesta={'1': {'success':True, 'data':{}}})))
    assert (leer_cache_vigente(p, 'u', 1, 7, NOW) is not None) == esperado

@pytest.mark.parametrize('contenido', ['{', '{}', '{"consultado_utc":"incorrecta"}'])
def test_cache_corrupta(tmp_path, contenido):
    p = tmp_path/'1.json';p.write_text(contenido)
    assert leer_cache_vigente(p, 'u', 1, 7, NOW) is None


def test_error_no_es_cache_valida(tmp_path):
    p = tmp_path/'1.json'
    p.write_text(json.dumps(dict(url='u', consultado_utc=NOW.isoformat(), respuesta={'1':{'success':False}})))
    assert leer_cache_vigente(p, 'u', 1, 7, NOW) is None


def test_frescura_y_estado():
    t = pd.DataFrame(dict(appid=[1,2,3,4], proximo_lanzamiento=[True,True,True,False],
                         ficha_estado=['ok','ok','error','ok'],
                         ficha_consultado_utc=[NOW.isoformat(),(NOW+timedelta(seconds=1)).isoformat(),NOW.isoformat(),NOW.isoformat()]))
    assert radar.evaluar_fichas(t, NOW).regla_lanzamiento_pdf.tolist() == [True, False, False, False]


def test_historial_no_duplica_cache(tmp_path):
    db = tmp_path/'historial.sqlite'
    t = pd.DataFrame([dict(appid=1, fecha=NOW.isoformat(), ficha_desde_cache=False, valor='a')])
    radar.registrar_historial(db, '1', NOW.isoformat(), [('ficha', t, 'fecha', {})], {})
    t['ficha_desde_cache'] = True
    radar.registrar_historial(db, '2', NOW.isoformat(), [('ficha', t, 'fecha', {})], {})
    with sqlite3.connect(db) as con:
        assert con.execute('select count(*) from observaciones').fetchone()[0] == 1
        assert con.execute('select count(*) from ejecucion_observacion').fetchone()[0] == 2


def test_descargador_reutiliza_y_fuerza(tmp_path, monkeypatch):
    llamadas=[]
    def consulta(*args):
        llamadas.append(1)
        return {'1': {'success':True, 'data':{'name':'Juego'}}}
    monkeypatch.setattr(fichas, '_consulta', consulta)
    juegos=pd.DataFrame({'appid':[1]})
    a=fichas.descargar_fichas_completas(juegos, carpeta=tmp_path, pausa=0)
    b=fichas.descargar_fichas_completas(juegos, carpeta=tmp_path, pausa=0)
    assert len(llamadas)==1
    assert a.ficha_consultado_utc.iloc[0] == b.ficha_consultado_utc.iloc[0]
    assert b.ficha_desde_cache.iloc[0]
    fichas.descargar_fichas_completas(juegos, carpeta=tmp_path, pausa=0, actualizar=True)
    assert len(llamadas)==2


@pytest.mark.parametrize('pregunta,publicado,completo', [(False,False,True),(True,False,True),(True,True,True),(True,False,False)])
def test_radar_selectivo(tmp_path, monkeypatch, pregunta, publicado, completo):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(radar, 'exportar_formatos', lambda *args: {})
    monkeypatch.setattr(radar, 'ahora_utc', lambda: NOW)
    juegos = pd.DataFrame([dict(appid=1,nombre='Juego',consultado_utc=NOW.isoformat(),
                                lanzamiento_texto='1 nov 2026',precision_fecha='anio',periodo_fin='2027-12-31')])
    monkeypatch.setattr(radar, 'descargar_proximos_steam', lambda **kw: dict(juegos=juegos,sin_fecha=juegos.iloc[:0],resumen={'completo':completo}))
    llamadas=[]
    def descargar(j, **kw):
        llamadas.append((j.appid.tolist(),kw['actualizar']))
        return pd.DataFrame([dict(appid=a, ficha_estado='ok', ficha_consultado_utc=NOW.isoformat(),
                                  proximo_lanzamiento=not (publicado and kw['actualizar']),
                                  lanzamiento_ficha_texto='1 nov 2026') for a in j.appid],
                            columns=['appid','ficha_estado','ficha_consultado_utc','proximo_lanzamiento','lanzamiento_ficha_texto'])
    monkeypatch.setattr(radar,'descargar_fichas_completas',descargar)
    opiniones=[]
    def resenas(j, **kw):
        opiniones.extend(j.appid.tolist())
        return dict(resumen=pd.DataFrame([dict(appid=a,estado='ok',consultado_utc=NOW.isoformat(),resenas_total=30,resenas_positivas=24,resenas_negativas=6,porcentaje_positivas=80) for a in j.appid],
                                        columns=['appid','estado','consultado_utc','resenas_total','resenas_positivas','resenas_negativas','porcentaje_positivas']),
                    comentarios=pd.DataFrame(columns=['appid','recommendationid']))
    monkeypatch.setattr(radar,'extraer_resenas',resenas)
    cfg=dict(zona_horaria='America/Caracas',horizonte_dias=180,max_edad_dias=7,max_propuestas=3,
             carpeta_estado='estado',carpeta_salida='data/04_radar',preguntas_geca={'1':'¿Narrativa?'} if pregunta else {})
    if not completo:
        with pytest.raises(RuntimeError, match='parcial'):
            radar.ejecutar_radar(dict(pais='es',plataforma='win',filtro='comingsoon',desde='2026-10-27',hasta='2026-11-02'),
                dict(incluir_sin_fecha=False,limite_juegos=None),dict(pais='es',idioma='spanish'),
                dict(idiomas=['all'],tipo_compra=1,excluir_offtopic=True),cfg)
        return
    result=radar.ejecutar_radar(dict(pais='es',plataforma='win',filtro='comingsoon',desde='2026-10-27',hasta='2026-11-02'),
          dict(incluir_sin_fecha=False,limite_juegos=None),dict(pais='es',idioma='spanish'),
          dict(idiomas=['all'],tipo_compra=1,excluir_offtopic=True),cfg)
    assert result['propuestas'] == int(pregunta and not publicado)
    assert llamadas[0] == ([1],False)
    assert llamadas[1] == ([1] if pregunta else [],True)
    assert opiniones == [1]
    # El nuevo pipeline no duplica el JSON completo en el estado operativo.
    assert not (tmp_path/'estado/historial.sqlite').exists()

@pytest.mark.parametrize('vacio', [False, True])
def test_pipeline_radar_con_descargadores_reales(tmp_path, monkeypatch, vacio):
    from urllib.parse import parse_qs, urlparse
    from kedro.config import OmegaConfigLoader
    from kedro.io import DataCatalog, MemoryDataset
    from kedro.runner import SequentialRunner
    from steam_pipeline.pipeline_registry import register_pipelines
    from steam_pipeline.descargas import steam_proximos_paginados as p, steam_resenas as r
    root = Path(__file__).resolve().parents[1]
    params=OmegaConfigLoader(str(root/'conf'),base_env='base',default_run_env='local')['parameters']
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(radar, 'exportar_formatos', lambda *args: {})
    monkeypatch.setattr(radar,'ahora_utc',lambda: NOW)
    def pagina(*args):
        html='' if vacio else '<a class="search_result_row" href="https://store.steampowered.com/app/1/"><span class="title">Juego</span><div class="search_released">1 nov 2026</div></a>'
        return dict(results_html=html,total_count=0 if vacio else 1,start=0)
    monkeypatch.setattr(p,'_obtener_json',pagina)
    monkeypatch.setattr(fichas,'_consulta',lambda *args: {'1':{'success':True,'data':{'name':'Juego','release_date':{'coming_soon':True,'date':'1 nov 2026'}}}})
    monkeypatch.setattr(r,'_consultar',lambda *args: ({'query_summary':{'total_reviews':30,'total_positive':24,'total_negative':6}},NOW.isoformat()))
    # La fecha real de fichas debe ser anterior al corte simulado.
    class Clock:
        @staticmethod
        def now(tz): return NOW-timedelta(seconds=1)
    monkeypatch.setattr(fichas,'datetime',Clock)
    params['radar']['preguntas_geca']={'1':'¿Qué narrativa explorar?'}
    cat=DataCatalog()
    for k,v in params.items():cat[f'params:{k}']=MemoryDataset(data=v)
    SequentialRunner().run(register_pipelines()['radar'],cat)
    resumen=json.loads(next(Path('data/04_radar').glob('*/resumen.json')).read_text())
    assert resumen['propuestas']==(0 if vacio else 1)
    carpeta=next(Path('data/04_radar').iterdir())
    legible=pd.read_csv(carpeta/'maestro.csv',sep=';')
    assert len(legible)==(0 if vacio else 1)
    assert len(legible.columns)==13
    assert (carpeta/'maestro_completo.csv').is_file()



@pytest.mark.parametrize('total,porcentaje,estado,lanzamiento,esperado', [
    (30,80,'ok',True,True), (29,100,'ok',True,False),
    (30,79.99,'ok',True,False), (100,95,'ok',True,True),
    (0,None,'ok',True,False), (None,None,'ok',True,False),
    (30,80,'error',True,False), (30,80,'ok',False,False),
    ('30','80','ok',True,True), (30,101,'ok',True,False),
])
def test_recepcion_umbral(total,porcentaje,estado,lanzamiento,esperado):
    datos=pd.DataFrame([dict(appid=1,nombre='Juego',resenas_total=total,
                            porcentaje_positivas=porcentaje,resenas_estado=estado,
                            regla_lanzamiento_pdf=lanzamiento)])
    resultado=radar.evaluar_recepcion(datos)
    assert bool(resultado.candidato_recomendado.iloc[0]) == lanzamiento
    assert bool(resultado.recepcion_favorable.iloc[0] and lanzamiento) == esperado
    legible=radar.construir_listado(resultado)
    assert len(legible)==int(lanzamiento)
    assert 'resenas_positivas' in legible
    assert 'resenas_negativas' in legible


def test_recepcion_vacia():
    datos=pd.DataFrame(columns=['appid','nombre','resenas_total','porcentaje_positivas',
                                'resenas_estado','regla_lanzamiento_pdf'])
    resultado=radar.construir_listado(radar.evaluar_recepcion(datos))
    assert resultado.empty
    assert len(resultado.columns)==13
