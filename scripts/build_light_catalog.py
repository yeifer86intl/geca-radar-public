"""Consolida las fichas diarias de Steam en un libro XLSX reproducible.
No sustituye la evidencia diaria exportada. Entrada: maestro_completo.csv y resumen.json.
Las importaciones son idempotentes y las descargas parciales NO producen bajas.
"""
import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd
from datetime import date, datetime
from zoneinfo import ZoneInfo
import calendar
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

FIELDS = ['appid','nombre','lanzamiento','coming_soon','ficha_estado','ficha_verificada_utc',
          'resenas_total','resenas_positivas','resenas_negativas','porcentaje_positivas',
          'url_steam','ficha_url_consulta','fecha_textual_distinta','verificar_fecha_pasada']

def clean_bool(value):
    if pd.isna(value): return ''
    return str(value).strip().lower() in ('true','1','sí','si')

def frame(path):
    if not path.exists(): return pd.DataFrame()
    return pd.read_excel(path, engine='openpyxl', dtype={'appid':str})

def coalesce(row, options):
    for name in options:
        v=row.get(name)
        if v is not None and not (isinstance(v,float) and pd.isna(v)) and str(v).strip() not in ('','nan','None'):
            return v
    return ''

def _normalize_run(runs):
    if runs.empty:
        return runs
    return runs.drop_duplicates(subset=['ejecucion'], keep='last')



def _active_sheet(current, now=None):
    from sys import path as syspath
    import sys
    src = str(Path(__file__).resolve().parents[1] / 'src')
    if src not in syspath:
        syspath.insert(0,src)
    from steam_pipeline.ventana import resolver_ventana
    from steam_pipeline.exportaciones import fecha_exacta
    import yaml
    params = yaml.safe_load((Path(__file__).resolve().parents[1] / 'conf/base/parameters_proximos.yml').read_text(encoding='utf-8'))['proximos']
    start, end = resolver_ventana(params.get('desde'), params.get('hasta'), params.get('ventana_meses', 6), hoy=now)
    # Solo fichas verificadas y con fecha exacta en el horizonte.
    date_values = current['lanzamiento'].map(fecha_exacta)
    status = current['coming_soon'].map(clean_bool)
    ok = current['ficha_estado'].fillna('').astype(str).str.lower().eq('ok')
    # Verificación de ficha fresca (máximo 7 días), evita alertas antiguas.
    seen = pd.to_datetime(current['ficha_verificada_utc'], utc=True, errors='coerce')
    end_utc = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now).tz_localize('America/Caracas').tz_convert('UTC')
    fresh = seen.between(end_utc-pd.Timedelta(days=7), end_utc)
    active = current[status & ok & fresh & date_values.between(pd.Timestamp(start),pd.Timestamp(end)).fillna(False)].copy()
    active['ventana_desde'] = str(start)
    active['ventana_hasta'] = str(end)
    return active


def excel_safe(frame):
    """Limpia solo el formato de intercambio XLSX; los CSV conservan el original."""
    frame = frame.copy()
    for column in frame.select_dtypes(include=['object', 'string']).columns:
        def clean(value):
            if not isinstance(value, str):
                return value
            value = ILLEGAL_CHARACTERS_RE.sub('', value)
            # Evita la inyección de fórmulas cuando el origen es texto de Steam.
            if value.startswith(('=', '+', '-', '@')):
                value = "'" + value
            return value[:32767]
        frame[column] = frame[column].map(clean)
    return frame


