"""Duraciones al estilo Group Help: "3 months 2 days 12 hours 4 minutes 34 seconds", en inglés o español."""
import re

MINIMO = 30                 # 30 segundos
MAXIMO = 365 * 86400        # 365 días

_UNIDADES = [
    (("month", "months", "mes", "meses", "mo"), 30 * 86400),
    (("week", "weeks", "semana", "semanas", "w", "sem"), 7 * 86400),
    (("day", "days", "dia", "días", "dias", "día", "d"), 86400),
    (("hour", "hours", "hora", "horas", "h", "hr", "hrs"), 3600),
    (("minute", "minutes", "minuto", "minutos", "min", "mins", "m"), 60),
    (("second", "seconds", "segundo", "segundos", "sec", "secs", "seg", "s"), 1),
]
_POR_NOMBRE = {nombre: segundos for nombres, segundos in _UNIDADES for nombre in nombres}


def leer(texto: str) -> int | None:
    """Convierte "2 days 3h", "1 mes", "30m" o "90" (minutos) en segundos. None si no se entiende."""
    texto = texto.strip().lower().replace(",", " ")
    if not texto:
        return None
    if texto.isdigit():
        return int(texto) * 60  # Un número solo se toma como minutos
    total, pos = 0, 0
    for m in re.finditer(r"(\d+)\s*([a-záéíóúñ]+)", texto):
        if texto[pos:m.start()].strip():
            return None
        unidad = _POR_NOMBRE.get(m.group(2))
        if unidad is None:
            return None
        total += int(m.group(1)) * unidad
        pos = m.end()
    if texto[pos:].strip() or not total:
        return None
    return total


def escribir(segundos: int | None) -> str:
    """30 Minutos · 1 Día 2 Horas · Para siempre"""
    if not segundos:
        return "Para siempre"
    partes = []
    for nombres_es, valor in (("Mes", 30 * 86400), ("Día", 86400), ("Hora", 3600), ("Minuto", 60), ("Segundo", 1)):
        n, segundos = divmod(segundos, valor)
        if n:
            plural = {"Mes": "Meses"}.get(nombres_es, nombres_es + "s")
            partes.append(f"{n} {nombres_es if n == 1 else plural}")
    return " ".join(partes[:3])
