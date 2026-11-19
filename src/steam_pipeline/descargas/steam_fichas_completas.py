"""Fichas completas de Steam Store appdetails, una fila por appid.

Dependencias: pandas (y openpyxl si el usuario lee un Excel con pandas).
No requiere otros módulos de este proyecto ni API key.
La función descarga todos los campos que entregue la ficha, sin lista restrictiva.
Las fichas no disponibles conservan su appid y un estado explícito.
"""
import json
import time
from datetime import datetime, timezone
from steam_pipeline.frescura import leer_cache_vigente
from steam_pipeline.descargas import checkpoint_fichas
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import pandas as pd

__all__ = ['descargar_fichas_completas']
ENDPOINT = 'https://store.steampowered.com/api/appdetails'


class _Texto(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []

    def handle_data(self, data):
        self.partes.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'p', 'div', 'li', 'h1', 'h2', 'h3'):
            self.partes.append('\n')

    def handle_endtag(self, tag):
        if tag in ('p', 'div', 'li', 'h1', 'h2', 'h3'):
            self.partes.append('\n')


def _texto(html):
    if not isinstance(html, str):
        return None
    parser = _Texto()
    parser.feed(html)
    return '\n'.join(linea.strip() for linea in ''.join(parser.partes).splitlines() if linea.strip())


def _consulta(url, pausa):
    for intento in range(4):
        try:
            time.sleep(pausa)
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=35) as r:
                return json.load(r)
        except (HTTPError, URLError, TimeoutError) as exc:
            if intento == 3:
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


def _atomico(ruta, contenido):
    temporal = ruta.with_suffix(ruta.suffix + '.tmp')
    temporal.write_text(json.dumps(contenido, ensure_ascii=False), encoding='utf-8')
    temporal.replace(ruta)


def _firma_listado(registro):
    """Campos observables del listado que obligan a refrescar una ficha.

    No se inventan fechas: se compara exactamente el texto que publicó Steam.
    Una firma ausente en cachés anteriores se admite hasta vencer la antigüedad.
    """
    if registro is None:
        return None
    claves = ("nombre", "lanzamiento_texto")
    valores = {}
    for clave in claves:
        v = registro.get(clave) if hasattr(registro, "get") else None
        if v is not None and not pd.isna(v):
            valores[clave] = " ".join(str(v).split()).casefold()
    return valores or None


def _lista_nombres(valor, campo):
    if not isinstance(valor, list):
        return None
    return ' | '.join(str(x[campo]) for x in valor if isinstance(x, dict) and campo in x)


def _derivadas(datos):
    precio = datos.get('price_overview') or {}
    fecha = datos.get('release_date') or {}
    return dict(
        nombre_ficha=datos.get('name'),
        descripcion_corta_texto=_texto(datos.get('short_description')),
        descripcion_completa_texto=_texto(datos.get('detailed_description')),
        sobre_el_juego_texto=_texto(datos.get('about_the_game')),
        idiomas_texto=_texto(datos.get('supported_languages')),
        desarrolladores_texto=' | '.join(datos['developers']) if isinstance(datos.get('developers'), list) else None,
        editores_texto=' | '.join(datos['publishers']) if isinstance(datos.get('publishers'), list) else None,
        generos_texto=_lista_nombres(datos.get('genres'), 'description'),
        categorias_texto=_lista_nombres(datos.get('categories'), 'description'),
        lanzamiento_ficha_texto=fecha.get('date'),
        proximo_lanzamiento=fecha.get('coming_soon'),
        gratis=datos.get('is_free'),
        precio_inicial=precio['initial'] / 100 if isinstance(precio.get('initial'), (int, float)) else None,
        precio_final=precio['final'] / 100 if isinstance(precio.get('final'), (int, float)) else None,
        moneda=precio.get('currency'),
        descuento_porcentaje=precio.get('discount_percent'),
        tiene_descuento=precio['discount_percent'] > 0 if isinstance(precio.get('discount_percent'), (int, float)) else None,
    )


