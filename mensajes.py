"""Mensajes personalizados como los de Group Help: Texto + Multimedia + Teclado Inline.

Se usan en Bienvenida, Despedida, Reglamento, Captcha y Mensajes recurrentes.
- texto: HTML (se guarda con el formato que el admin escribió en Telegram)
- media: {"tipo": "photo|video|animation|document|sticker|audio|voice", "file_id": "..."} o None
- botones: texto con una fila por línea, botones de la misma fila separados por "&&":
      Mi canal - https://t.me/canal && Reglas - rules
"""
import re
from datetime import datetime
from html import escape

from telegram import InlineKeyboardButton as Boton, InlineKeyboardMarkup as Teclado
from telegram.helpers import mention_html

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

VARIABLES_AYUDA = (
    "<b>Variables:</b> {ID} {NAME} {SURNAME} {NAMESURNAME} {MENTION} {USERNAME} {LANG} "
    "{GROUPNAME} {GROUPUSERNAME} {RULES} {DATE} {TIME} {WEEKDAY}"
)
BOTONES_AYUDA = (
    "<b>Formato de los botones</b> (uno por línea; misma fila con <code>&&</code>):\n"
    "<code>Mi canal - https://t.me/canal</code>\n"
    "<code>Reglas - rules && Web - https://ejemplo.com</code>"
)


def vacio() -> dict:
    return {"texto": "", "media": None, "botones": ""}


def desde_texto_plano(texto: str) -> dict:
    """Para migrar textos guardados antes sin formato."""
    return {"texto": escape(texto or ""), "media": None, "botones": ""}


def configurado(m: dict) -> dict:
    return {"texto": bool(m.get("texto")), "media": bool(m.get("media")), "botones": bool(m.get("botones"))}


def rellenar(html: str, usuario=None, chat=None, reglas_html: str = "") -> str:
    """Reemplaza las variables (estilo Group Help y las antiguas en español)."""
    ahora = datetime.now()
    valores = {}
    if usuario is not None:
        nombre = escape(usuario.first_name or "")
        apellido = escape(usuario.last_name or "")
        valores.update({
            "ID": str(usuario.id), "NAME": nombre, "SURNAME": apellido,
            "NAMESURNAME": escape(usuario.full_name or ""),
            "MENTION": mention_html(usuario.id, usuario.full_name or usuario.first_name),
            "USERNAME": f"@{usuario.username}" if usuario.username else escape(usuario.first_name or ""),
            "LANG": escape(getattr(usuario, "language_code", "") or ""),
        })
        # Variables antiguas de Danny Phantom
        valores.update({"nombre": valores["MENTION"], "usuario": valores["USERNAME"], "id": valores["ID"]})
    if chat is not None:
        valores.update({
            "GROUPNAME": escape(chat.title or ""), "GROUPUSERNAME": f"@{chat.username}" if chat.username else "",
            "grupo": escape(chat.title or ""),
        })
    valores.update({
        "RULES": reglas_html, "DATE": ahora.strftime("%d/%m/%Y"), "TIME": ahora.strftime("%H:%M"),
        "WEEKDAY": DIAS[ahora.weekday()],
    })
    return re.sub(r"\{(\w+)\}", lambda m: valores.get(m.group(1), m.group(0)), html or "")


def leer_botones(texto: str, chat_id: int) -> Teclado | None:
    filas = []
    for linea in (texto or "").splitlines():
        fila = []
        for parte in linea.split("&&"):
            if " - " not in parte:
                continue
            nombre, destino = (x.strip() for x in parte.rsplit(" - ", 1))
            if not nombre or not destino:
                continue
            if destino.lower() == "rules":
                fila.append(Boton(nombre, callback_data=f"rules:{chat_id}"))
            elif re.match(r"^(https?://|tg://|t\.me/)", destino):
                fila.append(Boton(nombre, url=destino if not destino.startswith("t.me/") else f"https://{destino}"))
        if fila:
            filas.append(fila)
    return Teclado(filas) if filas else None


def botones_validos(texto: str) -> bool:
    return leer_botones(texto, 0) is not None


async def enviar(bot, chat_id: int, m: dict, usuario=None, chat=None, reglas_html: str = "", **extra):
    """Envía el mensaje personalizado. Devuelve el Message enviado (o None si está vacío)."""
    texto = rellenar(m.get("texto", ""), usuario, chat, reglas_html)
    teclado = leer_botones(m.get("botones", ""), chat.id if chat else chat_id)
    media = m.get("media")
    if media:
        tipo, archivo = media["tipo"], media["file_id"]
        if tipo == "sticker":
            enviado = await bot.send_sticker(chat_id, archivo, **extra)
            if texto or teclado:
                enviado = await bot.send_message(chat_id, texto or "👆", reply_markup=teclado, **extra)
            return enviado
        metodo = {"photo": bot.send_photo, "video": bot.send_video, "animation": bot.send_animation,
                  "document": bot.send_document, "audio": bot.send_audio, "voice": bot.send_voice}[tipo]
        if len(texto) <= 1024:
            return await metodo(chat_id, archivo, caption=texto or None, reply_markup=teclado, **extra)
        await metodo(chat_id, archivo, **extra)
    if not texto and not teclado:
        return None
    return await bot.send_message(chat_id, texto or "👆", reply_markup=teclado, **extra)


def media_de(mensaje) -> dict | None:
    """Extrae la multimedia de un mensaje que mandó el admin."""
    for tipo in ("animation", "video", "audio", "voice", "document", "sticker"):
        objeto = getattr(mensaje, tipo, None)
        if objeto:
            return {"tipo": tipo, "file_id": objeto.file_id}
    if mensaje.photo:
        return {"tipo": "photo", "file_id": mensaje.photo[-1].file_id}
    return None
