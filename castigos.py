"""Castigos automáticos (los usan todas las protecciones) y el canal de registro."""
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from telegram import ChatPermissions
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

import db
import tiempo

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
                   mensaje=None, segundos_mute: int = 3600, segundos_ban: int = 0) -> bool:
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
            duracion = f" por {tiempo.escribir(segundos_mute)}" if segundos_mute else ""
            texto = f"🔇 {mencion} silenciado{duracion}: {escape(motivo)}."
        elif accion == "kick":
            await aplicar_basico(bot, chat.id, usuario.id, "kick")
            texto = f"🌀 {mencion} expulsado: {escape(motivo)}."
        elif accion == "ban":
            await aplicar_basico(bot, chat.id, usuario.id, "ban", segundos_ban or None)
            duracion = f" por {tiempo.escribir(segundos_ban)}" if segundos_ban else ""
            texto = f"👻 {mencion} enviado a la Zona Fantasma{duracion}: {escape(motivo)}."
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


# =====================================================================
# Castigo al estilo Group Help: acción + interruptor "Borrar los Mensajes" + duraciones
# =====================================================================

ACCIONES_GH = ["off", "warn", "kick", "mute", "ban"]
NOMBRE_GH = {"off": "Off", "warn": "Warn", "kick": "Kick", "mute": "Silenciar", "ban": "Ban"}


def nuevo(accion: str = "off", borrar: bool = False, dur_mute: int = 1800, dur_ban: int = 0) -> dict:
    return {"accion": accion, "borrar": borrar, "dur_mute": dur_mute, "dur_ban": dur_ban}


def desde_accion_vieja(accion: str) -> dict:
    """Convierte el formato anterior ("off", "borrar", "warn"...) al nuevo."""
    if accion == "borrar":
        return nuevo("off", True)
    if accion in ACCIONES_GH:
        return nuevo(accion, accion != "off")
    return nuevo()


def normalizar(cfg) -> dict:
    """Acepta también el formato viejo (un texto como "ban") por si quedó algún valor guardado así."""
    return desde_accion_vieja(cfg) if isinstance(cfg, str) else cfg


def describir(cfg: dict) -> str:
    """Texto de "Castigo:" como lo muestra Group Help."""
    cfg = normalizar(cfg)
    accion = cfg["accion"]
    if accion == "off":
        return "Eliminación" if cfg["borrar"] else "Off"
    if accion == "mute":
        return f"Silenciar {tiempo.escribir(cfg['dur_mute'])}" if cfg["dur_mute"] else "Silenciar"
    if accion == "ban":
        return f"Ban {tiempo.escribir(cfg['dur_ban'])}" if cfg["dur_ban"] else "Ban"
    return NOMBRE_GH[accion]


def activo(cfg: dict) -> bool:
    cfg = normalizar(cfg)
    return cfg["accion"] != "off" or cfg["borrar"]


async def aplicar(context: ContextTypes.DEFAULT_TYPE, chat, usuario, cfg: dict, motivo: str, mensaje=None) -> bool:
    """Aplica un castigo con formato nuevo. Devuelve True si hizo algo (borrar o castigar)."""
    cfg = normalizar(cfg)
    if not activo(cfg):
        return False
    if cfg["borrar"] and mensaje is not None:
        try:
            await mensaje.delete()
        except (BadRequest, Forbidden):
            pass
    if cfg["accion"] == "off":
        return True
    return await castigar(context, chat, usuario, cfg["accion"], motivo, None,
                          segundos_mute=cfg["dur_mute"], segundos_ban=cfg["dur_ban"])
