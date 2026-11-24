"""Exportaciones CSV.GZ compatibles con las columnas de referencia."""
import json
from datetime import date
from pathlib import Path
import pandas as pd
from steam_pipeline.descargas.steam_proximos_paginados import interpretar

FICHAS = ['', 'appid', 'region', 'idioma', 'estado_consulta', 'error_consulta', 'consultado_utc', 'steam.type', 'steam.name', 'steam.steam_appid', 'steam.required_age', 'steam.is_free', 'steam.detailed_description', 'steam.about_the_game', 'steam.short_description', 'steam.supported_languages', 'steam.reviews', 'steam.header_image', 'steam.capsule_image', 'steam.capsule_imagev5', 'steam.website', 'steam.pc_requirements.minimum', 'steam.pc_requirements.recommended', 'steam.mac_requirements.minimum', 'steam.mac_requirements.recommended', 'steam.linux_requirements.minimum', 'steam.linux_requirements.recommended', 'steam.developers', 'steam.publishers', 'steam.package_groups', 'steam.platforms.windows', 'steam.platforms.mac', 'steam.platforms.linux', 'steam.categories', 'steam.genres', 'steam.release_date.coming_soon', 'steam.release_date.date', 'steam.support_info.url', 'steam.support_info.email', 'steam.background', 'steam.background_raw', 'steam.content_descriptors.ids', 'steam.content_descriptors.notes', 'steam.ratings.dejus.rating', 'steam.ratings.steam_germany.rating_generated', 'steam.ratings.steam_germany.rating', 'steam.ratings.steam_germany.required_age', 'steam.ratings.steam_germany.banned', 'steam.ratings.steam_germany.use_age_gate', 'steam.ratings.steam_germany.descriptors', 'steam.ratings.igrs.rating_generated', 'steam.ratings.igrs.rating', 'steam.ratings.igrs.required_age', 'steam.ratings.igrs.banned', 'steam.ratings.igrs.use_age_gate', 'steam.ratings.igrs.descriptors', 'steam.screenshots', 'steam.movies', 'steam.ratings.dejus.rating_generated', 'steam.ratings.dejus.required_age', 'steam.ratings.dejus.banned', 'steam.ratings.dejus.use_age_gate', 'steam.ratings.dejus.descriptors', 'steam.mac_requirements', 'steam.linux_requirements', 'steam.controller_support', 'steam.ratings', 'steam.legal_notice', 'steam.demos', 'steam.dlc', 'steam.ext_user_account_notice', 'steam.ratings.crl.rating', 'lanzamiento_texto', 'fecha_lanzamiento', 'estado_lanzamiento', 'coincide_filtro']

CATALOGO = ['', 'appid', 'nombre_buscador', 'lanzamiento_buscador', 'url_tienda', 'region', 'idioma', 'filtro_buscador', 'buscador_consultado_utc', 'fecha_buscador']

VERIFICACION = ['', 'appid', 'nombre_buscador', 'lanzamiento_buscador', 'url_tienda', 'region', 'idioma', 'filtro_buscador', 'buscador_consultado_utc', 'fecha_buscador', 'estado_consulta', 'error_consulta', 'consultado_utc', 'steam.type', 'steam.name', 'steam.steam_appid', 'steam.required_age', 'steam.is_free', 'steam.detailed_description', 'steam.about_the_game', 'steam.short_description', 'steam.supported_languages', 'steam.header_image', 'steam.capsule_image', 'steam.capsule_imagev5', 'steam.website', 'steam.pc_requirements.minimum', 'steam.mac_requirements', 'steam.linux_requirements', 'steam.developers', 'steam.publishers', 'steam.package_groups', 'steam.platforms.windows', 'steam.platforms.mac', 'steam.platforms.linux', 'steam.categories', 'steam.genres', 'steam.screenshots', 'steam.movies', 'steam.release_date.coming_soon', 'steam.release_date.date', 'steam.support_info.url', 'steam.support_info.email', 'steam.background', 'steam.background_raw', 'steam.content_descriptors.ids', 'steam.content_descriptors.notes', 'steam.ratings.dejus.rating_generated', 'steam.ratings.dejus.rating', 'steam.ratings.dejus.required_age', 'steam.ratings.dejus.banned', 'steam.ratings.dejus.use_age_gate', 'steam.ratings.dejus.descriptors', 'steam.ratings.steam_germany.rating_generated', 'steam.ratings.steam_germany.rating', 'steam.ratings.steam_germany.required_age', 'steam.ratings.steam_germany.banned', 'steam.ratings.steam_germany.use_age_gate', 'steam.ratings.steam_germany.descriptors', 'steam.pc_requirements.recommended', 'steam.mac_requirements.minimum', 'steam.mac_requirements.recommended', 'steam.linux_requirements.minimum', 'steam.linux_requirements.recommended', 'steam.price_overview.currency', 'steam.price_overview.initial', 'steam.price_overview.final', 'steam.price_overview.discount_percent', 'steam.price_overview.initial_formatted', 'steam.price_overview.final_formatted', 'steam.packages', 'steam.achievements.total', 'steam.achievements.highlighted', 'steam.ratings.igrs.rating_generated', 'steam.ratings.igrs.rating', 'steam.ratings.igrs.required_age', 'steam.ratings.igrs.banned', 'steam.ratings.igrs.use_age_gate', 'steam.ratings.igrs.descriptors', 'steam.dlc', 'steam.reviews', 'steam.controller_support', 'lanzamiento_texto', 'fecha_lanzamiento', 'estado_lanzamiento', 'coincide_filtro']

