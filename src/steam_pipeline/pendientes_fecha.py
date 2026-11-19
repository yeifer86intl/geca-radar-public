"""Cola persistente de fechas no confirmadas; no infiere fechas de estreno.

La hoja pendientes_fecha vive en el histórico XLSX de cada release. La lista
Steam se observa diariamente y la ficha appdetails se revisa como máximo cada
siete días por juego, con presupuesto diario explícito y cola priorizada.
"""
from pathlib import Path
import pandas as pd
from steam_pipeline.exportaciones import fecha_exacta

CAMPOS = ["appid", "nombre", "lanzamiento_texto", "url_tienda",
          "primera_observacion_utc", "ultima_observacion_utc", "ultima_verificacion_utc",
          "proxima_verificacion_utc", "ultimo_intento_utc", "estado_pendiente", "fecha_ficha_texto",
          "ficha_estado", "fecha_confirmada", "cambio_texto_detectado"]


def cargar_historico(path='transfer/geca_steam_historico.xlsx'):
    archivo = Path(path)
    if not archivo.is_file():
        return pd.DataFrame(columns=CAMPOS)
    with pd.ExcelFile(archivo, engine='openpyxl') as xls:
        if 'pendientes_fecha' not in xls.sheet_names:
            return pd.DataFrame(columns=CAMPOS)
        tabla = pd.read_excel(xls, sheet_name='pendientes_fecha', dtype={'appid': str})
    return tabla.reindex(columns=CAMPOS).dropna(subset=['appid']).drop_duplicates('appid', keep='last')


def preparar_pendientes(listado, historico, ahora, cupo=1200, intervalo=7):
    """Devuelve estado observado y AppIDs a revisar, primero vencidos y antiguos.

    No hace una consulta por cada pendiente al verlo en el listado. Si cambia el
    texto público, adelanta inmediatamente la revisión de su ficha.
    """
    if isinstance(cupo, bool) or not isinstance(cupo, int) or cupo < 0:
        raise ValueError('max_pendientes_por_dia debe ser entero >= 0')
    ahora = pd.Timestamp(ahora)
    if ahora.tzinfo is None:
        raise ValueError('ahora debe tener zona horaria UTC')
    nuevo = listado.copy().drop_duplicates('appid')
    if nuevo.empty:
        return historico.reindex(columns=CAMPOS).copy(), nuevo, 0
    if 'appid' not in nuevo:
        raise ValueError('Listado de pendientes sin appid')
    nuevo['appid'] = nuevo['appid'].astype('int64').astype(str)
    anterior = {str(x['appid']): x for x in historico.reindex(columns=CAMPOS).to_dict('records')}
    filas=[]
    for x in nuevo.to_dict('records'):
        appid = x['appid']
        previo = anterior.get(appid, {})
        texto = str(x.get('lanzamiento_texto') or '').strip()
        previo_texto = str(previo.get('lanzamiento_texto') or '').strip()
        anterior_fecha = pd.to_datetime(previo.get('ultima_verificacion_utc'), utc=True, errors='coerce')
        ultimo_intento = pd.to_datetime(previo.get('ultimo_intento_utc'), utc=True, errors='coerce')
        cambio = bool(previo and texto.casefold() != previo_texto.casefold())
        vencido = pd.isna(anterior_fecha) or ahora - anterior_fecha >= pd.Timedelta(days=intervalo) or cambio
        datos = {campo: previo.get(campo) for campo in CAMPOS}
        datos.update(appid=appid, nombre=x.get('nombre'), lanzamiento_texto=texto,
                     url_tienda=x.get('url_tienda'), ultima_observacion_utc=ahora.isoformat(),
                     primera_observacion_utc=previo.get('primera_observacion_utc') if pd.notna(previo.get('primera_observacion_utc')) else ahora.isoformat(),
                     cambio_texto_detectado=cambio,
                     estado_pendiente='pendiente_verificacion' if vencido else 'en_seguimiento')
        if pd.notna(anterior_fecha):
            datos['proxima_verificacion_utc']=(anterior_fecha + pd.Timedelta(days=intervalo)).isoformat()
        else:
            datos['proxima_verificacion_utc']=None
        datos['_vencido']=vencido
        # Los nunca verificados tienen prioridad, pero sin dejar que errores
        # repetidos de algunos AppIDs bloqueen toda la cola.
        datos['_prioridad_fecha']=anterior_fecha if pd.notna(anterior_fecha) else ultimo_intento
        filas.append(datos)
    frame=pd.DataFrame(filas)
    por_revisar=frame.loc[frame['_vencido']].sort_values(['_prioridad_fecha','appid'],
                              na_position='first',kind='stable').head(cupo)
    ids=set(por_revisar['appid'])
    consulta=nuevo[nuevo.appid.isin(ids)].copy()
    # Preserve older pending entries not visible in today's Steam listing; never delete history.
    antiguos=historico.copy()
    if not antiguos.empty:
        antiguos=antiguos.loc[~antiguos.appid.astype(str).isin(set(frame.appid))]
    frame=frame.drop(columns=['_vencido','_prioridad_fecha'])
    return pd.concat([antiguos,frame], ignore_index=True).reindex(columns=CAMPOS),consulta,int(sum(x['_vencido'] for x in filas))


def aplicar_verificaciones(estado, verificaciones, ahora, desde, hasta, intervalo=7):
    if estado.empty or verificaciones.empty:
        return estado, pd.DataFrame(columns=['appid'])
    ahora=pd.Timestamp(ahora)
    tabla=estado.copy().set_index('appid',drop=False)
    promovidos=[]
    for fila in verificaciones.to_dict('records'):
        aid=str(int(fila['appid']))
        if aid not in tabla.index:
            continue
        estado_ficha=fila.get('ficha_estado')
        consulta=pd.to_datetime(fila.get('ficha_consultado_utc'),utc=True,errors='coerce')
        texto=fila.get('lanzamiento_ficha_texto')
        fecha=fecha_exacta(texto)
        confirmado=(estado_ficha=='ok' and pd.notna(fecha) and
                    bool(fila.get('proximo_lanzamiento') is True) and
                    pd.Timestamp(desde)<=fecha<=pd.Timestamp(hasta))
        if pd.notna(consulta) and estado_ficha=='ok':
            tabla.at[aid,'ultima_verificacion_utc']=consulta.isoformat()
            tabla.at[aid,'proxima_verificacion_utc']=(consulta + pd.Timedelta(days=intervalo)).isoformat()
        tabla.at[aid,'ultimo_intento_utc']=ahora.isoformat()
        tabla.at[aid,'ficha_estado']=estado_ficha
        tabla.at[aid,'fecha_ficha_texto']=texto
        tabla.at[aid,'fecha_confirmada']=fecha.isoformat() if pd.notna(fecha) else None
        tabla.at[aid,'estado_pendiente']=('promovido_activo' if confirmado else
             'en_seguimiento' if estado_ficha=='ok' else 'error_reintentar')
        if confirmado:
            promovidos.append({'appid':int(aid), 'fecha_confirmada':fecha, 'lanzamiento_ficha_texto':texto})
    return tabla.reset_index(drop=True),pd.DataFrame(promovidos,columns=['appid','fecha_confirmada','lanzamiento_ficha_texto'])