def consolidate(result_dir, old_path, out_path):
    runs=sorted(Path(result_dir).rglob('resumen.json'), key=lambda p:p.stat().st_mtime)
    if not runs: raise RuntimeError('No existe resumen.json en resultados Steam')
    summary_path=runs[-1]; folder=summary_path.parent
    summary=json.loads(summary_path.read_text(encoding='utf-8'))
    input_csv=folder/'maestro_completo.csv'
    if not input_csv.is_file(): raise RuntimeError(f'Falta {input_csv}; no se puede construir el catálogo')
    raw=pd.read_csv(input_csv,low_memory=False,dtype={'appid':str})
    if 'appid' not in raw or raw['appid'].isna().any() or raw['appid'].duplicated().any():
        raise ValueError('El maestro completo debe contener AppID únicos y no nulos')
    execution=str(summary.get('ejecucion') or folder.name)
    source_cut=str(summary.get('corte_utc') or '')
    if not source_cut: raise ValueError('resumen.json sin fecha de corte')
    path=Path(old_path)
    if not path.exists():
        raise RuntimeError('Falta el histórico privado: se prohíbe crear uno vacío')
    hist=frame_sheet(path,'historial'); runs_hist=frame_sheet(path,'ejecuciones')
    # No borrar los pendientes históricos. Incorporar su estado actualizado
    # desde la extracción diaria (si existe y fue completada).
    from sys import path as syspath
    src = str(Path(__file__).resolve().parents[1] / 'src')
    if src not in syspath: syspath.insert(0,src)
    from steam_pipeline.pendientes_fecha import cargar_historico, CAMPOS
    pendientes_previos = cargar_historico(path)
    pendientes_diarios = folder / 'pendientes_fecha.csv'
    if pendientes_diarios.is_file():
        pendientes_nuevos = pd.read_csv(pendientes_diarios, dtype={'appid':str},low_memory=False)
        pendientes = pd.concat([pendientes_previos, pendientes_nuevos],ignore_index=True)
        pendientes = pendientes.dropna(subset=['appid']).drop_duplicates('appid',keep='last')
        pendientes = pendientes.reindex(columns=CAMPOS)
    else:
        pendientes = pendientes_previos.reindex(columns=CAMPOS)
    if not runs_hist.empty and execution in runs_hist['ejecucion'].astype(str).values:
        # Idempotente: conservar el estado si el run ya se incorporó.
        print('Ejecución ya consolidada:', execution)
        return str(path)
    records=[]
    for row in raw.to_dict('records'):
        item={
          'appid':str(row['appid']).strip(),
          'nombre':coalesce(row,['nombre','nombre_buscador','nombre_ficha']),
          'lanzamiento':coalesce(row,['lanzamiento_ficha_texto','lanzamiento_texto','fecha_lanzamiento']),
          'coming_soon':clean_bool(coalesce(row,['proximo_lanzamiento','steam.release_date.coming_soon'])),
          'ficha_estado':coalesce(row,['ficha_estado','estado_consulta']),
          'ficha_verificada_utc':coalesce(row,['ficha_consultado_utc','consultado_utc']),
          'resenas_total':coalesce(row,['resenas_total']),
          'resenas_positivas':coalesce(row,['resenas_positivas']),
          'resenas_negativas':coalesce(row,['resenas_negativas']),
          'porcentaje_positivas':coalesce(row,['porcentaje_positivas']),
          'url_steam':coalesce(row,['url_tienda','url_steam']),
          'ficha_url_consulta':coalesce(row,['ficha_url_consulta']),
          'fecha_textual_distinta':clean_bool(coalesce(row,['fecha_textual_distinta'])),
          'verificar_fecha_pasada':clean_bool(coalesce(row,['verificar_fecha_pasada'])),
          'ejecucion':execution,'corte_utc':source_cut
        }
        records.append(item)
    new=pd.DataFrame(records)
    hist=pd.concat([hist,new],ignore_index=True)
    hist['appid']=hist['appid'].astype(str)
    hist=hist.drop_duplicates(subset=['ejecucion','appid'],keep='last')
    # Una ficha vigente por AppID: elegir la última ficha válida; si ninguna fue válida,
    # conservar el último registro marcado para revalidación.
    hist=hist.sort_values(['corte_utc','ejecucion'],kind='stable')
    valid=hist['ficha_estado'].astype(str).str.lower().eq('ok') & hist['ficha_verificada_utc'].fillna('').astype(str).ne('')
    hist['_valida']=valid.astype(int)
    current=hist.sort_values(['appid','_valida','corte_utc'],kind='stable').drop_duplicates('appid',keep='last')
    # Trazabilidad: último registro válido y fecha de su ejecución, sin dar de baja ausentes.
    current=current.drop(columns=['_valida']).sort_values('appid')
    hist=hist.drop(columns=['_valida'])
    entry={'ejecucion':execution,'corte_utc':source_cut,'juegos':len(new),
           'catalogo_completo':bool(summary.get('listado',{}).get('completo',False)),
           'motivo_parada':str(summary.get('listado',{}).get('motivo_parada','')),
           'origen':'maestro_completo.csv'}
    runs_hist=pd.concat([runs_hist,pd.DataFrame([entry])],ignore_index=True)
    dest=Path(out_path);dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix('.tmp.xlsx')
    active = _active_sheet(current)
    if current['appid'].nunique() < 4323 or len(hist) < 22283 or len(runs_hist) < 21:
        raise RuntimeError('El nuevo catálogo no conserva la auditoría mínima de 4.323 juegos, 22.283 observaciones y 21 ejecuciones')
    with pd.ExcelWriter(tmp,engine='openpyxl') as w:
        excel_safe(current).to_excel(w,sheet_name='vigente',index=False)
        excel_safe(hist).to_excel(w,sheet_name='historial',index=False)
        excel_safe(runs_hist).to_excel(w,sheet_name='ejecuciones',index=False)
        excel_safe(active).to_excel(w,sheet_name='seguimiento_activo',index=False)
        excel_safe(pendientes).to_excel(w,sheet_name='pendientes_fecha',index=False)
        # Alias de compatibilidad con lectores Twitch de la versión anterior.
        excel_safe(active).to_excel(w,sheet_name='seguimiento_6_meses',index=False)
    tmp.replace(dest)
    print(json.dumps({'juegos_vigentes':len(current),'observaciones_historicas':len(hist),
         'ejecuciones':len(runs_hist),'seguimiento_activo':len(active),'pendientes_fecha':len(pendientes),'tamano_mb':round(dest.stat().st_size/1048576,2)},ensure_ascii=False))
    return str(dest)

def frame_sheet(path,sheet):
    return pd.read_excel(path,sheet_name=sheet,dtype={'appid':str},engine='openpyxl')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--results',default='data/04_radar')
    p.add_argument('--previous',default='transfer/geca_steam_historico.xlsx')
    p.add_argument('--out',default='transfer/geca_steam_historico.xlsx')
    a=p.parse_args()
    consolidate(a.results,a.previous,a.out)
