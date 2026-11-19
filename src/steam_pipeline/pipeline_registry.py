from kedro.pipeline import Node, Pipeline
from .pipelines.steam.pipeline import create_pipeline
from .radar import ejecutar_radar


def register_pipelines():
    radar = Pipeline([Node(ejecutar_radar,
                          ['params:proximos', 'params:seleccion', 'params:fichas',
                           'params:resenas', 'params:radar'],
                          'radar_resumen', name='radar_diario')])
    return {'__default__': radar, 'radar': radar, 'steam': create_pipeline()}
