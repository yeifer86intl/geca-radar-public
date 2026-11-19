"""Regresiones del contrato Steam descrito en las páginas 3 y 4 del PDF."""
import json
from pathlib import Path
import pandas as pd
import pytest
from steam_pipeline import radar
from steam_pipeline.descargas import steam_proximos_paginados as proximos
from steam_pipeline.pipelines.steam.nodes import seleccionar_juegos

NOW = pd.Timestamp('2026-10-29T12:00:00Z')

def test_paginacion_no_depende_del_orden_publico(tmp_path, monkeypatch):
    pages = iter([
        {'start': 0, 'total_count': 3, 'results_html': '<a class="search_result_row" href="/app/1/"><span class="title">A</span><div class="search_released">1 ene 2028</div></a>'},
        {'start': 1, 'total_count': 3, 'results_html': '<a class="search_result_row" href="/app/2/"><span class="title">B</span><div class="search_released">1 nov 2026</div></a>'},
        {'start': 2, 'total_count': 3, 'results_html': '<a class="search_result_row" href="/app/3/"><span class="title">C</span><div class="search_released">2027</div></a>'},
    ])
    monkeypatch.setattr(proximos, '_obtener_json', lambda *a: next(pages))
    r = proximos.descargar_proximos_steam(desde='2026-10-29', hasta='2027-12-31', carpeta=tmp_path, pausa=0)
    assert r['resumen']['completo']
    assert not r['resumen']['orden_observado']
    assert r['juegos'].appid.tolist() == [2]
    assert r['sin_fecha'].appid.tolist() == [3]
    assert seleccionar_juegos(r['juegos'], r['sin_fecha'], {'incluir_sin_fecha': True, 'limite_juegos': None}).appid.tolist() == [2, 3]

@pytest.mark.parametrize('completo', [True, False])
@pytest.mark.parametrize('estado_resenas', ['ok', 'error'])
def test_propuestas_sin_resenas_y_reposicion(tmp_path, monkeypatch, completo, estado_resenas):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(radar, 'ahora_utc', lambda: NOW)
    juegos = pd.DataFrame([dict(appid=i, nombre=f'Juego {i}', lanzamiento_texto='1 nov 2026',
                               consultado_utc=NOW.isoformat(), url_tienda=f'https://store.steampowered.com/app/{i}/') for i in range(1, 6)])
    monkeypatch.setattr(radar, 'descargar_proximos_steam', lambda **kw: {'juegos': juegos, 'sin_fecha': juegos.iloc[:0], 'resumen': {'completo': completo}})
    def fichas(j, **kw):
        return pd.DataFrame([dict(appid=i, ficha_estado='ok', ficha_consultado_utc=NOW.isoformat(),
                                  ficha_desde_cache=not kw['actualizar'],
                                  proximo_lanzamiento=not (kw['actualizar'] and i == 1),
                                  lanzamiento_ficha_texto='1 nov 2026') for i in j.appid])
    monkeypatch.setattr(radar, 'descargar_fichas_completas', fichas)
    monkeypatch.setattr(radar, 'extraer_resenas', lambda j, **kw: {
        'resumen': pd.DataFrame([dict(appid=i, estado=estado_resenas, consultado_utc=NOW.isoformat(),
                                      resenas_total=0 if estado_resenas == 'ok' else None,
                                      porcentaje_positivas=None) for i in j.appid]),
        'comentarios': pd.DataFrame(columns=['appid', 'recommendationid'])})
    cfg = dict(max_edad_dias=7, max_propuestas=3, carpeta_estado='estado', carpeta_salida='salida',
               preguntas_geca={str(i): '¿Qué narrativa revisar?' for i in range(1, 5)})
    if not completo:
        with pytest.raises(RuntimeError, match='parcial'):
            radar.ejecutar_radar(dict(pais='es', plataforma=None, filtro='comingsoon', desde='2026-10-29', hasta='2027-04-29'),
                                 dict(incluir_sin_fecha=False, limite_juegos=None), dict(pais='es', idioma='spanish'),
                                 dict(idiomas=['all'], tipo_compra=1, excluir_offtopic=True), cfg)
        return
    result = radar.ejecutar_radar(dict(pais='es', plataforma=None, filtro='comingsoon', desde='2026-10-29', hasta='2027-04-29'),
                                 dict(incluir_sin_fecha=False, limite_juegos=None), dict(pais='es', idioma='spanish'),
                                 dict(idiomas=['all'], tipo_compra=1, excluir_offtopic=True), cfg)
    assert result['propuestas'] == 3
    assert result['elegibles'] == 4  # El juego 5 sigue siendo elegible, pero sin pregunta.
    salida = next(Path('salida').iterdir())
    p = pd.read_csv(salida / 'propuestas.csv')
    assert p.appid.tolist() == [2, 3, 4]  # El 4 repone al 1, publicado al refrescar.
    assert p.captura_completa.eq(completo).all()
    assert len(pd.read_csv(salida / 'maestro.csv', sep=';')) == 4
    assert all((salida / name).is_file() for name in ['catalogo_new.xlsx', 'fichas_new.xlsx', 'verificacion.xlsx'])
    assert 'ADVERTENCIA: captura parcial' not in (salida / 'resumen.md').read_text()

def test_fechas_son_advertencias_normalizadas():
    juegos = pd.DataFrame([dict(appid=1, lanzamiento_texto='27 oct 2026')])
    fichas = pd.DataFrame([dict(appid=1, ficha_estado='ok', ficha_consultado_utc=NOW.isoformat(),
                                proximo_lanzamiento=True, lanzamiento_ficha_texto='Oct 27, 2026')])
    r = radar.integrar(juegos, fichas, pd.DataFrame([dict(appid=1, estado='error')]), pd.DataFrame(), NOW, 7)
    assert r.regla_lanzamiento_pdf.iloc[0]
    assert r.verificar_fecha_pasada.iloc[0]
    assert not r.fecha_textual_distinta.iloc[0]
