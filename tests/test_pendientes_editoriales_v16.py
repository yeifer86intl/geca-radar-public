import pandas as pd
from steam_pipeline.pendientes_fecha import CAMPOS, senales_editoriales_pendientes

NOW=pd.Timestamp('2026-11-19T13:00:00Z')

def registro(fecha='2026-11-18T13:00:00Z', proximo=True, texto='2027', ok='ok'):
    return pd.DataFrame([dict(appid='123', nombre='Juego pendiente', lanzamiento_texto='2027',
        fecha_ficha_texto=texto, ultima_verificacion_utc=fecha, proximo_lanzamiento_ficha=proximo,
        ficha_estado=ok,estado_pendiente='en_seguimiento',url_tienda='https://store.steampowered.com/app/123/')]).reindex(columns=CAMPOS)

def test_pendiente_2027_senal_sin_promocion():
    r=senales_editoriales_pendientes(registro(), NOW, {123:'¿Vale la pena seguirlo?'})
    assert len(r)==1 and r.tipo_senal.iloc[0]=='lanzamiento_fecha_imprecisa'
    assert 'NO acreditar' in r.incertidumbre_fecha.iloc[0]

def test_pendiente_vencido_o_no_confirmado_no_es_senal():
    assert senales_editoriales_pendientes(registro(fecha='2026-11-01T13:00:00Z'),NOW,{123:'Pregunta'}).empty
    assert senales_editoriales_pendientes(registro(proximo=False),NOW,{123:'Pregunta'}).empty
    assert senales_editoriales_pendientes(registro(texto='15 ene 2027'),NOW,{123:'Pregunta'}).empty
    sin_pregunta=senales_editoriales_pendientes(registro(),NOW,{})
    assert len(sin_pregunta)==1 and sin_pregunta.pregunta_geca.isna().all()

def test_radar_propone_pendiente_sin_afirmar_tres_meses(tmp_path,monkeypatch):
    from pathlib import Path
    from steam_pipeline import radar
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(radar,'ahora_utc',lambda: NOW.to_pydatetime())
    monkeypatch.setattr(radar,'exportar_formatos',lambda *args: {})
    vacios=pd.DataFrame(columns=['appid','nombre','lanzamiento_texto','url_tienda','consultado_utc'])
    pendientes=pd.DataFrame([dict(appid=123,nombre='Juego 2027',lanzamiento_texto='2027',
        url_tienda='https://store.steampowered.com/app/123/',consultado_utc=NOW.isoformat())])
    monkeypatch.setattr(radar,'descargar_proximos_steam',lambda **kw:{'juegos':vacios,'sin_fecha':pendientes,'resumen':{'completo':True}})
    def descargar(j,**kw):
        return pd.DataFrame([dict(appid=int(i),ficha_estado='ok',ficha_consultado_utc=NOW.isoformat(),
            ficha_desde_cache=False,proximo_lanzamiento=True,lanzamiento_ficha_texto='2027') for i in j.appid],
            columns=['appid','ficha_estado','ficha_consultado_utc','ficha_desde_cache','proximo_lanzamiento','lanzamiento_ficha_texto'])
    monkeypatch.setattr(radar,'descargar_fichas_completas',descargar)
    monkeypatch.setattr(radar,'extraer_resenas',lambda j,**kw:{'resumen':pd.DataFrame(columns=['appid','estado','resenas_total','porcentaje_positivas']),
       'comentarios':pd.DataFrame(columns=['appid','recommendationid'])})
    cfg=dict(max_edad_dias=7,max_propuestas=3,max_pendientes_por_dia=10,
       carpeta_estado='estado',carpeta_salida='salida',preguntas_geca={'123':'¿Seguir su estreno?'})
    result=radar.ejecutar_radar(dict(desde='2026-11-19',hasta='2027-02-19',ventana_meses=3,
        pais='es',plataforma=None,filtro='comingsoon'),dict(incluir_sin_fecha=False,limite_juegos=None),
        dict(pais='es',idioma='spanish'),dict(idiomas=['all'],tipo_compra=1,excluir_offtopic=True),cfg)
    out=next(Path('salida').iterdir())
    propuestas=pd.read_csv(out/'propuestas.csv')
    assert result['juegos']==0
    assert result['propuestas']==1
    assert propuestas.iloc[0]['tipo_senal']=='lanzamiento_fecha_imprecisa'
    assert 'NO acreditar' in propuestas.iloc[0]['incertidumbre_fecha']
    assert pd.read_csv(out/'maestro_completo.csv').empty
