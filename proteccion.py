"""Protecciones automáticas que se revisan en cada mensaje del grupo."""
import logging
import re
import time
from collections import defaultdict, deque
from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from telegram import MessageEntity, MessageOriginChannel, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

import db
import ia
from castigos import castigar, programar_borrado, registrar
from permisos import NIVELES, nivel, rol_de

ALFABETOS = {
    "arabe": re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]"),
    "cirilico": re.compile(r"[Ѐ-ӿԀ-ԯ]"),
    "chino": re.compile(r"[㐀-䶿一-鿿豈-﫿]"),
    "latino": re.compile(r"[A-Za-zÀ-ɏ]"),
}
NOMBRE_ALFABETO = {"arabe": "árabe", "cirilico": "cirílico", "chino": "chino", "latino": "latino"}
ENLACE_TELEGRAM = re.compile(r"(?:t\.me|telegram\.me|telegram\.dog)/|tg://", re.IGNORECASE)
NOMBRE_MEDIA = {
    "foto": "Las fotos", "video": "Los videos", "sticker": "Los stickers", "gif": "Los GIFs",
    "audio": "Los audios", "voz": "Las notas de voz", "videonota": "Los videomensajes",
    "documento": "Los archivos", "encuesta": "Las encuestas", "contacto": "Los contactos",
    "ubicacion": "Las ubicaciones", "dado": "Los dados y juegos",
}

_flood: dict[tuple[int, int], deque] = defaultdict(deque)
_canal_vinculado: dict[int, tuple[float, int | None]] = {}


def tipo_media(m) -> str | None:
    if m.photo:
        return "foto"
    if m.animation:
        return "gif"  # Va antes que documento: un GIF también trae document
    if m.video:
        return "video"
    if m.sticker:
        return "sticker"
    if m.audio:
        return "audio"
    if m.voice:
        return "voz"
    if m.video_note:
        return "videonota"
    if m.document:
        return "documento"
    if m.poll:
        return "encuesta"
    if m.contact:
        return "contacto"
    if m.location or m.venue:
        return "ubicacion"
    if m.dice or m.game:
        return "dado"
    return None


def es_de_noche(n: dict) -> bool:
    hora = datetime.now(ZoneInfo(n["zona"])).hour
    inicio, fin = n["inicio"], n["fin"]
    if inicio == fin:
        return False
    return inicio <= hora < fin if inicio < fin else (hora >= inicio or hora < fin)


def tiene_enlace(m) -> bool:
    entidades = list(m.entities) + list(m.caption_entities)
    return any(e.type in (MessageEntity.URL, MessageEntity.TEXT_LINK) for e in entidades) or \
        bool(ENLACE_TELEGRAM.search(m.text or m.caption or ""))


def enlaces_de_telegram(m) -> bool:
    texto = m.text or m.caption or ""
    if ENLACE_TELEGRAM.search(texto):
        return True
    return any(e.type == MessageEntity.TEXT_LINK and ENLACE_TELEGRAM.search(e.url or "")
               for e in list(m.entities) + list(m.caption_entities))


async def canal_vinculado(bot, chat_id: int) -> int | None:
    guardado = _canal_vinculado.get(chat_id)
    if guardado and time.time() - guardado[0] < 3600:
        return guardado[1]
    try:
        vinculado = (await bot.get_chat(chat_id)).linked_chat_id
    except Exception:
        vinculado = None
    _canal_vinculado[chat_id] = (time.time(), vinculado)
    return vinculado


async def _borrar(mensaje):
    try:
        await mensaje.delete()
    except (BadRequest, Forbidden):
        pass


