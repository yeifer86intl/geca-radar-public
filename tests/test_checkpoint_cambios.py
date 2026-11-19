"""Pruebas independientes de red de caché y cambios de ficha."""
import pandas as pd
from steam_pipeline.descargas import steam_fichas_completas as mod


def test_cache_reutiliza_y_refresca_cuando_cambia_listado(tmp_path, monkeypatch):
    monkeypatch.delenv('GECA_CHECKPOINT_TOKEN', raising=False)
    llamados = []

    def consulta(url, pausa):
        llamados.append(url)
        return {'123': {'success': True, 'data': {
            'name': 'Ejemplo',
            'release_date': {'date': 'Mar 2027', 'coming_soon': True},
        }}}

    monkeypatch.setattr(mod, '_consulta', consulta)
    carpeta = tmp_path / 'fichas'
    normal = pd.DataFrame([{'appid': 123, 'nombre': 'Ejemplo', 'lanzamiento_texto': 'Mar 2027'}])
    actualizado = pd.DataFrame([{'appid': 123, 'nombre': 'Ejemplo', 'lanzamiento_texto': 'Apr 2027'}])
    mod.descargar_fichas_completas(normal, carpeta=str(carpeta), pausa=0)
    assert len(llamados) == 1
    segundo = mod.descargar_fichas_completas(normal, carpeta=str(carpeta), pausa=0)
    assert len(llamados) == 1
    assert bool(segundo.iloc[0]['ficha_desde_cache'])
    nuevo = mod.descargar_fichas_completas(actualizado, carpeta=str(carpeta), pausa=0)
    assert len(llamados) == 2
    assert not bool(nuevo.iloc[0]['ficha_desde_cache'])
    assert nuevo.iloc[0]['ficha_consultado_utc']


def test_cache_no_fabrica_verificacion_nueva(tmp_path, monkeypatch):
    monkeypatch.delenv('GECA_CHECKPOINT_TOKEN', raising=False)
    monkeypatch.setattr(mod, '_consulta', lambda url, pausa: {'123': {'success': True, 'data': {'name': 'X'}}})
    carpeta = str(tmp_path / 'fichas')
    tabla = pd.DataFrame([{'appid': 123, 'nombre': 'X'}])
    primera = mod.descargar_fichas_completas(tabla, carpeta=carpeta, pausa=0)
    segunda = mod.descargar_fichas_completas(tabla, carpeta=carpeta, pausa=0)
    assert primera.iloc[0]['ficha_consultado_utc'] == segunda.iloc[0]['ficha_consultado_utc']
