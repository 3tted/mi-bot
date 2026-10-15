"""Roles del staff, a quién va dirigido un comando y duraciones (30m, 2h, 1d...)."""
import re
import time
from dataclasses import dataclass

from telegram import MessageEntity, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

import db

NIVELES = {
    "founder": 100, "cofounder": 90, "admin": 80, "mod": 60,
    "helper": 40, "muter": 40, "cleaner": 40, "free": 10,
}
NOMBRES_ROL = {
    "founder": "👑 Fundador", "cofounder": "💎 Cofundador", "admin": "⚡ Administrador",
    "mod": "🛡️ Moderador", "muter": "🔇 Muter", "cleaner": "🧹 Cleaner",
    "helper": "🤝 Helper", "free": "🕊️ Libre",
}


class Aviso(Exception):
    """Error pensado para el usuario: el bot responde con este texto."""


def nivel(rol: str | None) -> int:
    return NIVELES.get(rol, 0)


def es_staff(rol: str | None) -> bool:
    return nivel(rol) >= NIVELES["helper"]


# Caché del staff de cada grupo: admins de Telegram + roles guardados en la base de datos
_staff: dict[int, tuple[float, dict[int, str]]] = {}
_DURACION_CACHE = 300


async def staff(bot, chat_id: int, forzar: bool = False) -> dict[int, str]:
    guardado = _staff.get(chat_id)
    if guardado and not forzar and time.time() - guardado[0] < _DURACION_CACHE:
        return guardado[1]
    roles = db.roles_del_chat(chat_id)
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except Exception:
        admins = []
    for admin in admins:
        if admin.user.is_bot:
            continue
        rol_telegram = "founder" if admin.status == ChatMemberStatus.OWNER else "admin"
        if nivel(rol_telegram) > nivel(roles.get(admin.user.id)):
            roles[admin.user.id] = rol_telegram
    _staff[chat_id] = (time.time(), roles)
    return roles


def olvidar_staff(chat_id: int):
    _staff.pop(chat_id, None)


async def rol_de(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int | None = None) -> str | None:
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        return None
    if user_id is None:
        mensaje = update.message
        # Un admin que escribe como "anónimo" llega como el propio grupo
        if mensaje and mensaje.sender_chat and mensaje.sender_chat.id == chat.id:
            return "admin"
        user_id = update.effective_user.id
    return (await staff(context.bot, chat.id)).get(user_id)


# ---------- A quién va dirigido el comando ----------

@dataclass
class Objetivo:
    id: int
    nombre: str

    @property
    def mencion(self) -> str:
        return mention_html(self.id, self.nombre)


def _respuesta_real(mensaje):
    """El mensaje respondido, ignorando el mensaje inicial de un tema (foros)."""
    respuesta = mensaje.reply_to_message
    if respuesta and not respuesta.forum_topic_created and respuesta.from_user and not respuesta.sender_chat:
        return respuesta
    return None


async def _objetivo_desde_texto(context, chat_id: int, palabra: str) -> Objetivo:
    if palabra.startswith("@"):
        encontrado = db.buscar_usuario(palabra)
        if not encontrado:
            raise Aviso(
                f"🔍 No conozco a {palabra} todavía. Responde a un mensaje suyo o usa su ID numérico."
            )
        return Objetivo(*encontrado)
    if palabra.lstrip("-").isdigit():
        user_id = int(palabra)
        nombre = db.nombre_usuario(user_id)
        if not nombre:
            try:
                nombre = (await context.bot.get_chat_member(chat_id, user_id)).user.full_name
            except Exception:
                nombre = str(user_id)
        return Objetivo(user_id, nombre)
    raise Aviso("👻 ¿A quién? Responde a su mensaje, o escribe su @usuario o su ID.")


async def objetivo(update: Update, context, args: list[str]) -> tuple[Objetivo, list[str]]:
    """Devuelve el usuario objetivo y el resto de argumentos."""
    mensaje = update.message
    respuesta = _respuesta_real(mensaje)
    if respuesta:
        u = respuesta.from_user
        return Objetivo(u.id, u.full_name), args

    menciones = [e for e in mensaje.entities if e.type == MessageEntity.TEXT_MENTION]
    if menciones:
        e = menciones[0]
        resto = mensaje.text[e.offset + e.length:].split()
        return Objetivo(e.user.id, e.user.full_name), resto

    if not args:
        raise Aviso("👻 ¿A quién? Responde a su mensaje, o escribe su @usuario o su ID.")
    return await _objetivo_desde_texto(context, update.effective_chat.id, args[0]), args[1:]


async def objetivos_multiples(update: Update, context, args: list[str], maximo: int = 20) -> list[Objetivo]:
    lista = []
    respuesta = _respuesta_real(update.message)
    if respuesta:
        lista.append(Objetivo(respuesta.from_user.id, respuesta.from_user.full_name))
    for palabra in args:
        if palabra.startswith("@") or palabra.lstrip("-").isdigit():
            lista.append(await _objetivo_desde_texto(context, update.effective_chat.id, palabra))
    if not lista:
        raise Aviso("👻 Escribe los @usuarios o IDs separados por espacios (máximo 20).")
    unicos = list({o.id: o for o in lista}.values())
    if len(unicos) > maximo:
        raise Aviso(f"✋ Máximo {maximo} usuarios a la vez.")
    return unicos


# ---------- Duraciones ----------

_UNIDADES = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_NOMBRES_UNIDAD = {"s": "segundos", "m": "minutos", "h": "horas", "d": "días", "w": "semanas"}


def duracion(palabra: str) -> int | None:
    m = re.fullmatch(r"(\d+)([smhdw])", palabra.lower())
    return int(m.group(1)) * _UNIDADES[m.group(2)] if m else None


def texto_duracion(segundos: int) -> str:
    for unidad in ("w", "d", "h", "m", "s"):
        if segundos % _UNIDADES[unidad] == 0:
            return f"{segundos // _UNIDADES[unidad]} {_NOMBRES_UNIDAD[unidad]}"
    return f"{segundos} segundos"
