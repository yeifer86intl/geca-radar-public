from datetime import date
from steam_pipeline.ventana import resolver_ventana, sumar_meses
from steam_pipeline.descargas.steam_proximos_paginados import descargar_proximos_steam
from steam_pipeline.pipelines.steam.nodes import seleccionar_juegos
import pandas as pd


def test_ventana_movil_y_fin_de_mes():
    assert resolver_ventana(hoy=date(2026, 11, 17)) == (date(2026, 11, 17), date(2027, 5, 17))
    assert sumar_meses(date(2026, 8, 31), 6) == date(2027, 2, 28)


def test_sin_fecha_no_seleccionado():
    juegos = pd.DataFrame([{'appid': 1}])
    sin_fecha = pd.DataFrame([{'appid': 2}])
    t = seleccionar_juegos(juegos, sin_fecha, {'incluir_sin_fecha': False, 'limite_juegos': None})
    assert t.appid.tolist() == [1]


def test_paginacion_hasta_fin_real(tmp_path, monkeypatch):
    from steam_pipeline.descargas import steam_proximos_paginados as m
    paginas = iter([
        {'results_html': '<a class="search_result_row" href="/app/12/"><span class="title">A</span><div class="search_released">20 nov 2026</div></a>', 'start':0, 'total_count':2},
        {'results_html': '<a class="search_result_row" href="/app/13/"><span class="title">B</span><div class="search_released">20 may 2028</div></a>', 'start':1, 'total_count':2},
    ])
    monkeypatch.setattr(m, '_obtener_json', lambda *a: next(paginas))
    r = descargar_proximos_steam(desde='2026-11-17', hasta='2027-05-17', max_paginas=None, tamano_pagina=1, carpeta=tmp_path, pausa=0)
    assert r['resumen']['completo']
    assert r['resumen']['paginas_procesadas'] == 2
    assert r['juegos'].appid.tolist() == [12]
