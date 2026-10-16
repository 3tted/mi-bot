"""Comandos de las secciones nuevas: filtros, recurrentes, mágicos, registro, enlace, temas y etiqueta."""
import random
import re
import time
from html import escape

from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

import db
import ui
from comandos import COMANDOS, Peticion, comando
from permisos import NIVELES, Aviso, duracion, nivel, rol_de, texto_duracion


# ---------- Filtros (respuestas automáticas) ----------

@comando("filtro", "filter", rol="admin")
async def filtro(p: Peticion):
    m = re.match(r'^"([^"]+)"\s+(.+)$', p.texto, re.S) or re.match(r"^(\S+)\s+(.+)$", p.texto, re.S)
    if not m:
        raise Aviso('✏️ Uso: <code>/filtro palabra respuesta</code> o <code>/filtro "varias palabras" respuesta</code>')
    palabra, respuesta = m.group(1).strip().lower(), m.group(2).strip()
    a = db.ajustes(p.chat.id)
    a["filtros"][palabra] = respuesta
    db.guardar_ajustes(p.chat.id, a)
    await p.responder(f"🔦 Cuando alguien diga <code>{escape(palabra)}</code>, responderé eso.")


@comando("unfiltro", "unfilter", rol="admin")
async def unfiltro(p: Peticion):
    palabra = p.texto.strip().strip('"').lower()
    a = db.ajustes(p.chat.id)
    if a["filtros"].pop(palabra, None) is None:
        raise Aviso("🔍 Ese filtro no existe. Mira la lista con /filtros")
    db.guardar_ajustes(p.chat.id, a)
    await p.responder(f"🗑️ Quité el filtro <code>{escape(palabra)}</code>.")


@comando("filtros", "filters", rol="admin")
async def filtros(p: Peticion):
    lista = db.ajustes(p.chat.id)["filtros"]
    if not lista:
        raise Aviso("📭 No hay filtros. Crea uno con /filtro palabra respuesta")
    await p.responder(ui.tarjeta("🔦 Filtros", "\n".join(f"• <code>{escape(k)}</code>" for k in sorted(lista))))


# ---------- Mensajes recurrentes ----------

async def enviar_recurrente(context: ContextTypes.DEFAULT_TYPE):
    chat_id, rid = context.job.data
    a = db.ajustes(chat_id)
    r = next((x for x in a["recurrentes"] if x["id"] == rid), None)
    if not r:
        context.job.schedule_removal()
        return
    try:
        tema = a["temas"]["avisos"]
        extra = {"message_thread_id": tema} if tema else {}
        await context.bot.send_message(chat_id, escape(r["texto"]), **extra)
    except Forbidden:
        context.job.schedule_removal()  # Ya no estoy en ese grupo
    except BadRequest:
        pass


def programar_recurrente(job_queue, chat_id: int, r: dict):
    nombre = f"rec:{chat_id}:{r['id']}"
    for trabajo in job_queue.get_jobs_by_name(nombre):
        trabajo.schedule_removal()
    job_queue.run_repeating(enviar_recurrente, interval=r["segundos"], first=r["segundos"],
                            data=(chat_id, r["id"]), name=nombre)


def programar_todos(job_queue):
    for chat_id in db.chats_con_ajustes():
        for r in db.ajustes(chat_id)["recurrentes"]:
            programar_recurrente(job_queue, chat_id, r)


@comando("recurrente", "recurring", rol="admin")
async def recurrente(p: Peticion):
    segundos = duracion(p.args[0]) if p.args else None
    texto = p.texto[len(p.args[0]):].strip() if p.args else ""
    if not segundos or not texto:
        raise Aviso("✏️ Uso: <code>/recurrente 6h texto</code> (también 30m, 1d…). Mínimo cada 10 minutos.")
    if segundos < 600:
        raise Aviso("⏱️ Lo mínimo es cada 10 minutos.")
    a = db.ajustes(p.chat.id)
    if len(a["recurrentes"]) >= 10:
        raise Aviso("✋ Máximo 10 mensajes recurrentes por grupo.")
    nuevo = {"id": max((r["id"] for r in a["recurrentes"]), default=0) + 1, "segundos": segundos, "texto": texto}
    a["recurrentes"].append(nuevo)
    db.guardar_ajustes(p.chat.id, a)
    programar_recurrente(p.context.job_queue, p.chat.id, nuevo)
    await p.responder(f"🕐 Listo: enviaré ese mensaje cada <b>{texto_duracion(segundos)}</b>.")


