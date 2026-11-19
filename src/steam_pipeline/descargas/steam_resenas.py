"""Reseñas públicas de Steam: resumen por juego y comentarios opcionales.

Dependencia: pip install pandas
Importar no inicia consultas. No requiere steam_tablas.py ni API key.
Fuente: https://partner.steamgames.com/doc/webapi/IUserReviewsService
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import pandas as pd

ENDPOINT = 'https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/'


def _consultar(parametros, carpeta, pausa, actualizar):
    clave = hashlib.sha256(json.dumps(parametros, sort_keys=True).encode()).hexdigest()
    ruta = carpeta / (clave + '.json')
    if ruta.exists() and not actualizar:
        paquete = json.loads(ruta.read_text(encoding='utf-8'))
        return paquete['respuesta'], paquete['consultado_utc']
    url = ENDPOINT + '?' + urlencode({'input_json': json.dumps(parametros)})
    for intento in range(5):
        try:
            time.sleep(pausa)
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=35) as r:
                bruto = json.load(r)
            respuesta = bruto.get('response', bruto)
            if isinstance(respuesta, dict) and 'reviews' not in respuesta:
                q = respuesta.get('query_summary', {})
                # Steam omite arrays vacíos. Exigir evidencia explícita de cero
                # o una página posterior con cursor y sin resultados.
                cero = respuesta.get('total_matching') == 0 or (
                    isinstance(q, dict) and q.get('total_reviews') == 0)
                fin_paginacion = parametros.get('cursor', '*') != '*' and 'cursor' in respuesta
                if cero or fin_paginacion:
                    respuesta['reviews'] = []
            if not isinstance(respuesta, dict) or not isinstance(respuesta.get('reviews'), list):
                raise ValueError('Steam no devolvió una lista de reseñas válida.')
            marca = datetime.now(timezone.utc).isoformat()
            tmp = ruta.with_suffix('.tmp')
            tmp.write_text(json.dumps({'respuesta': respuesta, 'consultado_utc': marca}, ensure_ascii=False), encoding='utf-8')
            tmp.replace(ruta)
            return respuesta, marca
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            if intento == 4:
                raise
            espera = 2 ** (intento + 1)
            if isinstance(exc, HTTPError):
                if exc.code not in (429, 500, 502, 503, 504):
                    raise
                retry = exc.headers.get('Retry-After', '')
                if retry.isdigit():
                    espera = max(espera, int(retry))
                elif retry:
                    try:
                        espera = max(espera, (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
                    except (TypeError, ValueError):
                        pass
            time.sleep(max(0, espera))


def extraer_resenas(df_juegos, *, idiomas=('all',), tipo_compra=1,
                   descargar_comentarios=False, paginas_por_juego=1,
                   resenas_por_pagina=100, excluir_offtopic=True,
                   pausa=1.5, carpeta='resenas_steam', actualizar=False):
    """Consulta los appid únicos de un DataFrame y devuelve dos tablas.

    resultado['resumen']: total, positivas, negativas, porcentaje y valoración.
    resultado['comentarios']: texto y campos públicos de cada reseña descargada.

    tipo_compra: 0 = comprados en Steam; 1 = todas las procedencias; 2 = otras.
    idiomas=('all',) incluye todos. ('spanish',) limita al español de España;
    para incluir español latinoamericano añadir 'latam'.
    descargar_comentarios=False solo obtiene estadísticas (una petición/juego).
    True descarga hasta paginas_por_juego páginas por juego. None recorre todas.
    Los totales cuentan la consulta completa, no solo los textos descargados.
    El porcentaje positivo es positivas / total * 100; vacío cuando total=0.
    review_score_desc es una categoría global, no un tipo de voto individual.
    Se respetan filtros de idioma, procedencia y actividad fuera de tema.

    Guarda resumen_resenas.csv, comentarios_resenas.csv y respuestas JSON.
    Repetir con la misma carpeta reutiliza consultas, permitiendo reanudar.
    actualizar=True vuelve a consultar; la API puede cachear unos 10 minutos.
    Errores no se convierten en ceros. 401/403/429 detienen el recorrido para
    evitar consultas fallidas en masa; juegos restantes quedan pendientes.
    Consultas exitosas con cero reseñas tienen estado='ok' y total=0.
    """
    if 'appid' not in df_juegos:
        raise ValueError('Falta la columna appid.')
    ids = pd.to_numeric(df_juegos['appid'], errors='raise')
    if ids.isna().any() or (ids <= 0).any() or (ids % 1 != 0).any():
        raise ValueError('Los appid deben ser enteros positivos.')
    if tipo_compra not in (0, 1, 2) or pausa < 0:
        raise ValueError('Revisa tipo_compra y pausa.')
    if not isinstance(resenas_por_pagina, int) or not 1 <= resenas_por_pagina <= 100:
        raise ValueError('resenas_por_pagina debe estar entre 1 y 100.')
    if paginas_por_juego is not None and (not isinstance(paginas_por_juego, int) or paginas_por_juego < 1):
        raise ValueError('paginas_por_juego debe ser positivo o None.')
    if isinstance(idiomas, str):
        idiomas = (idiomas,)
    if not idiomas:
        raise ValueError('Indica al menos un idioma o all.')
    ids = ids.astype('int64').drop_duplicates().tolist()
    raiz = Path(carpeta)
    cache = raiz / 'respuestas'
    cache.mkdir(parents=True, exist_ok=True)
    columnas = ['appid', 'resenas_total', 'resenas_positivas', 'resenas_negativas',
                'porcentaje_positivas', 'valoracion', 'tiene_resenas', 'estado',
                'error', 'consultado_utc', 'idiomas', 'tipo_compra', 'excluir_offtopic',
                'comentarios_descargados', 'comentarios_estado']
    resumen = {a: dict(appid=a, resenas_total=None, resenas_positivas=None,
        resenas_negativas=None, porcentaje_positivas=None, valoracion=None,
        tiene_resenas=None, estado='pendiente', error=None, consultado_utc=None,
        idiomas=','.join(idiomas), tipo_compra=tipo_compra, excluir_offtopic=excluir_offtopic,
        comentarios_descargados=0, comentarios_estado='pendiente' if descargar_comentarios else 'no_solicitados') for a in ids}
    comentarios = {}
    consecutivos = 0
    try:
        for numero, appid in enumerate(ids, 1):
            fila = resumen[appid]
            cursor, paginas, cursores = '*', 0, set()
            try:
                while True:
                    parametros = dict(appid=appid, languages=list(idiomas), review_type=0,
                        purchase_type=tipo_compra, filter=1, cursor=cursor,
                        num_per_page=resenas_por_pagina if descargar_comentarios else 1,
                        filter_offtopic_activity=excluir_offtopic, display_language='spanish')
                    data, marca = _consultar(parametros, cache, pausa, actualizar)
                    if paginas == 0:
                        q = data['query_summary']
                        total, positivas, negativas = (int(q[k]) for k in ('total_reviews', 'total_positive', 'total_negative'))
                        if min(total, positivas, negativas) < 0 or positivas + negativas != total:
                            raise ValueError('Totales de reseñas inconsistentes.')
                        fila.update(resenas_total=total, resenas_positivas=positivas,
                            resenas_negativas=negativas, porcentaje_positivas=round(100*positivas/total, 2) if total else None,
                            valoracion=q.get('review_score_desc'), tiene_resenas=total > 0,
                            estado='ok', consultado_utc=marca)
                    paginas += 1
                    if not descargar_comentarios:
                        break
                    lote = data['reviews']
                    for review in lote:
                        clave = (appid, str(review['recommendationid']))
                        if clave not in comentarios:
                            comentarios[clave] = dict(review, appid=appid, pagina_consulta=paginas, consultado_utc=marca)
                            fila['comentarios_descargados'] += 1
                    if not lote:
                        fila['comentarios_estado'] = 'completo'
                        break
                    if paginas_por_juego is not None and paginas >= paginas_por_juego:
                        fila['comentarios_estado'] = 'limite_de_paginas'
                        break
                    siguiente = data.get('cursor')
                    if not siguiente or siguiente == cursor or siguiente in cursores:
                        raise ValueError('Cursor ausente o repetido; comentarios parciales.')
                    cursores.add(cursor)
                    cursor = siguiente
                consecutivos = 0
            except (HTTPError, URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
                consecutivos += 1
                fila['error'] = str(exc)
                if fila['estado'] != 'ok':
                    fila['estado'] = 'error'
                if descargar_comentarios:
                    fila['comentarios_estado'] = 'error_parcial'
                if (isinstance(exc, HTTPError) and exc.code in (401, 403, 429)) or consecutivos >= 5:
                    print('Consulta detenida:', exc)
                    break
            print(f'Reseñas {numero}/{len(ids)}: appid={appid}, estado={fila["estado"]}, total={fila["resenas_total"]}')
    except KeyboardInterrupt:
        print('Interrumpido. Se conservan las respuestas y los resultados parciales.')
    df_resumen = pd.DataFrame(resumen.values(), columns=columnas)
    for columna in ('resenas_total', 'resenas_positivas', 'resenas_negativas'):
        df_resumen[columna] = pd.to_numeric(df_resumen[columna], errors='coerce').astype('Int64')
    df_resumen['tiene_resenas'] = df_resumen['tiene_resenas'].astype('boolean')
    df_comentarios = pd.json_normalize(list(comentarios.values()), sep='.') if comentarios else pd.DataFrame(columns=['appid','recommendationid','review','voted_up','language'])
    df_resumen.to_csv(raiz / 'resumen_resenas.csv', index=False, encoding='utf-8-sig')
    df_comentarios.to_csv(raiz / 'comentarios_resenas.csv', index=False, encoding='utf-8-sig')
    return {'resumen': df_resumen, 'comentarios': df_comentarios}
