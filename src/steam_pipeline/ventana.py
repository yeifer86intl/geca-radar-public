"""Ventana de seis meses naturales, calculada en la zona horaria de Venezuela."""
import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Caracas")


def sumar_meses(dia: date, meses: int) -> date:
    if isinstance(meses, bool) or not isinstance(meses, int) or meses < 1:
        raise ValueError("ventana_meses debe ser entero positivo")
    indice = dia.year * 12 + dia.month - 1 + meses
    anio, mes0 = divmod(indice, 12)
    mes = mes0 + 1
    return date(anio, mes, min(dia.day, calendar.monthrange(anio, mes)[1]))


def resolver_ventana(desde=None, hasta=None, ventana_meses=6, *, hoy=None):
    """Una ventana móvil cuando desde/hasta son nulos; también permite pruebas históricas."""
    dia = hoy or datetime.now(ZONA).date()
    principio = date.fromisoformat(str(desde)) if desde is not None else dia
    fin = date.fromisoformat(str(hasta)) if hasta is not None else sumar_meses(principio, ventana_meses)
    if fin < principio:
        raise ValueError("hasta es anterior a desde")
    return principio, fin
