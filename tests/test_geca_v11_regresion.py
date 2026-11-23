"""Regresiones para evitar fallos de GitHub Actions y datos sin fecha."""
from pathlib import Path
import pandas as pd
from steam_pipeline.ventana import resolver_ventana

def test_rango_invalido_tiene_mensaje_preciso():
    import pytest
    with pytest.raises(ValueError, match="posterior"):
        resolver_ventana("2027-03-15", "2026-10-22", 3)

def test_workflow_no_expone_token_checkpoint_a_pytest():
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/radar.yml").read_text()
    cabecera, ejecucion = wf.split("      - name: Ejecutar extracción Steam", 1)
    assert "GECA_CHECKPOINT_TOKEN:" not in cabecera
    assert "GECA_CHECKPOINT_TOKEN:" in ejecucion
    assert 'cron: "0 11 * * *"' in wf  # 07:00 Venezuela

def test_serie_fecha_ausente_no_inventa_fecha():
    from steam_pipeline.exportaciones import fecha_exacta
    t = pd.DataFrame({'appid':[1,2]})
    if 'lanzamiento_ficha_texto' not in t:
        t['lanzamiento_ficha_texto'] = pd.Series(pd.NA, index=t.index, dtype='object')
    assert t.lanzamiento_ficha_texto.map(fecha_exacta).isna().all()
