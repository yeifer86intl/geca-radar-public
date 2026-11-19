"""La fecha de captura nunca se renueva al leer una respuesta guardada."""
import json
from datetime import datetime, timezone, timedelta


def leer_cache_vigente(ruta, url, appid, max_edad_dias=7, ahora=None):
    ahora = ahora or datetime.now(timezone.utc)
    try:
        paquete = json.loads(ruta.read_text(encoding='utf-8'))
        fecha = datetime.fromisoformat(paquete['consultado_utc'].replace('Z', '+00:00'))
        item = paquete['respuesta'][str(appid)]
        if (paquete['url'] == url and fecha.tzinfo is not None
                and timedelta(0) <= ahora - fecha <= timedelta(days=max_edad_dias)
                and item.get('success') is True and isinstance(item.get('data'), dict)):
            return paquete
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        pass
    return None
