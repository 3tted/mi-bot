import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Configuración de registros para ver errores en la consola
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Pon aquí el token exacto que te dio BotFather
TOKEN = "8874866793:AAEN3q1-0dhGDED0P5Y0C7sIb5cSVYdJiaY"

async def administrar_grupo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ignorar si el mensaje no tiene texto o no viene de un grupo
    if not update.message or not update.message.text:
        return
        
    texto = update.message.text.strip()
    chat_id = update.effective_chat.id

    # 1. Comando .ban (Banea al usuario)
    if texto.startswith(".ban"):
        if update.message.reply_to_message:
            usuario_id = update.message.reply_to_message.from_user.id
            try:
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=usuario_id)
                await update.message.reply_text("🚫 Usuario baneado del grupo.")
            except Exception as e:
                await update.message.reply_text(f"❌ Error al banear: {e}")
        else:
            await update.message.reply_text("⚠️ Responde al mensaje de la persona que quieres banear.")

    # 2. Comando .delban (Desbanea al usuario)
    elif texto.startswith(".delban"):
        if update.message.reply_to_message:
            usuario_id = update.message.reply_to_message.from_user.id
            try:
                await context.bot.unban_chat_member(chat_id=chat_id, user_id=usuario_id)
                await update.message.reply_text("✅ Usuario desbaneado (ya puede volver a entrar).")
            except Exception as e:
                await update.message.reply_text(f"❌ Error al desbanear: {e}")
        else:
            await update.message.reply_text("⚠️ Responde al mensaje de la persona que quieres desbanear.")

def main():
    # Inicializa la aplicación con tu token
    app = Application.builder().token(TOKEN).build()
    
    # Escucha todos los mensajes de texto del grupo
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, administrar_grupo))
    
    print("Danny_PhanBot está activo y patrullando...")
    app.run_polling()

if __name__ == "__main__":
    main()
