import hashlib
import logging
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from html import escape

from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeChat, \
    ChatPermissions, LinkPreviewOptions, MessageEntity, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, ContextTypes, Defaults, \
    MessageHandler, filters
from telegram.helpers import mention_html

import db
import dueno
import ia
import ui
from comandos import COMANDOS, avisar_staff, borrar_mensaje_luego, ejecutar, rellenar, texto_warns
from permisos import NIVELES, Objetivo, nivel, rol_de, staff

# Configuración de registros para ver errores en la consola
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Las claves se leen de variables de entorno (en Render: pestaña "Environment").
# Nunca las escribas directamente en el código.
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

# "/ban", ".ban" o "/ban@Danny_PhanBot"
PATRON_COMANDO = re.compile(r"^[/.]([A-Za-z0-9_]{1,32})(?:@(\w+))?(?=\s|$)")
ES_GRUPO = (ChatType.GROUP, ChatType.SUPERGROUP)


# =====================================================================
# Filtros automáticos: stickers bloqueados, palabras, enlaces y flood
# =====================================================================

_flood: dict[tuple[int, int], deque] = defaultdict(deque)


def tiene_enlace(mensaje) -> bool:
    entidades = list(mensaje.entities) + list(mensaje.caption_entities)
    if any(e.type in (MessageEntity.URL, MessageEntity.TEXT_LINK) for e in entidades):
        return True
    return "t.me/" in (mensaje.text or mensaje.caption or "").lower()


async def avisar_y_borrar(context, chat_id: int, texto: str):
    aviso = await context.bot.send_message(chat_id, texto)
    context.job_queue.run_once(borrar_mensaje_luego, 15, data=(chat_id, aviso.message_id))


