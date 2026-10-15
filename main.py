import hashlib
import logging
import os
import re

from google import genai
from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configuración de registros para ver errores en la consola
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Las claves se leen de variables de entorno (en Render: pestaña "Environment").
# Nunca las escribas directamente en el código.
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

ai_client = genai.Client(api_key=GEMINI_API_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! Soy un bot inteligente conectado a una IA. Pregúntame lo que quieras."
    )


async def es_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    miembro = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    return miembro.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)


async def moderar(update: Update, context: ContextTypes.DEFAULT_TYPE, comando: str):
    # Solo los administradores del grupo pueden banear o desbanear
    if not await es_admin(update, context):
        await update.message.reply_text("⛔ Solo los administradores pueden usar este comando.")
        return

    if not update.message.reply_to_message:
        accion = "banear" if comando == ".ban" else "desbanear"
        await update.message.reply_text(f"⚠️ Responde al mensaje de la persona que quieres {accion}.")
        return

    chat_id = update.effective_chat.id
    usuario_id = update.message.reply_to_message.from_user.id

    # 1. Comando .ban (Banea al usuario)
    if comando == ".ban":
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=usuario_id)
            await update.message.reply_text("🚫 Usuario baneado del grupo.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error al banear: {e}")

    # 2. Comando .delban (Desbanea al usuario)
    else:
        try:
            await context.bot.unban_chat_member(chat_id=chat_id, user_id=usuario_id)
            await update.message.reply_text("✅ Usuario desbaneado (ya puede volver a entrar).")
        except Exception as e:
            await update.message.reply_text(f"❌ Error al desbanear: {e}")


def le_hablan_al_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # En chat privado responde siempre
    if update.effective_chat.type == ChatType.PRIVATE:
        return True

    # En grupos solo si lo mencionan (@usuario) o si le responden a un mensaje suyo
    mensaje = update.message
    if f"@{context.bot.username}".lower() in mensaje.text.lower():
        return True
    respuesta_a = mensaje.reply_to_message
    return bool(respuesta_a and respuesta_a.from_user and respuesta_a.from_user.id == context.bot.id)


async def responder_con_ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = re.sub(f"@{context.bot.username}", "", update.message.text, flags=re.IGNORECASE).strip()
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    try:
        response = await ai_client.aio.interactions.create(
            model="gemini-3.8-flash",
            system_instruction="Eres un asistente de Telegram útil, atento y conciso.",
            input=user_text,
        )
        bot_response = response.output_text
        if not bot_response:
            bot_response = "No pude generar una respuesta. Inténtalo de nuevo."
    except Exception as e:
        logging.error(f"Error con Gemini: {e}")
        bot_response = (
            "Lo siento, tuve un problema interno al procesar tu respuesta. "
            "Inténtalo de nuevo."
        )

    await update.message.reply_text(bot_response)


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ignorar si el mensaje no tiene texto
    if not update.message or not update.message.text:
        return

    primera_palabra = (update.message.text.split() or [""])[0].lower()
    es_grupo = update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

    if es_grupo and primera_palabra in (".ban", ".delban"):
        await moderar(update, context, primera_palabra)
    elif le_hablan_al_bot(update, context):
        await responder_con_ia(update, context)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

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
        )
    else:
        print("Danny_PhanBot activo por polling...")
        app.run_polling()


if __name__ == "__main__":
    main()
