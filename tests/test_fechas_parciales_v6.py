from datetime import date
from steam_pipeline.descargas.steam_proximos_paginados import interpretar


def test_fecha_parcial_anio_pendiente():
    data, category = interpretar('2027',date(2026,11,17),date(2027,5,17))
    assert category == 'sin_fecha' and data['precision_fecha'] == 'anio'


def test_anio_fuera_de_ventana():
    _, category = interpretar('2028',date(2026,11,17),date(2027,5,17))
    assert category == 'fuera'


def test_mes_parcial_solapa():
    data, category = interpretar('mayo de 2027',date(2026,11,17),date(2027,5,17))
    assert category == 'sin_fecha' and data['precision_fecha'] == 'mes'


def test_mes_fuera():
    _, category = interpretar('junio de 2027',date(2026,11,17),date(2027,5,17))
    assert category == 'fuera'


def test_fecha_exacta():
    data, category = interpretar('15 feb 2027',date(2026,11,17),date(2027,5,17))
    assert category == 'dentro' and data['precision_fecha'] == 'dia'


def test_sin_fecha():
    _, category = interpretar('Próximamente',date(2026,11,17),date(2027,5,17))
    assert category == 'sin_fecha'
