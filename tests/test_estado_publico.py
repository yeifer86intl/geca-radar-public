from pathlib import Path
import importlib.util

def test_semilla_publica_presente():
    assert (Path(__file__).resolve().parents[1] / 'bootstrap/geca_steam_historico.xlsx').is_file()

def test_ventana_tres_meses_sin_limite():
    import yaml
    params=yaml.safe_load((Path(__file__).resolve().parents[1] / 'conf/base/parameters_proximos.yml').read_text(encoding='utf8'))['proximos']
    assert params['ventana_meses'] == 3
    assert params['max_paginas'] is None
