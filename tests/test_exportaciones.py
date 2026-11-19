import pandas as pd
from steam_pipeline.exportaciones import construir_formatos, fecha_exacta, CATALOGO, FICHAS, VERIFICACION


def datos():
    listado=pd.DataFrame([dict(appid=1,nombre='Juego',lanzamiento_texto='28 OCT 2026',
                               region='es',url_tienda='https://store.steampowered.com/app/1/',
                               consultado_utc='2026-10-28T12:00:00+00:00'),
                          dict(appid=2,nombre='Sin ficha',lanzamiento_texto='Próximamente')])
    fichas=pd.DataFrame([{'appid':1,'ficha_region':'us','ficha_idioma':'english',
                         'ficha_estado':'ok','ficha_consultado_utc':'2026-10-28T12:01:00+00:00',
                         'lanzamiento_ficha_texto':'28 OCT 2026','proximo_lanzamiento':True,
                         'steam.name':'Juego','steam.release_date.coming_soon':True}])
    return listado,fichas,dict(desde='2026-10-27',hasta='2026-11-02',pais='es')


def test_formatos_columnas_y_valores():
    t=construir_formatos(*datos())
    assert list(t['catalogo_new'])==CATALOGO
    assert list(t['fichas_new'])==FICHAS
    assert list(t['verificacion'])==VERIFICACION
    assert (len(CATALOGO),len(FICHAS),len(VERIFICACION))==(10,76,86)
    assert t['fichas_new'].iloc[0].region=='us'
    assert t['verificacion'].iloc[0].region=='es'
    assert t['fichas_new'].iloc[0].estado_lanzamiento=='Próximo lanzamiento'
    assert t['fichas_new'].iloc[0].coincide_filtro
    assert t['verificacion'].iloc[1].isna()['estado_consulta']
    assert t['catalogo_new'][''].tolist()==[0,1]


def test_fechas_desconocidas():
    assert pd.isna(fecha_exacta('Próximamente'))
    assert pd.isna(fecha_exacta('31 DIC 9998'))
    assert fecha_exacta('28 OCT 2026')==pd.Timestamp('2026-10-28')


def test_tablas_vacias():
    listado,fichas,p=datos()
    tablas=construir_formatos(listado.iloc[:0],fichas.iloc[:0],p)
    assert all(t.empty for t in tablas.values())
    assert list(tablas['verificacion'])==VERIFICACION


def test_fecha_fuera_filtro_y_publicado():
    listado,fichas,p=datos()
    fichas.loc[0,'proximo_lanzamiento']=False
    fichas.loc[0,'lanzamiento_ficha_texto']='21 OCT 2026'
    t=construir_formatos(listado,fichas,p)['fichas_new']
    assert not t.iloc[0].coincide_filtro
    assert t.iloc[0].estado_lanzamiento=='Ya estrenado'
