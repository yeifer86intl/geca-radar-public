"""Checkpoints recuperables de fichas Steam, en una rama separada de GitHub.

Solo usa la API GitHub cuando GECA_CHECKPOINT_TOKEN y GECA_CHECKPOINT_REPO están
presentes. Cada bloque se guarda en gzip; al volver a ejecutar, las respuestas
recientes se restauran al caché ordinario y su hora de verificación NO se altera.
La rama no se usa como histórico editorial: el histórico sigue en Excel.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

BRANCH = "geca-checkpoints"
PREFIX = "fichas"


def _api(method, endpoint, body=None):
    token = os.environ["GECA_CHECKPOINT_TOKEN"]
    repo = os.environ["GECA_CHECKPOINT_REPO"]
    url = f"https://api.github.com/repos/{repo}"
    if endpoint:
        url += "/" + endpoint.lstrip("/")
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(url, data=payload, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "geca-radar-checkpoints",
        **({"Content-Type": "application/json"} if body is not None else {}),
    })
    for attempt in range(4):
        try:
            with urlopen(req, timeout=60) as response:
                data = response.read()
                return json.loads(data) if data else {}
        except HTTPError as exc:
            if exc.code == 404:
                # GET de referencias/archivos puede no existir; el repositorio
                # base NO debe ocultar un error de autenticación o de URL.
                if endpoint.strip("/") == "":
                    raise RuntimeError(
                        f"GitHub API 404 al consultar el repositorio {repo}. "
                        "Revisa GECA_CHECKPOINT_REPO y permisos del token."
                    ) from exc
                return None
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                message = exc.read().decode("utf-8", errors="replace")[:500]
                raise RuntimeError(f"GitHub API {exc.code}: {message}") from exc
            time.sleep(2 ** attempt)
        except (TimeoutError, URLError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def enabled():
    return bool(os.getenv("GECA_CHECKPOINT_TOKEN") and os.getenv("GECA_CHECKPOINT_REPO"))


def _branch_exists():
    result = _api("GET", f"git/ref/heads/{BRANCH}")
    return result is not None


def _ensure_branch():
    if _branch_exists():
        return
    # Rama separada. El estado editorial permanece en los artifacts Excel.
    default = _api("GET", "")
    if not default:
        raise RuntimeError("No se pudo consultar el repositorio para crear checkpoint")
    source = _api("GET", "git/ref/heads/" + quote(default["default_branch"], safe=""))
    if not source:
        raise RuntimeError("No se pudo localizar la rama principal")
    try:
        _api("POST", "git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": source["object"]["sha"]})
    except RuntimeError:
        if not _branch_exists():
            raise


def _get_file(path):
    return _api("GET", f"contents/{path}?ref={BRANCH}")


def _list(path):
    value = _api("GET", f"contents/{path}?ref={BRANCH}")
    return value if isinstance(value, list) else []


def _unpack(blob):
    return json.loads(gzip.decompress(blob).decode("utf-8"))


def restore(cache: Path, pais: str, idioma: str, max_edad_dias: float = 7):
    """Recupera respuestas recientes; el validador normal vuelve a comprobarlas."""
    if not enabled():
        return 0
    if not _branch_exists():
        return 0
    base = f"{PREFIX}/{pais}/{idioma}"
    restored = 0
    today = datetime.now(timezone.utc).date()
    # La API de contenidos lista primero las carpetas. Se itera de reciente a antiguo.
    directories = []
    for entry in _list(base):
        try:
            d = datetime.strptime(entry["name"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        if 0 <= (today-d).days <= int(max_edad_dias) + 1:
            directories.append((d, entry["path"]))
    for _, directory in sorted(directories, reverse=True):
        for item in _list(directory):
            if not item.get("name", "").endswith(".json.gz"):
                continue
            # Los archivos pequeños se recuperan a través de contents API.
            file = _get_file(item["path"])
            if not file or file.get("encoding") != "base64":
                continue
            rows = _unpack(base64.b64decode(file["content"]))
            for appid, packet in rows.items():
                path = cache / f"{appid}.json"
                if path.exists():
                    continue
                # No convertir fallos/no_disponible en respuestas reutilizables.
                try:
                    stamp = datetime.fromisoformat(packet["consultado_utc"].replace("Z", "+00:00"))
                    if not timedelta(0) <= datetime.now(timezone.utc) - stamp <= timedelta(days=max_edad_dias):
                        continue
                    item_resp = packet["respuesta"][str(appid)]
                    if item_resp.get("success") is not True or not isinstance(item_resp.get("data"), dict):
                        continue
                except (KeyError, ValueError, TypeError, AttributeError):
                    continue
                path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
                restored += 1
    print(f"Checkpoints Steam restaurados: {restored} fichas aún vigentes.", flush=True)
    return restored


def save(cache: Path, ids: list[int], pais: str, idioma: str, batch_no: int):
    """Guarda UN bloque completo, sin depender del post-step del workflow."""
    if not enabled() or not ids:
        return
    _ensure_branch()
    rows = {}
    for appid in ids:
        path = cache / f"{appid}.json"
        try:
            packet = json.loads(path.read_text(encoding="utf-8"))
            entry = packet["respuesta"][str(appid)]
            if entry.get("success") is True and isinstance(entry.get("data"), dict):
                rows[str(appid)] = packet
        except (OSError, KeyError, TypeError, ValueError, AttributeError):
            pass
    if not rows:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"{PREFIX}/{pais}/{idioma}/{stamp}/bloque-{batch_no:05d}.json.gz"
    compressed = gzip.compress(json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8"), compresslevel=6)
    # API contents JSON tiene un tamaño práctico limitado; si excede 900 KiB,
    # se divide el bloque en subbloques, cada uno con su propia ruta.
    max_bytes = 700_000
    chunks = []
    if len(compressed) <= max_bytes:
        chunks = [(key, compressed)]
    else:
        entries = list(rows.items())
        n = max(2, (len(compressed) // max_bytes) + 2)
        for index in range(0, len(entries), max(1, len(entries) // n)):
            part = dict(entries[index:index + max(1, len(entries) // n)])
            sub = gzip.compress(json.dumps(part, ensure_ascii=False).encode("utf-8"), compresslevel=6)
            if len(sub) > max_bytes:
                raise RuntimeError("Checkpoint excede el límite de la API: reduzca GECA_CHECKPOINT_BATCH")
            chunks.append((key.replace(".json.gz", f"-parte-{len(chunks):02d}.json.gz"), sub))
    for item_path, blob in chunks:
        current = _get_file(item_path)
        args = {"message": f"GECA checkpoint fichas {stamp} bloque {batch_no}",
                "content": base64.b64encode(blob).decode("ascii"), "branch": BRANCH}
        if current and current.get("sha"):
            args["sha"] = current["sha"]
        _api("PUT", f"contents/{item_path}", args)
    print(f"Checkpoint guardado: bloque {batch_no}; {len(rows)} fichas; {len(compressed)/1024:.0f} KiB.", flush=True)
