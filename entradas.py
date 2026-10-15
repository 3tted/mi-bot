"""Entradas y salidas: bienvenida, captcha, reglas al entrar, bots, solicitudes de unión y avisos de servicio."""
import random
from html import escape

from telegram import ChatPermissions, InlineKeyboardButton as Boton, InlineKeyboardMarkup as Teclado, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

import db
import ui
from castigos import aplicar_basico, castigar, programar_borrado, registrar
from comandos import rellenar
from permisos import es_staff, rol_de

GRAVEDAD = {"off": 0, "mute": 1, "kick": 2, "ban": 3}


async def _borrar(mensaje):
    try:
        await mensaje.delete()
    except (BadRequest, Forbidden):
        pass


async def enviar(context, chat_id: int, texto: str, a: dict, **kwargs):
    """Envía al tema de avisos si el grupo lo tiene configurado (Temas / Topics)."""
    tema = a["temas"]["avisos"]
    if tema:
        try:
            return await context.bot.send_message(chat_id, texto, message_thread_id=tema, **kwargs)
        except BadRequest:
            pass  # El tema ya no existe: lo mandamos al general
    return await context.bot.send_message(chat_id, texto, **kwargs)


async def dar_bienvenida(context, chat, usuario, a: dict):
    b = a["bienvenida"]
    if not b["on"]:
        return
    if b["borrar_anterior"] and b.get("ultimo_id"):
        try:
            await context.bot.delete_message(chat.id, b["ultimo_id"])
        except (BadRequest, Forbidden):
            pass
    mensaje = await enviar(context, chat.id, rellenar(b["texto"], usuario, chat), a)
    if b["borrar_anterior"]:
        actual = db.ajustes(chat.id)
        actual["bienvenida"]["ultimo_id"] = mensaje.message_id
        db.guardar_ajustes(chat.id, actual)
    programar_borrado(context, chat.id, mensaje.message_id, b["autoborrar"] * 60)


async def revisar_al_entrar(context, chat, usuario, a: dict) -> bool:
    """Gestión de miembros: castiga a quien entra sin @usuario o sin foto. True si castigó."""
    reglas, faltas = a["miembros"], []
    if reglas["sin_username"] != "off" and not usuario.username:
        faltas.append((reglas["sin_username"], "Entró sin @usuario"))
    if reglas["sin_foto"] != "off":
        try:
            sin_foto = (await context.bot.get_user_profile_photos(usuario.id, limit=1)).total_count == 0
        except (BadRequest, Forbidden):
            sin_foto = False
        if sin_foto:
            faltas.append((reglas["sin_foto"], "Entró sin foto de perfil"))
    if not faltas:
        return False
    accion, motivo = max(faltas, key=lambda f: GRAVEDAD[f[0]])
    await castigar(context, chat, usuario, accion, motivo)
    return True


# ---------- Captcha ----------

async def poner_captcha(context, chat, usuario, a: dict):
    c = a["captcha"]
    await context.bot.restrict_chat_member(chat.id, usuario.id, ChatPermissions.no_permissions())
    mencion = mention_html(usuario.id, usuario.first_name)
    if c["modo"] == "mates":
        x, y = random.randint(1, 9), random.randint(1, 9)
        correcto = x + y
        opciones = random.sample([n for n in range(2, 19) if n != correcto], 3) + [correcto]
        random.shuffle(opciones)
        context.chat_data[f"cap:{usuario.id}"] = correcto
        texto = (f"🧩 {mencion}, demuestra que no eres un bot: ¿cuánto es <b>{x} + {y}</b>?\n"
                 f"Tienes {c['minutos']} minutos.")
        teclado = Teclado([[Boton(str(o), callback_data=f"cap:{usuario.id}:{o}") for o in opciones]])
    else:
        texto = (f"🧩 {mencion}, demuestra que no eres un fantasma malo: toca el botón en "
                 f"{c['minutos']} minutos o te saco por el portal.")
        teclado = ui.teclado_captcha(usuario.id)
    aviso = await enviar(context, chat.id, texto, a, reply_markup=teclado)
    context.job_queue.run_once(captcha_vencido, c["minutos"] * 60, data=(chat.id, usuario.id, aviso.message_id),
                               name=f"cap:{chat.id}:{usuario.id}")