async def revisar_filtros(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Devuelve True si el mensaje fue eliminado o castigado."""
    mensaje, chat, usuario = update.message, update.effective_chat, update.effective_user
    if mensaje.sender_chat or not usuario or usuario.is_bot:
        return False
    if nivel(await rol_de(update, context)) >= NIVELES["free"]:
        return False  # El staff y los usuarios "libres" no pasan por los filtros

    a = db.ajustes(chat.id)
    texto = (mensaje.text or mensaje.caption or "").lower()
    media = mensaje.sticker or mensaje.animation
    motivo = None
    if media and media.file_unique_id in a["bloqueados"]:
        motivo = "🚫 Ese sticker/GIF está bloqueado aquí"
    elif any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", texto) for p in a["palabras"]):
        motivo = "🤐 Esa palabra está prohibida aquí"
    elif a["antilink"] and tiene_enlace(mensaje):
        motivo = "🔗 No se permiten enlaces"
    if motivo:
        try:
            await mensaje.delete()
            await avisar_y_borrar(context, chat.id, f"{motivo}, {mention_html(usuario.id, usuario.first_name)} 👻")
        except (BadRequest, Forbidden):
            pass
        return True

    flood = a["antiflood"]
    if flood["on"]:
        ahora = time.time()
        historial = _flood[(chat.id, usuario.id)]
        historial.append(ahora)
        while historial and ahora - historial[0] > flood["segundos"]:
            historial.popleft()
        if len(historial) > flood["mensajes"]:
            historial.clear()
            try:
                hasta = datetime.now(timezone.utc) + timedelta(minutes=10)
                await context.bot.restrict_chat_member(chat.id, usuario.id, ChatPermissions.no_permissions(),
                                                       until_date=hasta)
                await context.bot.send_message(
                    chat.id,
                    f"🌊 ¡Demasiado ectoplasma! {mention_html(usuario.id, usuario.first_name)} "
                    "queda silenciado 10 minutos por flood.",
                )
            except (BadRequest, Forbidden):
                pass
            return True
    return False


# =====================================================================
# Mensajes
# =====================================================================

def le_hablan_al_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat, mensaje = update.effective_chat, update.message
    if chat.type == ChatType.PRIVATE:
        return True
    if not db.ajustes(chat.id)["ia"]:
        return False
    if f"@{context.bot.username}".lower() in (mensaje.text or "").lower():
        return True
    respuesta = mensaje.reply_to_message
    return bool(respuesta and respuesta.from_user and respuesta.from_user.id == context.bot.id)


async def procesar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje, chat, usuario = update.message, update.effective_chat, update.effective_user
    if not mensaje:
        return
    if usuario and not usuario.is_bot:
        db.recordar_usuario(usuario.id, usuario.username, usuario.full_name)

    if chat.type in ES_GRUPO:
        db.tocar_grupo(chat.id, chat.title, chat.username)
        if usuario and not usuario.is_bot and not mensaje.sender_chat:
            db.contar_mensaje(chat.id, usuario.id)
        if await revisar_filtros(update, context):
            return
    elif chat.type == ChatType.PRIVATE and usuario:
        db.registrar_privado(usuario.id)

    texto = mensaje.text or mensaje.caption or ""
    m = PATRON_COMANDO.match(texto)
    if m:
        nombre, destino = m.group(1).lower(), m.group(2)
        if destino and destino.lower() != context.bot.username.lower():
            return  # Es un comando para otro bot
        resto = texto[m.end():].strip()
        if nombre in COMANDOS:
            await ejecutar(update, context, nombre, resto)
            return
        if chat.type in ES_GRUPO:
            alias = db.ajustes(chat.id)["alias"].get(nombre)
            if alias:
                await mensaje.reply_text(escape(alias))
                return

    if not mensaje.text:
        return
    if chat.type in ES_GRUPO and "@admin" in texto.lower():
        await avisar_staff(update, context)
    elif le_hablan_al_bot(update, context):
        pregunta = re.sub(f"@{context.bot.username}", "", texto, flags=re.IGNORECASE).strip()
        if not pregunta:
            return
        await context.bot.send_chat_action(chat.id, "typing")
        await mensaje.reply_text(await ia.preguntar(pregunta), parse_mode=None)


# =====================================================================
# Entradas y salidas (bienvenida y captcha)
# =====================================================================

async def nuevos_miembros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje, chat = update.message, update.effective_chat
    a = db.ajustes(chat.id)
    for nuevo in mensaje.new_chat_members:
        if nuevo.id == context.bot.id:
            await mensaje.reply_text(ui.tarjeta(
                "¡Llegó Danny Phantom! 👻",
                "Gracias por traerme, mano. Hazme <b>administrador</b> con permiso para borrar mensajes, "
                "restringir y fijar, y usa /settings para configurarme. Mis comandos: /help",
            ))
            continue
        if nuevo.is_bot:
            continue
        db.recordar_usuario(nuevo.id, nuevo.username, nuevo.full_name)
        if a["captcha"]["on"]:
            try:
                await context.bot.restrict_chat_member(chat.id, nuevo.id, ChatPermissions.no_permissions())
                aviso = await context.bot.send_message(
                    chat.id,
                    f"🧩 {mention_html(nuevo.id, nuevo.first_name)}, demuestra que no eres un fantasma malo: "
                    f"toca el botón en {a['captcha']['minutos']} minutos o te saco por el portal.",
                    reply_markup=ui.teclado_captcha(nuevo.id),
                )
                context.job_queue.run_once(
                    captcha_vencido, a["captcha"]["minutos"] * 60,
                    data=(chat.id, nuevo.id, aviso.message_id), name=f"cap:{chat.id}:{nuevo.id}",
                )
                continue
            except (BadRequest, Forbidden):
                pass  # Sin permisos para restringir: solo damos la bienvenida
        if a["bienvenida"]["on"]:
            await context.bot.send_message(chat.id, rellenar(a["bienvenida"]["texto"], nuevo, chat))


async def captcha_vencido(context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id, mensaje_id = context.job.data
    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        await context.bot.edit_message_text(
            "🌀 No pasó el captcha a tiempo y salió por el portal fantasma.", chat_id=chat_id, message_id=mensaje_id
        )
    except (BadRequest, Forbidden):
        pass


async def miembro_salio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, salio = update.effective_chat, update.message.left_chat_member
    if salio.id == context.bot.id or salio.is_bot:
        return
    a = db.ajustes(chat.id)
    if a["despedida"]["on"]:
        await context.bot.send_message(chat.id, rellenar(a["despedida"]["texto"], salio, chat))


# =====================================================================
# Botones
# =====================================================================

async def es_admin_de(context, chat_id: int, user_id: int) -> bool:
    return nivel((await staff(context.bot, chat_id)).get(user_id)) >= NIVELES["admin"]


async def botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tipo, *partes = q.data.split(":")
    privado = q.message.chat.type == ChatType.PRIVATE

    if tipo == "own":
        await dueno.botones(update, context, partes)

    elif tipo == "menu":
        destino = partes[0]
        if destino == "inicio":
            await q.edit_message_text(ui.texto_inicio(q.from_user.first_name),
                                      reply_markup=ui.teclado_inicio(context.bot.username))
        elif destino == "ayuda":
            await q.edit_message_text(ui.texto_ayuda_indice(), reply_markup=ui.teclado_ayuda_indice(volver=privado))
        elif destino == "ia":
            await q.edit_message_text(ui.TEXTO_IA, reply_markup=ui.teclado_volver())
        elif destino == "acerca":
            await q.edit_message_text(ui.TEXTO_ACERCA, reply_markup=ui.teclado_volver())
        await q.answer()

    elif tipo == "ayuda":
        await q.edit_message_text(ui.texto_ayuda(partes[0]), reply_markup=ui.teclado_volver("menu:ayuda"))
        await q.answer()

    elif tipo == "cerrar":
        await q.message.delete()
        await q.answer()

    elif tipo == "cfg":
        chat_id, accion = int(partes[0]), partes[1]
        if not await es_admin_de(context, chat_id, q.from_user.id):
            await q.answer("⛔ Solo los administradores pueden cambiar los ajustes.", show_alert=True)
            return
        a = db.ajustes(chat_id)
        if accion in ("bienvenida", "despedida", "captcha", "antiflood"):
            a[accion]["on"] = not a[accion]["on"]
        elif accion in ("antilink", "ia"):
            a[accion] = not a[accion]
        elif accion in ("flood-", "flood+"):
            a["antiflood"]["mensajes"] = max(2, min(50, a["antiflood"]["mensajes"] + (1 if accion == "flood+" else -1)))
        elif accion in ("warn-", "warn+"):
            a["warn_limite"] = max(1, min(10, a["warn_limite"] + (1 if accion == "warn+" else -1)))
        elif accion == "castigo":
            castigos = ui.CASTIGOS
            a["warn_castigo"] = castigos[(castigos.index(a["warn_castigo"]) + 1) % len(castigos)]
        else:
            await q.answer()
            return
        db.guardar_ajustes(chat_id, a)
        titulo = (await context.bot.get_chat(chat_id)).title
        await q.edit_message_text(ui.texto_ajustes(titulo, a), reply_markup=ui.teclado_ajustes(chat_id, a))
        await q.answer("✅ Guardado")

    elif tipo == "cap":
        user_id = int(partes[0])
        chat = q.message.chat
        if q.from_user.id != user_id:
            await q.answer("👻 Este botón no es para ti.", show_alert=True)
            return
        for trabajo in context.job_queue.get_jobs_by_name(f"cap:{chat.id}:{user_id}"):
            trabajo.schedule_removal()
        permisos = (await context.bot.get_chat(chat.id)).permissions or ChatPermissions.all_permissions()
        await context.bot.restrict_chat_member(chat.id, user_id, permisos)
        await q.message.delete()
        await q.answer("💚 ¡Verificado! Bienvenid@")
        a = db.ajustes(chat.id)
        if a["bienvenida"]["on"]:
            await context.bot.send_message(chat.id, rellenar(a["bienvenida"]["texto"], q.from_user, chat))

    elif tipo == "warn":
        chat_id, user_id, op = int(partes[0]), int(partes[1]), partes[2]
        if nivel((await staff(context.bot, chat_id)).get(q.from_user.id)) < NIVELES["mod"]:
            await q.answer("⛔ Solo moderadores o superiores.", show_alert=True)
            return
        actuales = db.miembro(chat_id, user_id)["warns"]
        nuevas = {"+": actuales + 1, "-": max(0, actuales - 1), "0": 0}[op]
        db.actualizar_miembro(chat_id, user_id, warns=nuevas)
        obj = Objetivo(user_id, db.nombre_usuario(user_id) or str(user_id))
        await q.edit_message_text(texto_warns(chat_id, obj), reply_markup=ui.teclado_warns(chat_id, user_id))
        await q.answer("✅ Actualizado")

    elif tipo == "juego":
        await context.bot.send_dice(q.message.chat.id, emoji=ui.JUEGOS[int(partes[0])])
        await q.answer()

    else:
        await q.answer()


# =====================================================================
# Arranque
# =====================================================================

async def error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error("Error procesando una actualización", exc_info=context.error)
    if isinstance(update, Update) and update.message and isinstance(context.error, (BadRequest, Forbidden)):
        try:
            await update.message.reply_text(
                f"⚠️ Telegram no me dejó hacerlo: <i>{escape(str(context.error))}</i>\n"
                "¿Soy administrador con los permisos necesarios?"
            )
        except Exception:
            pass


async def guardar_conteo(context: ContextTypes.DEFAULT_TYPE):
    db.guardar_conteo_mensajes()


async def al_iniciar(app: Application):
    privados = [
        BotCommand("start", "👻 Menú principal"), BotCommand("help", "📜 Comandos"),
        BotCommand("ia", "🤖 Pregúntale a la IA"), BotCommand("traducir", "🌐 Traducir un mensaje"),
        BotCommand("game", "🎮 Minijuegos"),
    ]
    grupos = [
        BotCommand("help", "📜 Comandos"), BotCommand("rules", "📜 Reglas"), BotCommand("staff", "👥 Staff"),
        BotCommand("report", "🚨 Avisar al staff"), BotCommand("me", "👤 Mi información"),
        BotCommand("ia", "🤖 Pregúntale a la IA"), BotCommand("ban", "👻 Enviar a la Zona Fantasma"),
        BotCommand("unban", "✨ Regresar de la Zona Fantasma"), BotCommand("kick", "🌀 Expulsar"),
        BotCommand("mute", "🔇 Silenciar"), BotCommand("unmute", "🗣️ Quitar silencio"),
        BotCommand("warn", "⚠️ Advertir"), BotCommand("unwarn", "💚 Quitar advertencia"),
        BotCommand("warns", "⚠️ Ver advertencias"), BotCommand("info", "👤 Info de usuario"),
        BotCommand("del", "🗑️ Borrar mensaje"), BotCommand("purge", "🧹 Borrar varios"),
        BotCommand("pin", "📌 Fijar"), BotCommand("settings", "⚙️ Ajustes"), BotCommand("top10", "📊 Más activos"),
    ]
    await app.bot.set_my_commands(privados, scope=BotCommandScopeAllPrivateChats())
    await app.bot.set_my_commands(grupos, scope=BotCommandScopeAllGroupChats())
    if dueno.id_dueno():
        # El dueño ve además los comandos del panel en su chat privado
        panel = [BotCommand("panel", "🔐 Panel del dueño"), BotCommand("grupos", "📋 Mis grupos")]
        try:
            await app.bot.set_my_commands(privados + panel, scope=BotCommandScopeChat(dueno.id_dueno()))
        except Exception as e:
            logging.warning(f"No pude poner los comandos del dueño (¿ya inició el chat conmigo?): {e}")
    app.job_queue.run_repeating(guardar_conteo, interval=60, first=60)


async def al_cerrar(app: Application):
    db.guardar_conteo_mensajes()


def main():
    defaults = Defaults(parse_mode=ParseMode.HTML, link_preview_options=LinkPreviewOptions(is_disabled=True))
    app = (
        Application.builder().token(TELEGRAM_TOKEN).defaults(defaults)
        .post_init(al_iniciar).post_shutdown(al_cerrar).build()
    )
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, nuevos_miembros))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, miembro_salio))
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, dueno.grupo_migrado))
    app.add_handler(ChatMemberHandler(dueno.cambio_en_el_bot, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(botones))
    app.add_handler(MessageHandler(filters.UpdateType.MESSAGE & ~filters.StatusUpdate.ALL, procesar))
    app.add_error_handler(error)

    # Render define RENDER_EXTERNAL_URL en los Web Services: ahí usamos webhook,
    # así Telegram "despierta" al servidor gratuito cuando llega un mensaje.
    # En tu PC (sin esa variable) usa polling como siempre.
    url_publica = os.environ.get("RENDER_EXTERNAL_URL")
    if url_publica:
        print(f"Danny_PhanBot activo por webhook en {url_publica}")
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 10000)),
            url_path="webhook",
            webhook_url=f"{url_publica}/webhook",
            secret_token=hashlib.sha256(TELEGRAM_TOKEN.encode()).hexdigest(),
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        print("Danny_PhanBot activo por polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
