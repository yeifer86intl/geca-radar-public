"""Migración única: utiliza el CSV creado por la auditoría de los maestros históricos.
No borra el respaldo ZIP/SQLite. Se ejecuta localmente UNA VEZ antes del primer push.
"""
import argparse
from pathlib import Path
import pandas as pd

parser=argparse.ArgumentParser()
parser.add_argument('--input',required=True,help='historial_juegos_steam.csv de la auditoría')
parser.add_argument('--out',default='transfer/geca_steam_historico.xlsx')
a=parser.parse_args()
df=pd.read_csv(a.input,sep=';',encoding='utf-8-sig',dtype={'appid':str,'run_id':str})
required={'appid','nombre','fecha_lanzamiento_texto','ficha_verificada_utc','coming_soon','run_id','corte_utc'}
if not required.issubset(df.columns):raise ValueError('Faltan columnas: '+str(required-set(df.columns)))
if df['appid'].isna().any():raise ValueError('AppID nulos en auditoría')
base=pd.DataFrame({
 'appid':df.appid,'nombre':df.nombre,'lanzamiento':df.fecha_lanzamiento_texto,
 'coming_soon':df.coming_soon.astype(str).str.lower().eq('true'),
 'ficha_estado':df.ficha_verificada_utc.notna().map({True:'ok',False:'pendiente'}),
 'ficha_verificada_utc':df.ficha_verificada_utc,
 'resenas_total':'','resenas_positivas':'','resenas_negativas':'',
 'porcentaje_positivas':'','url_steam':'','ficha_url_consulta':'',
 'fecha_textual_distinta':False,'verificar_fecha_pasada':False,
 'ejecucion':df.run_id,'corte_utc':df.corte_utc})
base=base.drop_duplicates(['ejecucion','appid'],keep='last').sort_values(['corte_utc','ejecucion'])
valid=base.ficha_estado.eq('ok')
current=base.assign(_valid=valid).sort_values(['appid','_valid','corte_utc']).drop_duplicates('appid',keep='last').drop(columns=['_valid'])
runs=base.groupby('ejecucion',as_index=False).agg(corte_utc=('corte_utc','max'),juegos=('appid','size'))
runs['catalogo_completo']=False;runs['motivo_parada']='origen_auditoria';runs['origen']='historial_juegos_steam.csv'
out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
with pd.ExcelWriter(out,engine='openpyxl') as w:
 current.to_excel(w,sheet_name='vigente',index=False)
 base.to_excel(w,sheet_name='historial',index=False)
 runs.to_excel(w,sheet_name='ejecuciones',index=False)
print('Migración:',len(current),'AppID,',len(base),'observaciones; creado',out)