async def captcha_vencido(context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id, mensaje_id = context.job.data
    fallo = db.ajustes(chat_id)["captcha"]["fallo"]
    try:
        if fallo in ("kick", "ban"):
            await aplicar_basico(context.bot, chat_id, user_id, fallo)
        await context.bot.edit_message_text("⌛ No resolvió el captcha a tiempo.", chat_id=chat_id, message_id=mensaje_id)
        programar_borrado(context, chat_id, mensaje_id, 60)
    except (BadRequest, Forbidden):
        pass


async def boton_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE, partes: list[str]):
    q = update.callback_query
    chat, user_id = q.message.chat, int(partes[0])
    if q.from_user.id != user_id:
        await q.answer("👻 Este captcha no es para ti.", show_alert=True)
        return
    for trabajo in context.job_queue.get_jobs_by_name(f"cap:{chat.id}:{user_id}"):
        trabajo.schedule_removal()
    a = db.ajustes(chat.id)

    if len(partes) > 1:  # Captcha de suma
        correcto = context.chat_data.pop(f"cap:{user_id}", None)
        if correcto is None or int(partes[1]) != correcto:
            await _borrar(q.message)
            if a["captcha"]["fallo"] in ("kick", "ban"):
                await aplicar_basico(context.bot, chat.id, user_id, a["captcha"]["fallo"])
            await q.answer("❌ Respuesta incorrecta.", show_alert=True)
            await registrar(context.bot, chat, f"🧩 Captcha fallado por {mention_html(user_id, q.from_user.first_name)}")
            return

    permisos = (await context.bot.get_chat(chat.id)).permissions or ChatPermissions.all_permissions()
    await context.bot.restrict_chat_member(chat.id, user_id, permisos)
    await _borrar(q.message)
    await q.answer("💚 ¡Verificado! Bienvenid@")
    await dar_bienvenida(context, chat, q.from_user, a)


# ---------- Eventos del grupo ----------

async def nuevos_miembros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje, chat = update.message, update.effective_chat
    a = db.ajustes(chat.id)
    if a["eliminar"]["entradas"]:
        await _borrar(mensaje)
    anadio_staff = es_staff(await rol_de(update, context))

    for nuevo in mensaje.new_chat_members:
        if nuevo.id == context.bot.id:
            await context.bot.send_message(chat.id, ui.tarjeta(
                "¡Llegó Danny Phantom! 👻",
                "Gracias por traerme. Hazme <b>administrador</b> con permiso para borrar mensajes, "
                "restringir y fijar, y usa /settings para configurarme. Mis comandos: /help",
            ))
            continue
        if nuevo.is_bot:
            if a["bloqueos"]["bots"] and not anadio_staff:
                try:
                    await aplicar_basico(context.bot, chat.id, nuevo.id, "kick")
                    aviso = await context.bot.send_message(chat.id, f"🤖 Saqué a {mention_html(nuevo.id, nuevo.first_name)}: "
                                                                    "solo los admins pueden añadir bots.")
                    programar_borrado(context, chat.id, aviso.message_id, 30)
                    await registrar(context.bot, chat, f"🤖 Bot expulsado: @{nuevo.username}")
                except (BadRequest, Forbidden):
                    pass
            continue
        db.recordar_usuario(nuevo.id, nuevo.username, nuevo.full_name)
        if await revisar_al_entrar(context, chat, nuevo, a):
            continue
        if a["captcha"]["on"]:
            try:
                await poner_captcha(context, chat, nuevo, a)
                continue
            except (BadRequest, Forbidden):
                pass  # Sin permisos para restringir: solo damos la bienvenida
        await dar_bienvenida(context, chat, nuevo, a)


async def miembro_salio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, salio = update.effective_chat, update.message.left_chat_member
    a = db.ajustes(chat.id)
    if a["eliminar"]["salidas"]:
        await _borrar(update.message)
    if salio.id == context.bot.id or salio.is_bot:
        return
    if a["despedida"]["on"]:
        await enviar(context, chat.id, rellenar(a["despedida"]["texto"], salio, chat), a)


async def mensaje_fijado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db.ajustes(update.effective_chat.id)["eliminar"]["fijados"]:
        await _borrar(update.message)


# ---------- Modo de aprobación (solicitudes para unirse) ----------

async def solicitud_union(update: Update, context: ContextTypes.DEFAULT_TYPE):
    solicitud = update.chat_join_request
    chat = solicitud.chat
    modo = db.ajustes(chat.id)["aprobacion"]["modo"]
    try:
        if modo == "auto":
            await solicitud.approve()
        elif modo == "captcha":
            await context.bot.send_message(
                solicitud.user_chat_id,
                ui.tarjeta("🧩 Verificación", f"Pediste entrar a <b>{escape(chat.title)}</b>. "
                                              "Toca el botón para demostrar que no eres un bot."),
                reply_markup=Teclado([[Boton("👻 No soy un bot, déjame entrar", callback_data=f"apr:{chat.id}")]]),
            )
    except (BadRequest, Forbidden):
        pass


async def boton_aprobacion(update: Update, context: ContextTypes.DEFAULT_TYPE, partes: list[str]):
    q = update.callback_query
    chat_id = int(partes[0])
    try:
        await context.bot.approve_chat_join_request(chat_id, q.from_user.id)
        await q.edit_message_text("✅ ¡Listo! Ya estás dentro del grupo. 💚")
    except (BadRequest, Forbidden):
        await q.edit_message_text("⌛ Esa solicitud ya no está activa. Vuelve a pedir entrar al grupo.")
    await q.answer()
