"""Adaptadores de Kedro: cada descargador recibe su propio diccionario de parámetros."""
import json
import logging
import pandas as pd
from steam_pipeline.descargas.steam_proximos_paginados import descargar_proximos_steam
from steam_pipeline.descargas.steam_resenas import extraer_resenas
from steam_pipeline.descargas.steam_fichas_completas import descargar_fichas_completas

log = logging.getLogger(__name__)

def descargar_juegos(config):
    resultado = descargar_proximos_steam(**config)
    if not resultado["resumen"]["completo"]:
        log.warning("Listado parcial: %s", resultado["resumen"])
    return resultado

def seleccionar_juegos(juegos, sin_fecha, config):
    tablas = [juegos, sin_fecha] if config["incluir_sin_fecha"] else [juegos]
    seleccion = pd.concat(tablas, ignore_index=True).drop_duplicates("appid")
    limite = config["limite_juegos"]
    if limite is not None:
        if isinstance(limite, bool) or not isinstance(limite, int) or limite < 1:
            raise ValueError("limite_juegos debe ser null o un entero positivo")
        seleccion = seleccion.head(limite)
    seleccion = seleccion.copy()
    seleccion["appid"] = seleccion["appid"].astype("int64")
    return seleccion

def preparar_csv(tabla):
    """Conserva listas/diccionarios como JSON válido dentro de celdas CSV."""
    tabla = tabla.copy()
    for columna in tabla.select_dtypes(include="object"):
        tabla[columna] = tabla[columna].map(
            lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x
        )
    return tabla

def descargar_resenas(juegos, config):
    resultado = extraer_resenas(juegos, **config)
    estados = resultado["resumen"]["estado"]
    if not estados.eq("ok").all():
        log.warning("Revisar estados de reseñas: %s", estados.value_counts().to_dict())
    return {k: preparar_csv(v) for k, v in resultado.items()}

def descargar_fichas(juegos, config):
    fichas = descargar_fichas_completas(juegos, **config)
    if not fichas["ficha_estado"].eq("ok").all():
        log.warning("Revisar estados de fichas: %s", fichas.attrs)
    return preparar_csv(fichas)

def unir_datos(juegos, resenas, fichas):
    # Los comentarios van aparte: son varias filas por appid.
    return juegos.merge(resenas, on="appid", how="left", validate="one_to_one").merge(
        fichas, on="appid", how="left", validate="one_to_one", suffixes=("", "_ficha")
    )