async def revisar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Devuelve True si el mensaje fue borrado o castigado (y no hay que seguir procesándolo)."""
    mensaje, chat, usuario = update.message, update.effective_chat, update.effective_user
    a = db.ajustes(chat.id)

    # Publicaciones que llegan solas del canal vinculado (grupo de discusión)
    if mensaje.is_automatic_forward:
        if a["discusion"]["borrar"]:
            await _borrar(mensaje)
        elif a["discusion"]["desfijar"]:
            try:
                await context.bot.unpin_chat_message(chat.id, mensaje.message_id)
            except (BadRequest, Forbidden):
                pass
        return True

    # Usuarios enmascarados: alguien escribe "como canal"
    if mensaje.sender_chat and mensaje.sender_chat.id != chat.id:
        e = a["enmascarados"]
        if e["accion"] == "off":
            return False
        if e["permitir_vinculado"] and mensaje.sender_chat.id == await canal_vinculado(context.bot, chat.id):
            return False
        await _borrar(mensaje)
        if e["accion"] == "ban":
            try:
                await context.bot.ban_chat_sender_chat(chat.id, mensaje.sender_chat.id)
            except (BadRequest, Forbidden):
                pass
        await registrar(context.bot, chat, f"😶‍🌫️ Mensaje como canal ({mensaje.sender_chat.title}) · {e['accion']}")
        return True

    if mensaje.sender_chat or not usuario or usuario.is_bot:
        return False
    if nivel(await rol_de(update, context)) >= NIVELES["free"]:
        return False  # El staff y los usuarios "libres" no pasan por las protecciones

    # Modo nocturno
    n = a["nocturno"]
    if n["on"] and es_de_noche(n):
        tipo = tipo_media(mensaje)
        if n["modo"] == "silencio" or tipo:
            await _borrar(mensaje)
            hoy = date.today().isoformat()
            if n.get("avisado") != hoy:
                a["nocturno"]["avisado"] = hoy
                db.guardar_ajustes(chat.id, a)
                que = "solo el staff puede escribir" if n["modo"] == "silencio" else "no se permite multimedia"
                aviso = await context.bot.send_message(
                    chat.id, f"🌙 <b>Modo nocturno</b>: hasta las {n['fin']}:00 {que}. ¡Buenas noches, fantasmas!")
                programar_borrado(context, chat.id, aviso.message_id, 300)
            return True

    # Stickers y GIFs bloqueados uno por uno
    media = mensaje.sticker or mensaje.animation
    if media and media.file_unique_id in a["bloqueados"]:
        return await castigar(context, chat, usuario, "borrar", "Ese sticker/GIF está bloqueado aquí", mensaje)

    # Multimedia por tipo
    tipo = tipo_media(mensaje)
    if tipo and a["multimedia"].get(tipo, "off") != "off":
        return await castigar(context, chat, usuario, a["multimedia"][tipo], f"{NOMBRE_MEDIA[tipo]} no están permitidos", mensaje)

    # Reenvíos y bots inline
    if mensaje.forward_origin:
        if isinstance(mensaje.forward_origin, MessageOriginChannel) and a["antispam"]["reenvios_canal"] != "off":
            return await castigar(context, chat, usuario, a["antispam"]["reenvios_canal"], "Reenvío de canal", mensaje)
        if a["bloqueos"]["reenvios"] != "off":
            return await castigar(context, chat, usuario, a["bloqueos"]["reenvios"], "Mensaje reenviado", mensaje)
    if mensaje.via_bot and a["bloqueos"]["via_bot"] != "off":
        return await castigar(context, chat, usuario, a["bloqueos"]["via_bot"], "Mensaje de bot inline", mensaje)

    texto = mensaje.text or mensaje.caption or ""
    minusculas = texto.lower()

    # Palabras prohibidas
    if any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", minusculas) for p in a["palabras"]):
        return await castigar(context, chat, usuario, a["palabras_castigo"], "Palabra prohibida", mensaje)

    # Antispam de enlaces
    if a["antispam"]["telegram"] != "off" and enlaces_de_telegram(mensaje):
        return await castigar(context, chat, usuario, a["antispam"]["telegram"], "Enlaces de Telegram no permitidos", mensaje)
    if a["antispam"]["enlaces"] != "off" and tiene_enlace(mensaje):
        return await castigar(context, chat, usuario, a["antispam"]["enlaces"], "Enlaces no permitidos", mensaje)

    # Alfabetos
    for clave, patron in ALFABETOS.items():
        if a["alfabetos"][clave] != "off" and patron.search(texto):
            return await castigar(context, chat, usuario, a["alfabetos"][clave],
                                  f"Alfabeto {NOMBRE_ALFABETO[clave]} no permitido", mensaje)

    # Longitud
    lon = a["longitud"]
    if mensaje.text and ((lon["max"] and len(texto) > lon["max"]) or (lon["min"] and len(texto.strip()) < lon["min"])):
        motivo = "Mensaje demasiado largo" if lon["max"] and len(texto) > lon["max"] else "Mensaje demasiado corto"
        return await castigar(context, chat, usuario, lon["accion"], motivo, mensaje)

    # Anti-flood
    flood = a["antiflood"]
    if flood["on"]:
        ahora = time.time()
        historial = _flood[(chat.id, usuario.id)]
        historial.append((ahora, mensaje.message_id))
        while historial and ahora - historial[0][0] > flood["segundos"]:
            historial.popleft()
        if len(historial) > flood["mensajes"]:
            ids = [i for _, i in historial]
            historial.clear()
            if flood["borrar"]:
                try:
                    await context.bot.delete_messages(chat.id, ids)
                except (BadRequest, Forbidden):
                    pass
            await castigar(context, chat, usuario, flood["accion"], "Flood (demasiados mensajes seguidos)",
                           None, segundos_mute=600)
            return True

    # Bot Guardián (IA) en los primeros mensajes de cada persona
    g = a["guardian"]
    if g["on"] and len(texto) >= 15 and db.mensajes_de(chat.id, usuario.id) <= g["primeros"]:
        if await ia.es_mensaje_peligroso(texto):
            return await castigar(context, chat, usuario, g["accion"], "El Bot Guardián detectó spam o estafa", mensaje)

    # Antiporno (IA) en fotos y stickers
    if a["antiporno"]["on"] and (mensaje.photo or mensaje.sticker):
        try:
            if mensaje.photo:
                archivo, mime = mensaje.photo[len(mensaje.photo) // 2], "image/jpeg"
            elif mensaje.sticker.is_animated or mensaje.sticker.is_video:
                archivo, mime = mensaje.sticker.thumbnail, "image/webp"
            else:
                archivo, mime = mensaje.sticker, "image/webp"
            if archivo:
                datos = await (await context.bot.get_file(archivo.file_id)).download_as_bytearray()
                if await ia.es_imagen_sexual(bytes(datos), mime):
                    return await castigar(context, chat, usuario, a["antiporno"]["accion"],
                                          "Contenido sexual no permitido", mensaje)
        except Exception as e:
            logging.warning(f"Antiporno no pudo revisar la imagen: {e}")
    return False


async def responder_filtro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Respuestas automáticas por palabra clave (sección Filtros)."""
    a = db.ajustes(update.effective_chat.id)
    texto = (update.message.text or update.message.caption or "").lower()
    if not a["filtros_on"] or not texto:
        return False
    for palabra, respuesta in a["filtros"].items():
        if re.search(rf"(?<!\w){re.escape(palabra)}(?!\w)", texto):
            await update.message.reply_text(escape(respuesta))
            return True
    return False
