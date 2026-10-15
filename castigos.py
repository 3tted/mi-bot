"""Castigos automáticos (los usan todas las protecciones) y el canal de registro."""
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from telegram import ChatPermissions
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

import db

ACCIONES = ["off", "borrar", "warn", "mute", "kick", "ban"]
NOMBRE_ACCION = {
    "off": "❌ Apagado", "borrar": "🗑️ Borrar", "warn": "⚠️ Advertir",
    "mute": "🔇 Silenciar", "kick": "🌀 Expulsar", "ban": "👻 Banear",
}


async def borrar_mensaje_luego(context: ContextTypes.DEFAULT_TYPE):
    chat_id, mensaje_id = context.job.data
    try:
        await context.bot.delete_message(chat_id, mensaje_id)
    except Exception:
        pass


def programar_borrado(context, chat_id: int, mensaje_id: int, segundos: int):
    if segundos > 0 and context.job_queue:
        context.job_queue.run_once(borrar_mensaje_luego, segundos, data=(chat_id, mensaje_id))


async def registrar(bot, chat, texto: str):
    """Envía un aviso al canal de registro del grupo, si está configurado."""
    registro = db.ajustes(chat.id)["registro"]
    if not (registro["on"] and registro["chat_id"]):
        return
    try:
        await bot.send_message(registro["chat_id"], f"📝 <b>{escape(chat.title or str(chat.id))}</b>\n{texto}")
    except (BadRequest, Forbidden) as e:
        logging.warning(f"No pude escribir en el canal de registro de {chat.id}: {e}")


async def aplicar_basico(bot, chat_id: int, user_id: int, accion: str, segundos: int | None = None):
    hasta = datetime.now(timezone.utc) + timedelta(seconds=segundos) if segundos else None
    if accion == "ban":
        await bot.ban_chat_member(chat_id, user_id, until_date=hasta)
    elif accion == "kick":
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
    elif accion == "mute":
        await bot.restrict_chat_member(chat_id, user_id, ChatPermissions.no_permissions(), until_date=hasta)


async def castigar(context: ContextTypes.DEFAULT_TYPE, chat, usuario, accion: str, motivo: str,
                   mensaje=None, segundos_mute: int = 3600) -> bool:
    """Borra el mensaje (si hay) y aplica la acción. Devuelve True si hizo algo."""
    if accion == "off":
        return False
    bot = context.bot
    if mensaje is not None:
        try:
            await mensaje.delete()
        except (BadRequest, Forbidden):
            pass

    mencion = mention_html(usuario.id, usuario.first_name or usuario.full_name)
    try:
        if accion == "borrar":
            texto = f"🗑️ {escape(motivo)}, {mencion}."
        elif accion == "warn":
            a = db.ajustes(chat.id)
            warns = db.miembro(chat.id, usuario.id)["warns"] + 1
            if warns >= a["warn_limite"]:
                db.actualizar_miembro(chat.id, usuario.id, warns=0)
                dias = a["warn_dias"] * 86400 or None
                await aplicar_basico(bot, chat.id, usuario.id, a["warn_castigo"], dias)
                texto = (f"⚠️ {mencion} llegó a {warns}/{a['warn_limite']} advertencias "
                         f"({escape(motivo)}) → {NOMBRE_ACCION[a['warn_castigo']]}.")
            else:
                db.actualizar_miembro(chat.id, usuario.id, warns=warns)
                texto = f"⚠️ {mencion}: {escape(motivo)}. Advertencia <b>{warns}/{a['warn_limite']}</b>."
        elif accion == "mute":
            await aplicar_basico(bot, chat.id, usuario.id, "mute", segundos_mute)
            duracion = f" por {segundos_mute // 60} min" if segundos_mute else ""
            texto = f"🔇 {mencion} silenciado{duracion}: {escape(motivo)}."
        elif accion == "kick":
            await aplicar_basico(bot, chat.id, usuario.id, "kick")
            texto = f"🌀 {mencion} expulsado: {escape(motivo)}."
        elif accion == "ban":
            await aplicar_basico(bot, chat.id, usuario.id, "ban")
            texto = f"👻 {mencion} enviado a la Zona Fantasma: {escape(motivo)}."
        else:
            return False
    except (BadRequest, Forbidden) as e:
        logging.warning(f"No pude aplicar {accion} en {chat.id}: {e}")
        return True

    try:
        aviso = await bot.send_message(chat.id, texto)
        programar_borrado(context, chat.id, aviso.message_id, 30)
    except (BadRequest, Forbidden):
        pass
    await registrar(bot, chat, f"{NOMBRE_ACCION[accion]} · {mencion} (<code>{usuario.id}</code>)\n📝 {escape(motivo)}")
    return True