def fecha_exacta(texto):
    if pd.isna(texto):
        return pd.NaT
    detalle, _ = interpretar(str(texto), date(1900, 1, 1), date(9999, 12, 31))
    if detalle['precision_fecha'] != 'dia':
        return pd.NaT
    # Excel/pandas no representan fechas ficticias como 31 DIC 9998.
    return pd.to_datetime(
        f"{detalle['anio']:04d}-{detalle['mes_inicio']:02d}-{detalle['dia']:02d}",
        errors='coerce',
    )


def serie(tabla, nombre):
    return tabla.get(nombre, pd.Series(index=tabla.index, dtype='object'))


def ordenar(tabla, columnas):
    tabla = tabla.reset_index(drop=True).copy()
    tabla[''] = range(len(tabla))  # Índice con encabezado vacío como en las referencias.
    return tabla.reindex(columns=columnas)


def construir_formatos(listado, fichas, proximos):
    """No aplica filtros editoriales: mantiene los datos para verificación."""
    for tabla in (listado, fichas):
        if tabla.appid.isna().any() or not tabla.appid.is_unique:
            raise ValueError('La exportación requiere un appid único por fila.')
    if not set(fichas.appid).issubset(set(listado.appid)):
        raise ValueError('Hay fichas sin entrada de catálogo.')
    catalogo = listado.rename(columns={
        'nombre': 'nombre_buscador', 'lanzamiento_texto': 'lanzamiento_buscador',
        'consultado_utc': 'buscador_consultado_utc',
    }).copy()
    # El descargador recibido consulta el buscador con l=spanish.
    catalogo['idioma'] = 'spanish'
    catalogo['region'] = serie(listado, 'region').fillna(proximos.get('pais'))
    catalogo['filtro_buscador'] = 'comingsoon'
    catalogo['fecha_buscador'] = serie(catalogo, 'lanzamiento_buscador').map(fecha_exacta)
    catalogo = ordenar(catalogo, CATALOGO)

    detalle = fichas.rename(columns={
        'ficha_region': 'region', 'ficha_idioma': 'idioma',
        'ficha_estado': 'estado_consulta', 'ficha_error': 'error_consulta',
        'ficha_consultado_utc': 'consultado_utc',
        'lanzamiento_ficha_texto': 'lanzamiento_texto',
    }).copy()
    texto = serie(detalle, 'lanzamiento_texto').combine_first(serie(detalle, 'steam.release_date.date'))
    detalle['lanzamiento_texto'] = texto
    detalle['fecha_lanzamiento'] = texto.map(fecha_exacta)
    proximo = serie(detalle, 'proximo_lanzamiento').combine_first(serie(detalle, 'steam.release_date.coming_soon'))
    correcto = serie(detalle, 'estado_consulta').eq('ok')
    detalle['estado_lanzamiento'] = pd.Series(pd.NA, index=detalle.index, dtype='object')
    detalle.loc[correcto & proximo.eq(True), 'estado_lanzamiento'] = 'Próximo lanzamiento'
    detalle.loc[correcto & proximo.eq(False), 'estado_lanzamiento'] = 'Ya estrenado'
    # Coincidencia con el intervalo de fechas solicitado, NO con la recepción GECA.
    desde = pd.to_datetime(proximos.get('desde'), errors='coerce')
    hasta = pd.to_datetime(proximos.get('hasta'), errors='coerce')
    detalle['coincide_filtro'] = pd.Series(pd.NA, index=detalle.index, dtype='boolean')
    if pd.notna(desde) and pd.notna(hasta):
        conocidos = correcto & detalle.fecha_lanzamiento.notna()
        detalle.loc[conocidos, 'coincide_filtro'] = detalle.loc[conocidos, 'fecha_lanzamiento'].between(desde, hasta)
    # Verificación conserva región/idioma del buscador; fichas conserva los de appdetails.
    union = catalogo.drop(columns=['']).merge(
        detalle.drop(columns=['region', 'idioma'], errors='ignore'),
        on='appid', how='left', validate='one_to_one',
    )
    return {'catalogo_new': catalogo, 'fichas_new': ordenar(detalle, FICHAS),
            'verificacion': ordenar(union, VERIFICACION)}


def exportar_formatos(listado, fichas, proximos, salida):
    """Exporta los tres formatos a CSV.GZ sin alterar los datos originales.

    Conserva la firma y las claves de retorno utilizadas por radar_diario.
    Se escriben archivos temporales y solo se publican tras completarse.
    """
    import csv
    import os
    import tempfile

    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    tablas = construir_formatos(listado, fichas, proximos)
    archivos = {}

    for nombre, tabla in tablas.items():
        tabla = tabla.copy()
        for columna in tabla:
            tabla[columna] = tabla[columna].map(
                lambda x: repr(x) if isinstance(x, (list, dict)) else x
            )
        ruta = salida / f"{nombre}.csv.gz"
        # Temporal en la misma carpeta para que os.replace sea atómico.
        fd, temporal = tempfile.mkstemp(
            prefix=f".{nombre}.", suffix=".csv.gz", dir=salida
        )
        os.close(fd)
        try:
            tabla.to_csv(
                temporal,
                index=False,
                encoding="utf-8",
                compression="gzip",
                quoting=csv.QUOTE_MINIMAL,
            )
            os.replace(temporal, ruta)
        finally:
            if os.path.exists(temporal):
                os.unlink(temporal)
        archivos[nombre] = str(ruta)

    return archivos
