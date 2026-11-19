# GECA: validación de rango corregida (18-11-2026).
"""Descubrimiento Steam con paginación completa y fechas públicas preservadas.

No supone orden cronológico público: un retroceso se registra, no detiene.
No corta al encontrar fechas posteriores al intervalo. Conserva fechas
aproximadas en sin_fecha; el radar las incluye y verifica appdetails.
completo indica fin del recorrido observado, no una captura transaccional de
Steam. Los errores y max_paginas producen una captura explícitamente parcial.
"""
import hashlib
import json
import re
import time
import unicodedata
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import pandas as pd
from steam_pipeline.ventana import resolver_ventana

__all__ = ['descargar_proximos_steam']

class _Resultados(HTMLParser):
    """Extrae las filas y campos del HTML del buscador sin dependencias extra."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.filas = []
        self.actual = None
        self.campos = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        clases = attrs.get('class', '').split()
        if tag == 'a' and 'search_result_row' in clases:
            self.actual = {'href': attrs.get('href', ''), 'nombre': '', 'lanzamiento': ''}
            self.campos = []
        if self.actual is not None:
            if 'title' in clases:
                self.campos.append((tag, 'nombre'))
            elif 'search_released' in clases:
                self.campos.append((tag, 'lanzamiento'))

    def handle_data(self, data):
        if self.actual is not None and self.campos:
            self.actual[self.campos[-1][1]] += data

    def handle_endtag(self, tag):
        if self.campos and self.campos[-1][0] == tag:
            self.campos.pop()
        if tag == 'a' and self.actual is not None:
            self.filas.append(self.actual)
            self.actual = None
            self.campos = []

def interpretar(texto, desde, hasta):
    """Clasifica fechas exactas y parciales preservando su grado de precisión.

    Un año o mes potencialmente coincidente se mantiene pendiente, jamás se
    convierte en una fecha inventada. Otros textos sin fecha quedan pendientes.
    """
    t = ''.join(c for c in unicodedata.normalize('NFKD', str(texto).lower())
                if not unicodedata.combining(c)).strip()
    months = {'ene':1, 'jan':1, 'feb':2, 'mar':3, 'abr':4, 'apr':4,
              'may':5, 'jun':6, 'jul':7, 'ago':8, 'aug':8, 'sep':9,
              'oct':10, 'nov':11, 'dic':12, 'dec':12}
    detalle = dict(anio='', mes_inicio='', mes_fin='', dia='',
                   precision_fecha='sin_fecha')
    m = re.fullmatch(r'(\d{1,2})\s+(?:de\s+)?([a-z]+)\.?[,]?\s+(?:de\s+)?(\d{4})', t)
    n = re.fullmatch(r'([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})', t)
    iso = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', t)
    try:
        if iso:
            fecha = date.fromisoformat(t)
        elif m or n:
            day, word, year = (m[1], m[2], m[3]) if m else (n[2], n[1], n[3])
            fecha = date(int(year), months[word[:3]], int(day))
        else:
            fecha = None
        if fecha is not None:
            detalle.update(anio=fecha.year, mes_inicio=fecha.month,
                           mes_fin=fecha.month, dia=fecha.day, precision_fecha='dia')
            return detalle, 'dentro' if desde <= fecha <= hasta else 'fuera'

        # Solo año: «2027».
        solo_anio = re.fullmatch(r'(20\d{2})', t)
        if solo_anio:
            anio = int(solo_anio.group(1))
            detalle.update(anio=anio, mes_inicio=1, mes_fin=12, precision_fecha='anio')
            solapa = date(anio, 1, 1) <= hasta and date(anio, 12, 31) >= desde
            return detalle, 'sin_fecha' if solapa else 'fuera'

        # Mes y año, sin día: «marzo de 2027», «Mar 2027», «2027-03».
        m_ym = re.fullmatch(r'(20\d{2})-(\d{1,2})',t)
        m_my = re.fullmatch(r'([a-z]+)\.?\s+(?:de\s+)?(20\d{2})', t)
        if m_ym or m_my:
            anio = int(m_ym.group(1) if m_ym else m_my.group(2))
            mes = int(m_ym.group(2)) if m_ym else months.get(m_my.group(1)[:3])
            if mes is None or not (1 <= mes <= 12):
                return {**detalle, 'precision_fecha': 'no_reconocida'}, 'sin_fecha'
            import calendar
            ultimo = date(anio, mes, calendar.monthrange(anio, mes)[1])
            detalle.update(anio=anio, mes_inicio=mes, mes_fin=mes, precision_fecha='mes')
            solapa = date(anio, mes, 1) <= hasta and ultimo >= desde
            return detalle, 'sin_fecha' if solapa else 'fuera'
        detalle['precision_fecha'] = 'no_reconocida'
        return detalle, 'sin_fecha'
    except (KeyError, ValueError):
        detalle['precision_fecha'] = 'fecha_invalida'
        return detalle, 'sin_fecha'


def _guardar_json(ruta, datos):
    temporal = ruta.with_suffix('.tmp')
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')
    temporal.replace(ruta)


def _obtener_json(url, pausa):
    for intento in range(5):
        try:
            time.sleep(pausa)
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40) as r:
                return json.load(r)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            if intento == 4:
                raise
            espera = 2 ** (intento + 1)
            if isinstance(error, HTTPError):
                if error.code not in (429, 500, 502, 503, 504):
                    raise
                retry = error.headers.get('Retry-After', '')
                if retry.isdigit():
                    espera = max(espera, int(retry))
                elif retry:
                    try:
                        espera = max(espera, (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
                    except (TypeError, ValueError):
                        pass
            time.sleep(max(0, espera))


def descargar_proximos_steam(*, desde=None, hasta=None, anio_hasta=2031, pais='es',
                            plataforma='win', filtro='comingsoon',
                            carpeta='descarga_steam', tamano_pagina=100, ventana_meses=6,
                            pausa=1.5, max_paginas=None, actualizar=False,
                            guardar_csv=True):
    """Descarga el intervalo inclusivo indicado.

    desde/hasta: AAAA-MM-DD; ambos nulos activan ventana móvil local de seis meses.
    pais: región; plataforma: win o None; filtro: comingsoon para descubrir próximos estrenos.
    carpeta: caché y exportaciones; tamano_pagina: 1..100; pausa: segundos.
    max_paginas: None sin límite adicional; actualizar: refresca caché de consulta.
    guardar_csv: False si el catálogo de Kedro guarda las salidas.
    popularcomingsoon sigue aceptado por compatibilidad, pero se cambia con aviso
    a comingsoon para evitar un filtro de popularidad.
    """
    if filtro not in ('popularcomingsoon', 'comingsoon'):
        raise ValueError('filtro debe ser popularcomingsoon o comingsoon.')
    if filtro == 'popularcomingsoon':
        print("Modo por fechas: se cambia popularcomingsoon por comingsoon.")
        filtro = 'comingsoon'
    if not isinstance(tamano_pagina, int) or isinstance(tamano_pagina, bool) or not 1 <= tamano_pagina <= 100:
        raise ValueError('tamano_pagina debe estar entre 1 y 100.')
    if max_paginas is not None and (isinstance(max_paginas, bool) or not isinstance(max_paginas, int) or max_paginas < 1):
        raise ValueError('max_paginas debe ser positivo o None.')
    if pausa < 0:
        raise ValueError('pausa no puede ser negativa.')
    try:
        referencia, hasta = resolver_ventana(desde, hasta, ventana_meses)
    except (TypeError, ValueError) as exc:
        # Preservar el mensaje de rango inválido generado por resolver_ventana.
        # Así se distingue de una fecha mal escrita y se mantiene el contrato
        # comprobado por tests/test_pipeline.py::test_fecha_invalida.
        if isinstance(exc, ValueError) and 'posterior' in str(exc):
            raise
        raise ValueError('Usa fechas válidas AAAA-MM-DD.') from exc
    raiz = Path(carpeta)
    raiz.mkdir(parents=True, exist_ok=True)
    cache = raiz / 'paginas_json'
    cache.mkdir(exist_ok=True)
    base = dict(filter=filtro, sort_by='Released_ASC', category1='998', infinite=1, json=1,
                l='spanish', cc=pais, count=tamano_pagina)
    if plataforma:
        base['os'] = plataforma
    firma = hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()[:16]
    if actualizar:
        for archivo in cache.glob(f'{firma}_*.json'):
            archivo.unlink()
    seleccionados, desconocidos, vistos, paginas = {}, {}, set(), []
    inicio, numero, repetidas = 0, 0, 0
    completo, error, total_inicial, total_final = False, None, None, None
    excluidos = {'fuera': 0}
    ultima_fecha = None
    motivo_parada = 'max_paginas' if max_paginas is not None else 'pendiente'
    orden_observado = True
    try:
        while max_paginas is None or numero < max_paginas:
            url = 'https://store.steampowered.com/search/results/?' + urlencode(dict(base, start=inicio))
            ruta = cache / f'{firma}_{inicio}.json'
            guardado = ruta.exists()
            paquete = json.loads(ruta.read_text(encoding='utf-8')) if guardado else None
            if paquete and paquete.get('url') != url:
                raise ValueError('La caché no coincide con la consulta solicitada.')
            datos = paquete['respuesta'] if guardado else _obtener_json(url, pausa)
            parser = _Resultados()
            parser.feed(datos['results_html'])
            filas = parser.filas
            origen = int(datos.get('start', inicio))
            total_final = int(datos['total_count'])
            if total_inicial is None:
                total_inicial = total_final
            if origen != inicio:
                raise ValueError(f'Steam devolvió start={origen} al pedir {inicio}; descarga detenida para evitar saltos.')
            if not filas and inicio < total_final:
                raise ValueError('Página vacía antes del total anunciado; vuelve a ejecutar para reintentar.')
            if not guardado:
                paquete = {'url': url, 'consultado_utc': datetime.now(timezone.utc).isoformat(), 'respuesta': datos}
                _guardar_json(ruta, paquete)
            numero += 1
            marca = paquete['consultado_utc']
            paginas.append(dict(pagina_consulta=numero, inicio_solicitado=inicio,
                                inicio_respuesta=origen, filas_recibidas=len(filas),
                                total_anunciado=total_final, url_consulta=url,
                                archivo_pagina=str(ruta), consultado_utc=marca, desde_cache=guardado))
            anteriores = len(vistos)
            # Registra el orden público como diagnóstico, sin condicionar avance.
            for fila_fecha in filas:
                d, _ = interpretar(fila_fecha['lanzamiento'].strip(), referencia, hasta)
                if d['precision_fecha'] == 'dia':
                    f = date(d['anio'], d['mes_inicio'], d['dia'])
                    if ultima_fecha is not None and f < ultima_fecha:
                        orden_observado = False
                    ultima_fecha = f
            for offset, fila in enumerate(filas, 1):
                match = re.search(r'/app/(\d+)', fila['href'])
                if not match:
                    continue
                appid = int(match.group(1))
                if appid in vistos:
                    continue
                vistos.add(appid)
                texto = fila['lanzamiento'].strip()
                detalle, grupo = interpretar(texto, referencia, hasta)
                if grupo not in ('dentro', 'sin_fecha'):
                    excluidos[grupo] = excluidos.get(grupo, 0) + 1
                    continue
                registro = dict(appid=appid, nombre=fila['nombre'].strip(), lanzamiento_texto=texto,
                                url_tienda=f'https://store.steampowered.com/app/{appid}/',
                                fuente=filtro, region=pais, plataforma_filtro=plataforma,
                                pagina_consulta=numero, fila_en_pagina=offset,
                                posicion_global=origen + offset, inicio_solicitado=inicio,
                                inicio_respuesta=origen, url_consulta=url,
                                archivo_pagina=str(ruta), consultado_utc=marca, **detalle)
                (seleccionados if grupo == 'dentro' else desconocidos)[appid] = registro
            inicio = origen + len(filas)
            print(f'Página {numero}: {inicio} filas revisadas; {len(seleccionados)} juegos con día exacto entre {referencia} y {hasta}; {len(desconocidos)} sin día exacto.')
            if inicio >= total_final:
                completo = True
                motivo_parada = 'fin_listado'
                break
            repetidas = repetidas + 1 if len(vistos) == anteriores else 0
            if repetidas >= 3:
                raise ValueError('Tres páginas sin appid nuevos. Steam puede estar repitiendo resultados.')
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError, KeyboardInterrupt) as exc:
        motivo_parada = 'error'
        error = str(exc) or 'Interrumpido por el usuario'
        print('Descarga parcial:', error)
    columnas = ['appid','nombre','lanzamiento_texto','url_tienda','fuente','region','plataforma_filtro',
                'pagina_consulta','fila_en_pagina','posicion_global','inicio_solicitado','inicio_respuesta',
                'url_consulta','archivo_pagina','consultado_utc','anio','mes_inicio','mes_fin','dia','precision_fecha']
    df = pd.DataFrame(seleccionados.values(), columns=columnas)
    sin_fecha = pd.DataFrame(desconocidos.values(), columns=columnas)
    for tabla in (df, sin_fecha):
        for columna in ('anio','mes_inicio','mes_fin','dia'):
            tabla[columna] = pd.to_numeric(tabla[columna], errors='coerce').astype('Int64')
    df = df.sort_values(['anio','mes_inicio','dia','appid'], na_position='last', kind='stable').reset_index(drop=True)
    registro_paginas = pd.DataFrame(paginas)
    resumen = dict(completo=completo, motivo_parada=motivo_parada,
                   orden_observado=orden_observado, corte_por_fecha=motivo_parada == "corte_fecha",
                   error=error, desde=str(referencia), hasta=str(hasta),
                   paginas_procesadas=numero, siguiente_inicio=inicio,
                   total_anunciado_inicial=total_inicial, total_anunciado_final=total_final,
                   appids_unicos_examinados=len(vistos), juegos_en_periodo=len(df),
                   juegos_sin_fecha=len(sin_fecha), excluidos=excluidos,
                   filtro=filtro, region=pais, plataforma=plataforma,
                   nota='Fechas exactas en juegos; fechas parciales o desconocidas, pendientes de verificar, en sin_fecha. Sin corte cronológico. completo describe el recorrido observado; el catálogo puede cambiar durante la consulta. No se consultó appdetails.')
    for tabla in (df, sin_fecha, registro_paginas):
        tabla.attrs.update(resumen)
    if guardar_csv:
        df.to_csv(raiz / f'juegos_hasta_{hasta.isoformat()}.csv', index=False, encoding='utf-8-sig')
        sin_fecha.to_csv(raiz / 'juegos_sin_fecha.csv', index=False, encoding='utf-8-sig')
        registro_paginas.to_csv(raiz / 'registro_paginas.csv', index=False, encoding='utf-8-sig')
        _guardar_json(raiz / 'resumen.json', resumen)
    return {'juegos': df, 'sin_fecha': sin_fecha, 'paginas': registro_paginas, 'resumen': resumen}