@comando("recurrentes", rol="admin")
async def recurrentes(p: Peticion):
    lista = db.ajustes(p.chat.id)["recurrentes"]
    if not lista:
        raise Aviso("📭 No hay mensajes recurrentes. Crea uno con /recurrente 6h texto")
    lineas = [f"{i}. cada {texto_duracion(r['segundos'])}: <i>{escape(r['texto'][:80])}</i>" for i, r in enumerate(lista, 1)]
    await p.responder(ui.tarjeta("🕐 Mensajes recurrentes", "\n".join(lineas) + "\n\nQuita uno con /unrecurrente número"))


@comando("unrecurrente", rol="admin")
async def unrecurrente(p: Peticion):
    a = db.ajustes(p.chat.id)
    if not p.args or not p.args[0].isdigit() or not 1 <= int(p.args[0]) <= len(a["recurrentes"]):
        raise Aviso("✏️ Uso: /unrecurrente número (míralos con /recurrentes)")
    quitado = a["recurrentes"].pop(int(p.args[0]) - 1)
    db.guardar_ajustes(p.chat.id, a)
    for trabajo in p.context.job_queue.get_jobs_by_name(f"rec:{p.chat.id}:{quitado['id']}"):
        trabajo.schedule_removal()
    await p.responder("🗑️ Mensaje recurrente eliminado.")


# ---------- Stickers y GIFs mágicos ----------

@comando("magic", "magico", rol="admin")
async def magic(p: Peticion):
    respondido = p.respondido()
    media = respondido and (respondido.sticker or respondido.animation)
    nombre = p.args[0].lower().lstrip("/.") if p.args else ""
    if not media or not nombre:
        raise Aviso("🎭 Responde a un sticker o GIF con <code>/magic ban</code> (o el comando que quieras).")
    if nombre not in COMANDOS or nombre in ("magic", "magico", "unmagic"):
        raise Aviso(f"🔍 /{escape(nombre)} no es un comando del bot.")
    a = db.ajustes(p.chat.id)
    a["magicos"][media.file_unique_id] = nombre
    db.guardar_ajustes(p.chat.id, a)
    await p.responder(f"✨ ¡Listo! Ese {'sticker' if respondido.sticker else 'GIF'} ahora hace <code>/{nombre}</code> "
                      "cuando lo envía el staff respondiendo a alguien.")


@comando("unmagic", rol="admin")
async def unmagic(p: Peticion):
    respondido = p.respondido()
    media = respondido and (respondido.sticker or respondido.animation)
    a = db.ajustes(p.chat.id)
    if not media or a["magicos"].pop(media.file_unique_id, None) is None:
        raise Aviso("🎭 Responde al sticker o GIF mágico que quieres quitar.")
    db.guardar_ajustes(p.chat.id, a)
    await p.responder("🧹 Ya no es mágico.")


# ---------- Canal de registro, enlace y temas ----------

@comando("setlog", rol="cofounder")
async def setlog(p: Peticion):
    a = db.ajustes(p.chat.id)
    if p.args and p.args[0].lower() == "off":
        a["registro"] = {"on": False, "chat_id": None}
        db.guardar_ajustes(p.chat.id, a)
        await p.responder("🔍 Canal de registro desactivado.")
        return
    if not p.args or not p.args[0].lstrip("-").isdigit():
        raise Aviso("✏️ Uso: <code>/setlog ID_del_canal</code>. Usa /id dentro del canal o grupo para verlo.")
    destino = int(p.args[0])
    try:
        await p.bot.send_message(destino, f"🔍 Este chat ahora es el registro de <b>{escape(p.chat.title)}</b>.")
    except (BadRequest, Forbidden):
        raise Aviso("❌ No puedo escribir ahí. Añádeme como admin a ese canal o grupo y vuelve a intentarlo.")
    a["registro"] = {"on": True, "chat_id": destino}
    db.guardar_ajustes(p.chat.id, a)
    await p.responder("🔍 ¡Listo! Registraré ahí las sanciones del grupo.")


