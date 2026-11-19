from steam_pipeline.descargas import checkpoint_fichas as cp

def test_repo_api_no_termina_en_barra(monkeypatch):
    vistos = []
    monkeypatch.setenv("GECA_CHECKPOINT_TOKEN", "token-prueba")
    monkeypatch.setenv("GECA_CHECKPOINT_REPO", "organizacion/repositorio")
    class Respuesta:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b'{"default_branch":"main"}'
    def consulta(req, timeout):
        vistos.append(req.full_url)
        return Respuesta()
    monkeypatch.setattr(cp, "urlopen", consulta)
    assert cp._api("GET", "")["default_branch"] == "main"
    assert vistos == ["https://api.github.com/repos/organizacion/repositorio"]
