"""Exporta únicamente filas nuevas/cambiadas del XLSX maestro Steam."""
import argparse, gzip, json
from pathlib import Path
import pandas as pd

def clean(x):
    if pd.isna(x):return None
    if hasattr(x,'isoformat'):return x.isoformat()
    return str(x) if not isinstance(x,(int,float,bool)) else x

def records(path,sheet):
    if not Path(path).is_file():raise FileNotFoundError(path)
    df=pd.read_excel(path,sheet_name=sheet,engine='openpyxl',dtype={'appid':str})
    return [{k:clean(v) for k,v in row.items()} for row in df.to_dict('records')]

def export(before,after,out,repo,run):
    before_current={str(r['appid']):r for r in records(before,'vigente')}
    current=records(after,'vigente')
    before_history={(str(r['ejecucion']),str(r['appid'])) for r in records(before,'historial')}
    history=records(after,'historial')
    emitted=[]
    for row in current:
        appid=str(row.get('appid') or '').strip()
        if not appid or appid=='None':continue
        if row==before_current.get(appid):continue
        payload={'coming_soon':row.get('coming_soon'),'ficha_estado':row.get('ficha_estado'),
                 'url_steam':row.get('url_steam'),'source_row':row}
        emitted.append({'table':'steam_games','row':{
            'steam_appid':appid,'steam_name':row.get('nombre') or appid,
            'release_date':row.get('lanzamiento'),
            'reviews_total':row.get('resenas_total'),'reviews_positive':row.get('resenas_positivas'),
            'reviews_negative':row.get('resenas_negativas'),
            'verified_utc':row.get('ficha_verificada_utc'),
            'payload_json':json.dumps(payload,ensure_ascii=False,default=str),
            'updated_utc':row.get('corte_utc') or row.get('ficha_verificada_utc') or ''}})
    for r in history:
        key=(str(r.get('ejecucion')),str(r.get('appid')))
        if key in before_history:continue
        emitted.append({'table':'steam_observation_history','row':{
            'source_run':key[0],'steam_appid':key[1],
            'observed_utc':r.get('corte_utc') or '',
            'evidence_json':json.dumps(r,ensure_ascii=False,default=str)}})
    Path(out).parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(out,'wt',encoding='utf-8') as f:
        f.write(json.dumps({'_manifest':{'source':repo,'run_id':str(run),'kind':'steam'}},ensure_ascii=False)+'\n')
        for event in emitted:f.write(json.dumps(event,ensure_ascii=False,default=str,separators=(',',':'))+'\n')
    print(json.dumps({'filas_incrementales':len(emitted),'bytes':Path(out).stat().st_size}))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('before','after','out','repo','run'):p.add_argument('--'+k,required=True)
    a=p.parse_args();export(a.before,a.after,a.out,a.repo,a.run)