@comando("setlink", rol="admin")
async def setlink(p: Peticion):
    a = db.ajustes(p.chat.id)
    valor = p.texto.strip()
    if valor.lower() == "off":
        a["enlace"]["personalizado"] = ""
    elif re.match(r"^(https?://|t\.me/)\S+$", valor):
        a["enlace"]["personalizado"] = valor if valor.startswith("http") else f"https://{valor}"
    else:
        raise Aviso("✏️ Uso: <code>/setlink https://t.me/...</code> o <code>/setlink off</code>")
    db.guardar_ajustes(p.chat.id, a)
    await p.responder("🔗 Enlace actualizado. Se ve con /link")


@comando("settopic", "settema", rol="admin")
async def settopic(p: Peticion):
    a = db.ajustes(p.chat.id)
    if p.args and p.args[0].lower() == "off":
        a["temas"]["avisos"] = None
        texto = "🗂️ Bienvenidas y avisos volverán al tema general."
    elif p.msg.is_topic_message and p.msg.message_thread_id:
        a["temas"]["avisos"] = p.msg.message_thread_id
        texto = "🗂️ ¡Listo! Mandaré las bienvenidas y avisos a este tema."
    else:
        raise Aviso("🗂️ Escribe /settopic dentro del tema que quieres usar (solo en grupos con temas).")
    db.guardar_ajustes(p.chat.id, a)
    await p.responder(texto)


# ---------- Etiqueta (mencionar a todos) ----------

async def etiquetar_todos(update, context: ContextTypes.DEFAULT_TYPE, texto: str):
    chat = update.effective_chat
    a = db.ajustes(chat.id)["etiqueta"]
    if not a["on"]:
        return
    if a["quien"] == "admins" and nivel(await rol_de(update, context)) < NIVELES["admin"]:
        return
    ultimo = context.chat_data.get("tagall", 0)
    if time.time() - ultimo < 300:
        raise Aviso("⏳ Ya llamé a todos hace poco. Espera unos minutos.")
    autor = update.effective_user.id if update.effective_user else None
    ids = [i for i in db.ids_miembros(chat.id) if i not in (context.bot.id, autor)][:100]
    if not ids:
        raise Aviso("👻 Todavía no conozco a nadie aquí para etiquetar.")
    context.chat_data["tagall"] = time.time()
    encabezado = f"📣 {escape(texto)}" if texto else "📣 ¡Atención, fantasmas!"
    for i in range(0, len(ids), 5):
        menciones = " ".join(mention_html(uid, db.nombre_usuario(uid) or "👻") for uid in ids[i:i + 5])
        await context.bot.send_message(chat.id, (encabezado + "\n" if i == 0 else "") + menciones)


@comando("tagall", "all", "todos")
async def tagall(p: Peticion):
    await etiquetar_todos(p.update, p.context, p.texto)


# ---------- Stickers (packs que el bot va mandando) ----------

_cache_packs: dict[str, tuple[float, list]] = {}


def nombre_de_pack(texto: str) -> str:
    """Acepta 'NombreDelPack' o el enlace https://t.me/addstickers/NombreDelPack."""
    texto = texto.strip().rstrip("/")
    m = re.search(r"(?:t\.me|telegram\.me)/addstickers/([A-Za-z0-9_]+)", texto)
    return m.group(1) if m else texto


async def stickers_de(bot, pack: str) -> list:
    guardado = _cache_packs.get(pack)
    if guardado and time.time() - guardado[0] < 3600:
        return guardado[1]
    lista = list((await bot.get_sticker_set(pack)).stickers)
    _cache_packs[pack] = (time.time(), lista)
    return lista


