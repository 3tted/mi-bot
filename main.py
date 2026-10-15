import hashlib
import logging
import os
import re
from html import escape

from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeChat, \
    LinkPreviewOptions, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, CallbackQueryHandler, ChatJoinRequestHandler, ChatMemberHandler, \
    ContextTypes, Defaults, MessageHandler, filters

import ajustes_menu
import db
import dueno
import entradas
import extras
import ia
import proteccion
import ui
from comandos import COMANDOS, avisar_staff, ejecutar, texto_warns
from permisos import NIVELES, Aviso, Objetivo, es_staff, nivel, rol_de, staff

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

    en_grupo = chat.type in ES_GRUPO
    if en_grupo:
        db.tocar_grupo(chat.id, chat.title, chat.username)
        if usuario and not usuario.is_bot and not mensaje.sender_chat:
            db.contar_mensaje(chat.id, usuario.id)
        if await proteccion.revisar(update, context):
            return
    elif chat.type == ChatType.PRIVATE and usuario:
        db.registrar_privado(usuario.id)

    # Stickers y GIFs mágicos: el staff los envía y se ejecuta un comando
    media = mensaje.sticker or mensaje.animation
    if en_grupo and media:
        magico = db.ajustes(chat.id)["magicos"].get(media.file_unique_id)
        if magico in COMANDOS and es_staff(await rol_de(update, context)):
            await ejecutar(update, context, magico, "")
            return

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
        if en_grupo:
            a = db.ajustes(chat.id)
            alias = a["alias"].get(nombre)
            if alias:
                if not a["alias_solo_admins"] or es_staff(await rol_de(update, context)):
                    await mensaje.reply_text(escape(alias))
                return

    if not mensaje.text:
        return
    minusculas = texto.lower()
    if en_grupo and re.search(r"(?<!\w)@all(?!\w)", minusculas):
        try:
            await extras.etiquetar_todos(update, context, re.sub(r"(?i)@all", "", texto).strip())
        except Aviso as aviso:
            await mensaje.reply_text(str(aviso))
    elif en_grupo and "@admin" in minusculas:
        await avisar_staff(update, context)
    elif le_hablan_al_bot(update, context):
        pregunta = re.sub(f"@{context.bot.username}", "", texto, flags=re.IGNORECASE).strip()
        if not pregunta:
            return
        await context.bot.send_chat_action(chat.id, "typing")
        await mensaje.reply_text(await ia.preguntar(pregunta), parse_mode=None)
    elif en_grupo:
        await proteccion.responder_filtro(update, context)


# =====================================================================
# Botones
# =====================================================================

async def botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tipo, *partes = q.data.split(":")
    privado = q.message.chat.type == ChatType.PRIVATE

    if tipo == "own":
        await dueno.botones(update, context, partes)

    elif tipo == "cfg":
        await ajustes_menu.manejar(update, context, partes)

    elif tipo == "cap":
        await entradas.boton_captcha(update, context, partes)

    elif tipo == "apr":
        await entradas.boton_aprobacion(update, context, partes)

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
        BotCommand("game", "🎮 Minijuegos"), BotCommand("id", "🆔 Ver tu ID"),
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
    extras.programar_todos(app.job_queue)


async def al_cerrar(app: Application):
    db.guardar_conteo_mensajes()


def main():
    defaults = Defaults(parse_mode=ParseMode.HTML, link_preview_options=LinkPreviewOptions(is_disabled=True))
    app = (
        Application.builder().token(TELEGRAM_TOKEN).defaults(defaults)
        .post_init(al_iniciar).post_shutdown(al_cerrar).build()
    )
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, entradas.nuevos_miembros))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, entradas.miembro_salio))
    app.add_handler(MessageHandler(filters.StatusUpdate.PINNED_MESSAGE, entradas.mensaje_fijado))
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, dueno.grupo_migrado))
    app.add_handler(ChatMemberHandler(dueno.cambio_en_el_bot, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatJoinRequestHandler(entradas.solicitud_union))
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
