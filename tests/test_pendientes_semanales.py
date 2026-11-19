from datetime import datetime,timezone,timedelta
import pandas as pd
from steam_pipeline.pendientes_fecha import preparar_pendientes,aplicar_verificaciones,CAMPOS

NOW=pd.Timestamp('2026-11-19T13:00:00Z')
def listado(n=4):
    return pd.DataFrame([dict(appid=i,nombre=f'Juego {i}',lanzamiento_texto='Próximamente',url_tienda=f'https://store.steampowered.com/app/{i}/') for i in range(1,n+1)])

def test_pendientes_cupo_y_persistencia():
    estado, cola, vencidos=preparar_pendientes(listado(),pd.DataFrame(columns=CAMPOS),NOW,cupo=2)
    assert len(estado)==4 and len(cola)==2 and vencidos==4
    observaciones=pd.DataFrame([dict(appid=i,ficha_estado='ok',ficha_consultado_utc=NOW.isoformat(),
                                   proximo_lanzamiento=True,lanzamiento_ficha_texto='Próximamente') for i in cola.appid])
    estado,promovidos=aplicar_verificaciones(estado,observaciones,NOW,pd.Timestamp('2026-11-19'),pd.Timestamp('2027-02-19'))
    assert promovidos.empty
    estado, siguiente, vencidos=preparar_pendientes(listado(),estado,NOW+pd.Timedelta(days=1),cupo=2)
    assert len(siguiente)==2 and set(siguiente.appid)=={'3','4'}
    estado, ultimo, vencidos=preparar_pendientes(listado(),estado,NOW+pd.Timedelta(days=7),cupo=2)
    assert set(ultimo.appid)=={'3','4'}  # Sin verificación previa, los nunca consultados van primero

def test_cambio_texto_adelanta_revision():
    anterior=pd.DataFrame([dict(appid='1',nombre='Juego 1',lanzamiento_texto='Próximamente',
                                   ultima_verificacion_utc=NOW.isoformat())]).reindex(columns=CAMPOS)
    ahora=listado(1)
    ahora.loc[0,'lanzamiento_texto']='Enero 2027'
    estado, cola, vencidos=preparar_pendientes(ahora,anterior,NOW+pd.Timedelta(days=1))
    assert len(cola)==1 and bool(estado.cambio_texto_detectado.iloc[0])

def test_promover_si_ficha_confirma_fecha():
    estado,cola,_=preparar_pendientes(listado(1),pd.DataFrame(columns=CAMPOS),NOW)
    f=pd.DataFrame([dict(appid=1,ficha_estado='ok',ficha_consultado_utc=NOW.isoformat(),
                           proximo_lanzamiento=True,lanzamiento_ficha_texto='15 ene 2027')])
    actualizado,promovidos=aplicar_verificaciones(estado,f,NOW,pd.Timestamp('2026-11-19'),pd.Timestamp('2027-02-19'))
    assert len(promovidos)==1
    assert actualizado.estado_pendiente.iloc[0]=='promovido_activo'

def test_estado_no_borra_anteriores():
    anterior=pd.DataFrame([dict(appid='999',nombre='Antiguo',lanzamiento_texto='2027')]).reindex(columns=CAMPOS)
    estado,_,_=preparar_pendientes(listado(1),anterior,NOW)
    assert set(estado.appid)=={'999','1'}

def test_radar_aplica_pendientes_y_promocion(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from steam_pipeline import radar
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(radar,'ahora_utc',lambda:NOW.to_pydatetime())
    monkeypatch.setattr(radar,'exportar_formatos',lambda *args:{})
    dentro=pd.DataFrame([dict(appid=1,nombre='Con fecha',lanzamiento_texto='15 ene 2027',
        url_tienda='https://store.steampowered.com/app/1/',consultado_utc=NOW.isoformat())])
    pendientes=pd.DataFrame([dict(appid=2,nombre='Sin fecha',lanzamiento_texto='Próximamente',
        url_tienda='https://store.steampowered.com/app/2/',consultado_utc=NOW.isoformat())])
    monkeypatch.setattr(radar,'descargar_proximos_steam', lambda **kw:{'juegos':dentro,'sin_fecha':pendientes,
         'resumen':{'completo':True}})
    consultados=[]
    def descargar(j,**kw):
        consultados.extend(j.appid.tolist())
        return pd.DataFrame([dict(appid=int(i),ficha_estado='ok',ficha_consultado_utc=NOW.isoformat(),
               ficha_desde_cache=False,proximo_lanzamiento=True,lanzamiento_ficha_texto='15 ene 2027')
               for i in j.appid],columns=['appid','ficha_estado','ficha_consultado_utc',
               'ficha_desde_cache','proximo_lanzamiento','lanzamiento_ficha_texto'])
    monkeypatch.setattr(radar,'descargar_fichas_completas',descargar)
    def fake_resenas(j,**kw):
        res=pd.DataFrame([dict(appid=int(i),estado='ok',consultado_utc=NOW.isoformat(),
            resenas_total=30,resenas_positivas=24,resenas_negativas=6,porcentaje_positivas=80)
            for i in j.appid],columns=['appid','estado','consultado_utc','resenas_total',
            'resenas_positivas','resenas_negativas','porcentaje_positivas'])
        return {'resumen':res,'comentarios':pd.DataFrame(columns=['appid','recommendationid'])}
    monkeypatch.setattr(radar,'extraer_resenas',fake_resenas)
    conf=dict(max_edad_dias=7,max_propuestas=3,max_pendientes_por_dia=1,
              carpeta_estado='estado',carpeta_salida='data/04_radar',preguntas_geca={})
    cfg=dict(pais='es',idioma='spanish',pausa=0,carpeta='data/01_raw/fichas')
    resultado=radar.ejecutar_radar(dict(desde='2026-11-19',hasta='2027-02-19',
        ventana_meses=3,pais='es',plataforma=None,filtro='comingsoon'),
        dict(incluir_sin_fecha=False,limite_juegos=None),cfg,
        dict(idiomas=['all'],tipo_compra=1,excluir_offtopic=True),conf)
    assert set(consultados)=={1,2}
    assert resultado['pendientes_verificados_hoy']==1
    salida=next(Path('data/04_radar').glob('*/pendientes_fecha.csv'))
    df=pd.read_csv(salida)
    assert df.loc[df.appid.eq(2),'estado_pendiente'].iloc[0]=='promovido_activo'
    maestro=pd.read_csv(next(Path('data/04_radar').glob('*/maestro_completo.csv')))
    assert set(maestro.appid)=={1,2}