async def sticker_al_azar(bot, chat_id: int, emoji: str | None = None):
    candidatos = []
    for pack in db.ajustes(chat_id)["stickers"]["packs"]:
        try:
            candidatos += await stickers_de(bot, pack)
        except (BadRequest, Forbidden):
            continue  # El pack ya no existe
    if emoji:
        con_emoji = [s for s in candidatos if s.emoji and emoji in s.emoji]
        candidatos = con_emoji or candidatos
    return random.choice(candidatos) if candidatos else None


@comando("stickerpack", "addpack", solo_grupo=False)
async def stickerpack(p: Peticion):
    if p.chat.type != "private" and nivel(await rol_de(p.update, p.context)) < NIVELES["admin"]:
        return
    if not p.texto:
        raise Aviso("🐒 Uso: <code>/stickerpack NombreDelPack</code> o el enlace "
                    "<code>https://t.me/addstickers/NombreDelPack</code>")
    pack = nombre_de_pack(p.texto)
    try:
        conjunto = await p.bot.get_sticker_set(pack)
    except BadRequest:
        raise Aviso(f"🔍 No encontré el pack <code>{escape(pack)}</code>. Revisa el nombre: es lo que va "
                    "después de t.me/addstickers/")
    a = db.ajustes(p.chat.id)
    if pack in a["stickers"]["packs"]:
        raise Aviso("🐒 Ese pack ya estaba agregado.")
    if len(a["stickers"]["packs"]) >= 10:
        raise Aviso("✋ Máximo 10 packs. Quita uno con /delpack nombre")
    a["stickers"]["packs"].append(pack)
    db.guardar_ajustes(p.chat.id, a)
    _cache_packs[pack] = (time.time(), list(conjunto.stickers))
    await p.responder(f"🐒 Agregué <b>{escape(conjunto.title)}</b> ({len(conjunto.stickers)} stickers). "
                      "Pídelos con /chango")


@comando("delpack", solo_grupo=False)
async def delpack(p: Peticion):
    if p.chat.type != "private" and nivel(await rol_de(p.update, p.context)) < NIVELES["admin"]:
        return
    a = db.ajustes(p.chat.id)
    pack = nombre_de_pack(p.texto)
    if pack not in a["stickers"]["packs"]:
        raise Aviso("🔍 Ese pack no está agregado. Míralos con /packs")
    a["stickers"]["packs"].remove(pack)
    db.guardar_ajustes(p.chat.id, a)
    await p.responder(f"🗑️ Quité <code>{escape(pack)}</code>.")


@comando("packs", solo_grupo=False)
async def packs(p: Peticion):
    lista = db.ajustes(p.chat.id)["stickers"]["packs"]
    if not lista:
        raise Aviso("📭 No hay packs de stickers. Agrega uno con /stickerpack nombre")
    await p.responder(ui.tarjeta("🐒 Packs de stickers", "\n".join(
        f"• <a href=\"https://t.me/addstickers/{x}\">{escape(x)}</a>" for x in lista)))


@comando("chango", "sticker", "mono", solo_grupo=False)
async def chango(p: Peticion):
    if not db.ajustes(p.chat.id)["stickers"]["packs"]:
        raise Aviso("🐒 Todavía no tengo stickers. Un admin puede agregar un pack con /stickerpack nombre")
    sticker = await sticker_al_azar(p.bot, p.chat.id, p.args[0] if p.args else None)
    if sticker:
        await p.msg.reply_sticker(sticker.file_id)


async def sticker_automatico(update, context: ContextTypes.DEFAULT_TYPE):
    """Modo automático: de vez en cuando respondo un mensaje con un sticker."""
    config = db.ajustes(update.effective_chat.id)["stickers"]
    if not config["auto"] or not config["packs"] or random.random() * 100 >= config["auto"]:
        return
    sticker = await sticker_al_azar(context.bot, update.effective_chat.id)
    if sticker:
        await update.message.reply_sticker(sticker.file_id)
