"""Radar Steam diario. No implementa Twitch ni sustituye decisiones humanas."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
from steam_pipeline.exportaciones import exportar_formatos, fecha_exacta
from steam_pipeline.descargas.steam_proximos_paginados import descargar_proximos_steam
from steam_pipeline.descargas.steam_fichas_completas import descargar_fichas_completas
from steam_pipeline.descargas.steam_resenas import extraer_resenas
from steam_pipeline.pipelines.steam.nodes import seleccionar_juegos, preparar_csv
from steam_pipeline.ventana import resolver_ventana


def ahora_utc():
    return datetime.now(timezone.utc)


def evaluar_fichas(fichas, corte, max_edad_dias=7):
    """Replica los bloques 6 y 7: fecha válida, estado ok y próximo estreno."""
    corte = pd.Timestamp(corte)
    if corte.tzinfo is None:
        raise ValueError('El corte debe incluir zona horaria.')
    tabla = fichas.copy()
    for columna in ['ficha_consultado_utc', 'ficha_estado', 'proximo_lanzamiento']:
        if columna not in tabla:
            tabla[columna] = pd.Series(index=tabla.index, dtype='object')
    fechas = pd.to_datetime(tabla.ficha_consultado_utc, utc=True, errors='coerce')
    tabla['ficha_vigente_7_dias'] = fechas.between(corte - pd.Timedelta(days=max_edad_dias), corte)
    tabla['verificar_ficha'] = tabla.ficha_estado.ne('ok') | ~tabla.ficha_vigente_7_dias
    tabla['regla_lanzamiento_pdf'] = (
        tabla.proximo_lanzamiento.eq(True) & ~tabla.verificar_ficha
    )
    return tabla


def integrar(listado, fichas, resenas, comentarios, corte, max_edad_dias):
    for tabla in [listado, fichas, resenas]:
        if tabla.appid.isna().any() or not tabla.appid.is_unique:
            raise ValueError('Se requiere una fila por appid en cada tabla principal.')
    if set(listado.appid) != set(fichas.appid):
        raise ValueError('Listado y fichas deben cubrir los mismos juegos.')
    if not set(resenas.appid).issubset(set(listado.appid)):
        raise ValueError('Reseñas fuera del universo de juegos.')
    # Se solicitan reseñas de todos los juegos; conservar errores y datos ausentes.
    base = listado.rename(columns={'consultado_utc': 'listado_consultado_utc'})
    tabla = base.merge(fichas, on='appid', how='left', validate='one_to_one', suffixes=('', '_ficha'))
    opiniones = resenas.rename(columns={'estado': 'resenas_estado', 'consultado_utc': 'resenas_consultado_utc'})
    tabla = tabla.merge(opiniones, on='appid', how='left', validate='one_to_one', suffixes=('', '_resenas'))
    tabla['resenas_solicitadas'] = tabla.appid.isin(resenas.appid)
    tabla['error_resenas'] = tabla.resenas_solicitadas & tabla.resenas_estado.ne('ok')
    if not comentarios.empty:
        if comentarios.recommendationid.isna().any() or not comentarios.recommendationid.is_unique:
            raise ValueError('Comentarios duplicados o sin recommendationid.')
        if not set(comentarios.appid).issubset(set(listado.appid)):
            raise ValueError('Comentarios fuera del universo de juegos.')
        conteos = comentarios.groupby('appid').size()
        tabla['comentarios_en_archivo'] = tabla.appid.map(conteos).fillna(0).astype(int)
    else:
        tabla['comentarios_en_archivo'] = 0
    tabla = evaluar_fichas(tabla, corte, max_edad_dias)
    def serie(nombre):
        return tabla.get(nombre, pd.Series(index=tabla.index, dtype='object'))
    fin = serie('lanzamiento_ficha_texto').map(fecha_exacta)
    dia = pd.Timestamp(corte).tz_convert('America/Caracas').tz_localize(None).normalize()
    tabla['verificar_fecha_pasada'] = serie('proximo_lanzamiento').eq(True) & fin.lt(dia)
    tabla['fecha_textual_distinta'] = (serie('lanzamiento_texto').fillna('').str.strip().str.casefold()
                                      != serie('lanzamiento_ficha_texto').fillna('').str.strip().str.casefold())
    fecha_listado = serie('lanzamiento_texto').map(fecha_exacta)
    exactas = fecha_listado.notna() & fin.notna()
    tabla.loc[exactas, 'fecha_textual_distinta'] = fecha_listado[exactas].ne(fin[exactas])
    return tabla


def registrar_historial(db, ejecucion, corte, tablas, configuracion):
    """Identidad por captura: releer caché no crea una observación nueva."""
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS ejecuciones (
          id TEXT PRIMARY KEY, corte TEXT NOT NULL, configuracion TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observaciones (
          id TEXT PRIMARY KEY, appid INTEGER NOT NULL, fuente TEXT NOT NULL,
          observado_utc TEXT NOT NULL, alcance_json TEXT NOT NULL, evidencia_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ejecucion_observacion (
          ejecucion TEXT NOT NULL, observacion TEXT NOT NULL,
          PRIMARY KEY (ejecucion, observacion));
        ''')
        con.execute('INSERT INTO ejecuciones VALUES (?,?,?)',
                    (ejecucion, str(corte), json.dumps(configuracion, ensure_ascii=False)))
        for fuente, tabla, campo_fecha, alcance in tablas:
            for fila in json.loads(tabla.to_json(orient='records', force_ascii=False)):
                fecha = fila.get(campo_fecha)
                if not fecha:
                    continue  # Fallos sin captura quedan en el snapshot de la ejecución.
                evidencia = {k: v for k, v in fila.items() if k not in ['ficha_desde_cache', 'ficha_archivo_json']}
                cuerpo = json.dumps(evidencia, sort_keys=True, ensure_ascii=False)
                scope = json.dumps(alcance, sort_keys=True, ensure_ascii=False)
                clave = hashlib.sha256(f'{fuente}|{fila["appid"]}|{fecha}|{scope}|{cuerpo}'.encode()).hexdigest()
                con.execute('INSERT OR IGNORE INTO observaciones VALUES (?,?,?,?,?,?)',
                            (clave, int(fila['appid']), fuente, fecha, scope, cuerpo))
                con.execute('INSERT OR IGNORE INTO ejecucion_observacion VALUES (?,?)', (ejecucion, clave))


def evaluar_recepcion(maestro):
    """Recepción informativa por compatibilidad; nunca condiciona la señal PDF."""
    tabla = maestro.copy()
    total = pd.to_numeric(tabla['resenas_total'], errors='coerce')
    porcentaje = pd.to_numeric(tabla['porcentaje_positivas'], errors='coerce')
    tabla['recepcion_favorable'] = (
        tabla['resenas_estado'].eq('ok')
        & total.ge(30)
        & porcentaje.between(80, 100)
    ).fillna(False)
    # Alias conservado para consumidores anteriores. Es elegibilidad técnica,
    # no una recomendación editorial ni una propuesta sin pregunta GECA.
    tabla['candidato_recomendado'] = tabla['regla_lanzamiento_pdf'].eq(True).fillna(False)
    return tabla


def construir_listado(maestro):
    """Todos los elegibles por lanzamiento; reseñas solo como contexto."""
    columnas = {
        'appid': 'appid',
        'nombre': 'nombre',
        'lanzamiento_ficha_texto': 'lanzamiento',
        'descripcion_corta_texto': 'descripcion',
        'generos_texto': 'generos',
        'desarrolladores_texto': 'desarrolladores',
        'url_tienda': 'url_steam',
        'resenas_total': 'resenas_total',
        'resenas_positivas': 'resenas_positivas',
        'resenas_negativas': 'resenas_negativas',
        'porcentaje_positivas': 'porcentaje_positivas',
        'resenas_estado': 'estado_resenas',
        'ficha_consultado_utc': 'ficha_verificada_utc',
    }
    listado = (
        maestro.loc[maestro['candidato_recomendado'].eq(True)]
        .reindex(columns=list(columnas))
        .rename(columns=columnas)
        .sort_values('nombre', kind='stable', na_position='last')
        .reset_index(drop=True)
    )
    # Evitar descripciones partidas en varias líneas físicas del CSV.
    for columna in ['nombre', 'lanzamiento', 'descripcion', 'generos', 'desarrolladores']:
        listado[columna] = listado[columna].map(
            lambda valor: ' '.join(valor.split()) if isinstance(valor, str) else valor
        )
    return listado


def ejecutar_radar(proximos, seleccion, fichas, resenas, radar):
    edad = radar['max_edad_dias']
    if isinstance(edad, bool) or edad != 7:
        raise ValueError('El PDF exige max_edad_dias: 7.')
    limite = radar['max_propuestas']
    if isinstance(limite, bool) or not isinstance(limite, int) or not 0 <= limite <= 3:
        raise ValueError('max_propuestas debe estar entre 0 y 3.')
    preguntas = {int(k): str(v).strip() for k, v in radar['preguntas_geca'].items() if v and str(v).strip()}
    inicio = ahora_utc()
    estado = Path(radar['carpeta_estado']); estado.mkdir(parents=True, exist_ok=True)


    # Respetar desde/hasta de parameters_proximos.yml.
    principio, fin = resolver_ventana(proximos.get('desde'), proximos.get('hasta'), proximos.get('ventana_meses', 6))
    p = dict(proximos, desde=principio.isoformat(), hasta=fin.isoformat(), actualizar=True, carpeta=str(estado / 'proximos'))
    f = dict(fichas, actualizar=False, max_edad_dias=edad, carpeta=str(estado / 'fichas'))
    r = dict(resenas, actualizar=True, carpeta=str(estado / 'resenas'))
    listado = descargar_proximos_steam(**p)
    if not listado['resumen']['completo']:
        raise RuntimeError('La captura Steam fue parcial: no se publicará un catálogo incompleto. ' + str(listado['resumen']))
    juegos = seleccionar_juegos(listado['juegos'], listado['sin_fecha'], seleccion)
    capturas_iniciales = descargar_fichas_completas(juegos, **f)
    # El radar necesita cobertura completa, sin un límite independiente para fichas.
    if set(capturas_iniciales.appid) != set(juegos.appid):
        raise ValueError('En radar usa fichas.limite: null; limita juegos con seleccion.limite_juegos.')
    inicial = evaluar_fichas(capturas_iniciales, ahora_utc(), edad)
    ids = inicial.loc[inicial.regla_lanzamiento_pdf & inicial.appid.isin(preguntas), 'appid'].sort_values()
    # Verificar todos los candidatos antes de limitar a tres. Orden operativo,
    # no puntuación editorial. Las reseñas no intervienen.
    candidatos = juegos.loc[juegos.appid.isin(ids)]
    # Solo refrescar candidatos leídos de caché; los recién descargados ya se verificaron.
    cacheada = capturas_iniciales.get('ficha_desde_cache', pd.Series(True, index=capturas_iniciales.index)).eq(True)
    renovar = capturas_iniciales.loc[cacheada & capturas_iniciales.appid.isin(ids), 'appid']
    nuevas = descargar_fichas_completas(candidatos.loc[candidatos.appid.isin(renovar)],
                                       **dict(f, actualizar=True, limite=None))
    actuales = pd.concat([capturas_iniciales.loc[capturas_iniciales.appid.isin(ids)
                                                & ~capturas_iniciales.appid.isin(renovar)], nuevas], ignore_index=True)
    definitivas = pd.concat([capturas_iniciales.loc[~capturas_iniciales.appid.isin(ids)], actuales], ignore_index=True)
    validas = evaluar_fichas(actuales, ahora_utc(), edad)
    ids_validos = validas.loc[validas.regla_lanzamiento_pdf, 'appid']
    opiniones = extraer_resenas(juegos, **r)
    corte = ahora_utc()  # Se fija DESPUÉS de las consultas y se persiste.
    maestro = integrar(juegos, definitivas, opiniones['resumen'], opiniones['comentarios'], corte, edad)
    # El listado se filtró por la fecha exacta; confirmar de nuevo con appdetails.
    fechas_ficha = maestro['lanzamiento_ficha_texto'].map(fecha_exacta)
    ventana_valida = fechas_ficha.between(pd.Timestamp(principio), pd.Timestamp(fin)).fillna(False)
    maestro['dentro_ventana_6_meses'] = ventana_valida
    maestro['regla_lanzamiento_pdf'] = maestro['regla_lanzamiento_pdf'] & ventana_valida
    maestro['pregunta_geca'] = maestro.appid.map(preguntas)
    maestro = evaluar_recepcion(maestro)
    # El PDF usa coming_soon y frescura. Discrepancias son advertencias para
    # el analista, no nuevas reglas de exclusión. Una captura parcial se declara.
    aptos = (maestro.appid.isin(ids_validos) & maestro.candidato_recomendado
             & maestro.pregunta_geca.notna())
    propuestas = maestro.loc[aptos].sort_values('appid', kind='stable').head(limite).copy()
    propuestas['captura_completa'] = listado['resumen']['completo']
    propuestas['accion_propuesta'] = 'Validar con el analista; no es una decisión editorial'
    ejecucion = corte.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
    salida = Path(radar['carpeta_salida']) / ejecucion; salida.mkdir(parents=True)
    catalogo_exportar = pd.concat([listado['juegos'], listado['sin_fecha']], ignore_index=True).drop_duplicates('appid')
    archivos_excel = exportar_formatos(catalogo_exportar, definitivas, p, salida)
    tablas = [('steam_listado', juegos, 'consultado_utc', {k:p[k] for k in ['pais','plataforma','filtro','desde','hasta']}),
              ('steam_ficha', capturas_iniciales, 'ficha_consultado_utc', {k:f[k] for k in ['pais','idioma']}),
              ('steam_ficha', actuales, 'ficha_consultado_utc', {k:f[k] for k in ['pais','idioma']}),
              ('steam_resenas', opiniones['resumen'], 'consultado_utc', {k:r[k] for k in ['idiomas','tipo_compra','excluir_offtopic']})]
    # El histórico persistente se construye con Excel al finalizar el workflow.
    # No duplicar todas las respuestas JSON en una base SQLite de cientos de MB.
    # La evidencia de la ejecución queda en maestro_completo.csv y los Excel del radar.
    for nombre, tabla in [('maestro_completo', maestro), ('propuestas', propuestas),
                          ('comentarios', opiniones['comentarios']), ('fichas_iniciales', capturas_iniciales)]:
        preparar_csv(tabla).to_csv(salida / f'{nombre}.csv', index=False, encoding='utf-8-sig')
    # Universo elegible, sin límite de tres. Solo propuestas.csv es el resumen.
    listado_legible = construir_listado(maestro)
    listado_legible.to_csv(
        salida / 'maestro.csv', index=False, encoding='utf-8-sig', sep=';'
    )
    resumen = dict(archivos_excel=archivos_excel, ejecucion=ejecucion, corte_utc=corte.isoformat(), inicio_utc=inicio.isoformat(),
                   juegos=len(juegos), elegibles=int(maestro.regla_lanzamiento_pdf.sum()),
                   candidatos_recomendados=len(listado_legible),
                   criterio_lanzamiento={'coming_soon': True, 'max_edad_dias': 7},
                   resenas_solo_informativas=True,
                   con_pregunta_geca=int((maestro.regla_lanzamiento_pdf & maestro.pregunta_geca.notna()).sum()),
                   propuestas=len(propuestas), listado=listado['resumen'],
                   criterio_orden='appid ascendente, sin ranking editorial',
                   sin_reposicion=False, historial='transfer/geca_steam_historico.xlsx')
    (salida / 'resumen.json').write_text(json.dumps(resumen, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    lineas = ['# Resumen GECA Radar', '', f'Corte: {corte.isoformat()}',
              f'Juegos: {len(juegos)} · Elegibles por lanzamiento: {int(maestro.regla_lanzamiento_pdf.sum())} · Propuestas: {len(propuestas)}',
              'Elegibles: maestro.csv. Regla: Steam indica próximo estreno y ficha correcta verificada en los últimos 7 días. Reseñas solo informativas.',
              f'Alcance: región {p["pais"]}; plataforma {p["plataforma"]}; intervalo {p["desde"]} a {p["hasta"]}.', '']
    if not listado['resumen']['completo']:
        lineas.append('ADVERTENCIA: captura parcial; las propuestas solo representan los juegos observados, no todo Steam.')
    for fila in propuestas.to_dict('records'):
        lineas += [f"- {fila.get('nombre', fila['appid'])} ({fila['appid']}): {fila['pregunta_geca']}",
                   f"  Steam: {fila.get('url_tienda', '')}. Lanzamiento anunciado: {fila.get('lanzamiento_ficha_texto', '')}.",
                   f"  Ficha verificada: {fila.get('ficha_consultado_utc', '')}. Acción: validar con el analista."]
        if fila.get('verificar_fecha_pasada') or fila.get('fecha_textual_distinta'):
            lineas.append('  Advertencia: revisar discrepancia de fecha en maestro_completo.csv.')
    if propuestas.empty:
        lineas.append('Sin propuestas: no hay señal vigente con pregunta GECA, o max_propuestas es cero. Revisar estados y alcance de captura.')
    (salida / 'resumen.md').write_text('\n'.join(lineas), encoding='utf-8')
    return resumen
