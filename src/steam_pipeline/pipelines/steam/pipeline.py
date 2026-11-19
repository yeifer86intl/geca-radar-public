from kedro.pipeline import Node, Pipeline
from . import nodes

def create_pipeline(**kwargs):
    return Pipeline([
        Node(nodes.descargar_juegos, "params:proximos", {
            "juegos": "steam_juegos", "sin_fecha": "steam_sin_fecha",
            "paginas": "steam_paginas", "resumen": "steam_resumen_descarga",
        }, name="descargar_juegos"),
        Node(nodes.seleccionar_juegos,
             ["steam_juegos", "steam_sin_fecha", "params:seleccion"],
             "steam_juegos_seleccionados", name="seleccionar_juegos"),
        Node(nodes.descargar_resenas, ["steam_juegos_seleccionados", "params:resenas"],
             {"resumen": "steam_resenas", "comentarios": "steam_comentarios"},
             name="descargar_resenas"),
        Node(nodes.descargar_fichas, ["steam_juegos_seleccionados", "params:fichas"],
             "steam_fichas", name="descargar_fichas"),
        Node(nodes.unir_datos, ["steam_juegos_seleccionados", "steam_resenas", "steam_fichas"],
             "steam_juegos_enriquecidos", name="unir_datos"),
    ])