def descargar_fichas_completas(df_juegos, *, pais='es', idioma='spanish',
                               carpeta='fichas_steam', pausa=1.5,
                               actualizar=False, limite=None, max_edad_dias=7):
    """Descarga todos los campos de appdetails para appids únicos del DataFrame.

    Retorna un DataFrame independiente, listo para merge por appid.
    No aplica filtros de fechas ni de estado: examina los IDs proporcionados.
    limite=None consulta todos; limite=5 sirve para probar.

    Columnas originales de la API: steam.*. Conserva diccionarios anidados como
    columnas y listas completas en celdas. Las columnas sin prefijo son metadatos
    y derivados legibles; no sustituyen los datos originales.
    Campos no proporcionados quedan vacíos, no se convierten a cero o False.
    Número de columnas variable: depende de los campos que Steam publique.

    Precio: valores inicial/final del endpoint divididos entre 100; conservar
    también steam.price_overview.* y la moneda para comparar importes.
    pais es la región de la tienda, no el país de origen del desarrollador.
    No se extraen reseñas completas, jugadores conectados o wishlists aquí.

    Guarda fichas_completas.csv, campos_disponibles.csv, resumen.json y una
    respuesta JSON por juego/región/idioma, con URL y fecha de consulta.
    Con actualizar=False reutiliza respuestas correctas hasta max_edad_dias;
    actualizar=True solicita nuevamente la ficha. Para conservar capturas
    históricas, usar una carpeta nueva. Los errores no se guardan como éxitos.
    Interrumpir con el botón de Jupyter conserva lo obtenido. Revisar estado:
    ok / no_disponible / error / pendiente. No_disponible no significa eliminado.
    """
    if isinstance(max_edad_dias, bool) or not isinstance(max_edad_dias, (int, float)) or not 0 <= max_edad_dias < float('inf'):
        raise ValueError('max_edad_dias debe ser un número finito no negativo.')
    if 'appid' not in df_juegos:
        raise ValueError('El DataFrame debe contener appid.')
    ids = pd.to_numeric(df_juegos['appid'], errors='raise')
    if ids.isna().any() or (ids <= 0).any() or (ids % 1 != 0).any():
        raise ValueError('Hay appid vacíos o inválidos.')
    if pausa < 0 or not isinstance(pais, str) or not isinstance(idioma, str):
        raise ValueError('Revisa pausa, pais e idioma.')
    if not (pais.isalpha() and len(pais) == 2 and idioma.isalpha()):
        raise ValueError('pais debe ser un código de dos letras e idioma un código de Steam.')
    if limite is not None and (isinstance(limite, bool) or not isinstance(limite, int) or limite < 1):
        raise ValueError('limite debe ser positivo o None.')
    pais = pais.lower()
    idioma = idioma.lower()
    listado_firmas = {}
    for _, registro in df_juegos.iterrows():
        if pd.notna(registro['appid']):
            aid = int(registro['appid'])
            firma = _firma_listado(registro)
            if firma:
                listado_firmas[aid] = firma
    ids = ids.astype('int64').drop_duplicates().tolist()
    if limite is not None:
        ids = ids[:limite]
    raiz = Path(carpeta)
    cache = raiz / 'respuestas' / pais / idioma
    cache.mkdir(parents=True, exist_ok=True)
    # Recuperación de checkpoints publicados durante ejecuciones previas.
    # Si el token está configurado, los errores de GitHub se consideran graves:
    # no seguimos horas de extracción sin persistencia verificable.
    checkpoint_fichas.restore(cache, pais, idioma, max_edad_dias)
    lote = int(__import__('os').getenv('GECA_CHECKPOINT_BATCH', '100'))
    if lote < 1 or lote > 200:
        raise ValueError('GECA_CHECKPOINT_BATCH debe estar entre 1 y 200')
    registros = {a: dict(appid=a, ficha_estado='pendiente', ficha_error=None,
                        ficha_consultado_utc=None, ficha_desde_cache=False,
                        ficha_region=pais, ficha_idioma=idioma, ficha_url_consulta=None,
                        ficha_archivo_json=None) for a in ids}
    consecutivos, motivo = 0, None
    try:
        for numero, appid in enumerate(ids, 1):
            fila = registros[appid]
            ruta = cache / f'{appid}.json'
            url = ENDPOINT + '?' + urlencode(dict(appids=appid, cc=pais, l=idioma))
            fila['ficha_url_consulta'] = url
            try:
                paquete = None if actualizar else leer_cache_vigente(ruta, url, appid, max_edad_dias)
                # Refrescar en cuanto Steam cambie nombre o fecha en su listado.
                # Una ficha del caché antiguo sin firma sigue válida hasta 7 días.
                firma_actual = listado_firmas.get(appid)
                if paquete is not None and firma_actual:
                    firma_guardada = paquete.get('listado_firma')
                    if firma_guardada is not None and firma_guardada != firma_actual:
                        paquete = None
                desde_cache = paquete is not None
                respuesta = paquete['respuesta'] if desde_cache else _consulta(url, pausa)
                item = respuesta.get(str(appid))
                if not isinstance(item, dict) or not isinstance(item.get('success'), bool):
                    raise ValueError('Respuesta sin ficha válida.')
                datos = item.get('data')
                if item['success'] and not isinstance(datos, dict):
                    raise ValueError('Respuesta marcada como correcta pero sin datos.')
                if not desde_cache:
                    paquete = dict(url=url, consultado_utc=datetime.now(timezone.utc).isoformat(), respuesta=respuesta, listado_firma=firma_actual)
                    _atomico(ruta, paquete)
                fila.update(ficha_estado='ok' if item['success'] else 'no_disponible',
                            ficha_consultado_utc=paquete['consultado_utc'],
                            ficha_desde_cache=desde_cache, ficha_archivo_json=str(ruta))
                if item['success']:
                    # Normalización dinámica: no se descarta ningún campo nuevo.
                    fila.update(pd.json_normalize([{'steam': datos}], sep='.').to_dict('records')[0])
                    fila.update(_derivadas(datos))
                consecutivos = 0
            except (HTTPError, URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
                fila.update(ficha_estado='error', ficha_error=str(exc))
                consecutivos += 1
                if (isinstance(exc, HTTPError) and exc.code in (401, 403, 429)) or consecutivos >= 5:
                    motivo = str(exc)
                    print('Descarga detenida:', motivo, flush=True)
                    break
            print(f'Ficha {numero}/{len(ids)}: appid={appid}, {fila["ficha_estado"]}', flush=True)
            if numero % lote == 0:
                checkpoint_fichas.save(cache, ids[numero-lote:numero], pais, idioma, numero // lote)
        # El bloque final también se publica, si no se completó uno exacto.
        if len(ids) % lote and motivo is None:
            final = len(ids) // lote * lote
            checkpoint_fichas.save(cache, ids[final:], pais, idioma, (final // lote) + 1)
    except KeyboardInterrupt:
        motivo = 'Interrumpido por el usuario'
        print(motivo, flush=True)
    df = pd.DataFrame(registros.values()) if registros else pd.DataFrame(columns=[
        'appid','ficha_estado','ficha_error','ficha_consultado_utc','ficha_region','ficha_idioma'])
    # Listas y objetos se serializan como JSON válido al exportar a CSV.
    salida = df.copy()
    for columna in salida.select_dtypes(include='object'):
        salida[columna] = salida[columna].map(
            lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
    salida.to_csv(raiz / 'fichas_completas.csv', index=False, encoding='utf-8-sig')
    campos = pd.DataFrame([dict(campo=c, origen='appdetails' if c.startswith('steam.') else 'metadato_o_derivado',
                                filas_con_valor=int(df[c].notna().sum())) for c in df])
    campos.to_csv(raiz / 'campos_disponibles.csv', index=False, encoding='utf-8-sig')
    estados = {str(k): int(v) for k, v in df['ficha_estado'].value_counts().items()}
    resumen = dict(appids_solicitados=len(ids), columnas=len(df.columns), estados=estados,
                   recorrido_terminado=estados.get('pendiente', 0) == 0,
                   todas_fichas_obtenidas=estados.get('ok', 0) == len(ids),
                   motivo_parada=motivo, pais=pais, idioma=idioma)
    _atomico(raiz / 'resumen.json', resumen)
    df.attrs.update(resumen)
    return df
