"""Entradas y salidas: bienvenida, despedida, captcha, reglas al entrar, bots, solicitudes de unión y avisos de servicio."""
import random
from html import escape

from telegram import ChatPermissions, InlineKeyboardButton as Boton, InlineKeyboardMarkup as Teclado, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

import db
import mensajes
import tiempo
import ui
from castigos import aplicar_basico, castigar, programar_borrado, registrar
from permisos import es_staff, rol_de

GRAVEDAD = {"off": 0, "mute": 1, "kick": 2, "ban": 3}
EMOJIS_PRUEBA = ["👻", "🍌", "🚀", "🎃", "🐒", "⭐", "🍕", "🎲", "🌙", "🔥"]


async def _borrar(mensaje):
    try:
        await mensaje.delete()
    except (BadRequest, Forbidden):
        pass


async def _borrar_id(bot, chat_id: int, mensaje_id: int | None):
    if mensaje_id:
        try:
            await bot.delete_message(chat_id, mensaje_id)
        except (BadRequest, Forbidden):
            pass


def _tema(a: dict) -> dict:
    tema = a["temas"]["avisos"]
    return {"message_thread_id": tema} if tema else {}


async def enviar(context, chat_id: int, texto: str, a: dict, **kwargs):
    """Envía al tema de avisos si el grupo lo tiene configurado (Temas / Topics)."""
    if a["temas"]["avisos"]:
        try:
            return await context.bot.send_message(chat_id, texto, **_tema(a), **kwargs)
        except BadRequest:
            pass  # El tema ya no existe: lo mandamos al general
    return await context.bot.send_message(chat_id, texto, **kwargs)


async def enviar_personalizado(context, chat, m: dict, usuario, a: dict):
    reglas = a["reglas_msg"]["texto"]
    if a["temas"]["avisos"]:
        try:
            return await mensajes.enviar(context.bot, chat.id, m, usuario, chat, reglas, **_tema(a))
        except BadRequest:
            pass
    return await mensajes.enviar(context.bot, chat.id, m, usuario, chat, reglas)


# ---------- Bienvenida y despedida ----------

async def dar_bienvenida(context, chat, usuario, a: dict, primera: bool = True):
    b = a["bienvenida"]
    if not b["on"] or (b["modo"] == "primera" and not primera):
        return
    if b["borrar_ultimo"]:
        await _borrar_id(context.bot, chat.id, b.get("ultimo_id"))
    enviado = await enviar_personalizado(context, chat, b["mensaje"], usuario, a)
    if not enviado:
        return
    if b["borrar_ultimo"]:
        actual = db.ajustes(chat.id)
        actual["bienvenida"]["ultimo_id"] = enviado.message_id
        db.guardar_ajustes(chat.id, actual)
    programar_borrado(context, chat.id, enviado.message_id, b.get("autoborrar", 0) * 60)


async def dar_despedida(context, chat, usuario, a: dict):
    d = a["despedida"]
    if not d["on"]:
        return
    if d["privado"]:
        try:
            await mensajes.enviar(context.bot, usuario.id, d["mensaje"], usuario, chat, a["reglas_msg"]["texto"])
        except (BadRequest, Forbidden):
            pass  # Esa persona nunca le escribió al bot
        return
    if d["borrar_ultimo"]:
        await _borrar_id(context.bot, chat.id, d.get("ultimo_id"))
    enviado = await enviar_personalizado(context, chat, d["mensaje"], usuario, a)
    if enviado and d["borrar_ultimo"]:
        actual = db.ajustes(chat.id)
        actual["despedida"]["ultimo_id"] = enviado.message_id
        db.guardar_ajustes(chat.id, actual)


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


# ---------- Captcha (6 modos, como Group Help) ----------

def _pendientes(context) -> dict:
    return context.bot_data.setdefault("captchas", {})


async def poner_captcha(context, chat, usuario, a: dict, servicio_id: int | None = None, primera: bool = True):
    cap = a["captcha"]
    modo = cap["modo"]
    mencion = mention_html(usuario.id, usuario.first_name)
    plazo = tiempo.escribir(cap["tiempo"]).lower()
    if modo != "presentacion":
        await context.bot.restrict_chat_member(chat.id, usuario.id, ChatPermissions.no_permissions())
    correcto, teclado = None, None
    if modo == "matematicas":
        x, y = random.randint(1, 9), random.randint(1, 9)
        correcto = x + y
        opciones = random.sample([n for n in range(2, 19) if n != correcto], 3) + [correcto]
        random.shuffle(opciones)
        texto = f"🧮 {mencion}, demuestra que no eres un robot: ¿cuánto es <b>{x} + {y}</b>?"
        teclado = Teclado([[Boton(str(o), callback_data=f"cap:{usuario.id}:{o}") for o in opciones]])
    elif modo == "prueba":
        opciones = random.sample(EMOJIS_PRUEBA, 6)
        correcto = random.randrange(6)
        texto = f"🎯 {mencion}, demuestra que no eres un robot: toca el emoji {opciones[correcto]}"
        botones = [Boton(e, callback_data=f"cap:{usuario.id}:{i}") for i, e in enumerate(opciones)]
        teclado = Teclado([botones[:3], botones[3:]])
    elif modo == "reglamento":
        reglas = a["reglas_msg"]["texto"] or "<i>Este grupo todavía no tiene reglas.</i>"
        texto = f"📜 {mencion}, lee el reglamento y acéptalo para poder escribir:\n\n{reglas}"
        teclado = Teclado([[Boton("✅ Acepto el reglamento", callback_data=f"cap:{usuario.id}")]])
    elif modo == "recaptcha":
        texto = f"🔐 {mencion}, verifícate en mi chat privado para poder escribir en el grupo."
        teclado = Teclado([[Boton("🤖 Verificarme", url=f"https://t.me/{context.bot.username}?start=cap_{chat.id}")]])
    elif modo == "presentacion":
        texto = f"👋 {mencion}, preséntate escribiendo un mensaje en el grupo."
    else:  # botón
        texto = f"🧩 {mencion}, demuestra que no eres un robot: toca el botón."
        teclado = ui.teclado_captcha(usuario.id)
    texto += f"\n⏱️ Tienes {plazo}."
    if cap["mensaje"]["texto"]:
        texto = mensajes.rellenar(cap["mensaje"]["texto"], usuario, chat, a["reglas_msg"]["texto"]) + "\n\n" + texto
    aviso = await enviar(context, chat.id, texto, a, reply_markup=teclado)
    _pendientes(context)[(chat.id, usuario.id)] = {
        "msg": aviso.message_id, "servicio": servicio_id, "correcto": correcto, "modo": modo, "primera": primera}
    context.job_queue.run_once(captcha_vencido, cap["tiempo"], data=(chat.id, usuario.id),
                               name=f"cap:{chat.id}:{usuario.id}")


async def _fallo(context, chat_id: int, user_id: int, pendiente: dict, motivo: str):
    a = db.ajustes(chat_id)
    castigo = a["captcha"]["castigo"]
    try:
        if castigo in ("kick", "ban"):
            await aplicar_basico(context.bot, chat_id, user_id, castigo)
        elif pendiente["modo"] == "presentacion":
            await aplicar_basico(context.bot, chat_id, user_id, "mute")
    except (BadRequest, Forbidden):
        pass
    if a["captcha"]["borrar_servicio"]:
        await _borrar_id(context.bot, chat_id, pendiente.get("servicio"))
    chat = await context.bot.get_chat(chat_id)
    await registrar(context.bot, chat, f"🧩 Captcha fallado por <code>{user_id}</code> ({motivo})")


async def captcha_vencido(context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = context.job.data
    pendiente = _pendientes(context).pop((chat_id, user_id), None)
    if not pendiente:
        return
    await _fallo(context, chat_id, user_id, pendiente, "tiempo agotado")
    try:
        await context.bot.edit_message_text("⌛ No resolvió el captcha a tiempo.", chat_id=chat_id,
                                            message_id=pendiente["msg"])
        programar_borrado(context, chat_id, pendiente["msg"], 60)
    except (BadRequest, Forbidden):
        pass


async def verificar(context, chat, usuario, correcto: bool):
    """Termina el captcha de un usuario: lo deja escribir y le da la bienvenida, o lo castiga."""
    pendiente = _pendientes(context).pop((chat.id, usuario.id), None)
    if not pendiente:
        return False
    for trabajo in context.job_queue.get_jobs_by_name(f"cap:{chat.id}:{usuario.id}"):
        trabajo.schedule_removal()
    await _borrar_id(context.bot, chat.id, pendiente["msg"])
    if not correcto:
        await _fallo(context, chat.id, usuario.id, pendiente, "respuesta incorrecta")
        return True
    if pendiente["modo"] != "presentacion":
        permisos = (await context.bot.get_chat(chat.id)).permissions or ChatPermissions.all_permissions()
        await context.bot.restrict_chat_member(chat.id, usuario.id, permisos)
    await dar_bienvenida(context, chat, usuario, db.ajustes(chat.id), pendiente["primera"])
    return True


async def boton_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE, partes: list[str]):
    q = update.callback_query
    chat, user_id = q.message.chat, int(partes[0])
    if q.from_user.id != user_id:
        await q.answer("👻 Este captcha no es para ti.", show_alert=True)
        return
    pendiente = _pendientes(context).get((chat.id, user_id))
    if not pendiente:
        await q.answer("⌛ Este captcha ya no está activo.", show_alert=True)
        return
    correcto = len(partes) == 1 or int(partes[1]) == pendiente["correcto"]
    await verificar(context, chat, q.from_user, correcto)
    await q.answer("💚 ¡Verificado! Bienvenid@" if correcto else "❌ Respuesta incorrecta.", show_alert=not correcto)


async def captcha_privado(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """/start cap_<grupo>: el modo reCaptcha se resuelve en el chat privado."""
    if (chat_id, update.effective_user.id) not in _pendientes(context):
        await update.message.reply_text("⌛ No tienes ningún captcha pendiente en ese grupo.")
        return
    await update.message.reply_text(
        "🔐 <b>Verificación</b>\n\nToca el botón para demostrar que no eres un robot.",
        reply_markup=Teclado([[Boton("🤖 No soy un robot", callback_data=f"capp:{chat_id}")]]))


async def boton_captcha_privado(update: Update, context: ContextTypes.DEFAULT_TYPE, partes: list[str]):
    q = update.callback_query
    chat = await context.bot.get_chat(int(partes[0]))
    if await verificar(context, chat, q.from_user, True):
        await q.edit_message_text(f"✅ ¡Verificado! Ya puedes escribir en <b>{escape(chat.title)}</b>.")
    else:
        await q.edit_message_text("⌛ Ese captcha ya no está activo.")
    await q.answer()


async def revisar_presentacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Modo Presentación: el primer mensaje del nuevo miembro lo verifica."""
    clave = (update.effective_chat.id, update.effective_user.id)
    pendiente = _pendientes(context).get(clave)
    if pendiente and pendiente["modo"] == "presentacion" and (update.message.text or update.message.caption):
        await verificar(context, update.effective_chat, update.effective_user, True)


# ---------- Eventos del grupo ----------

async def nuevos_miembros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje, chat = update.message, update.effective_chat
    a = db.ajustes(chat.id)
    servicio_id = mensaje.message_id
    if a["eliminar"]["entradas"]:
        await _borrar(mensaje)
        servicio_id = None
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
        primera = not db.ya_entro(chat.id, nuevo.id)
        db.marcar_entrada(chat.id, nuevo.id)
        if await revisar_al_entrar(context, chat, nuevo, a):
            continue
        if a["captcha"]["on"]:
            try:
                await poner_captcha(context, chat, nuevo, a, servicio_id, primera)
                continue
            except (BadRequest, Forbidden):
                pass  # Sin permisos para restringir: solo damos la bienvenida
        await dar_bienvenida(context, chat, nuevo, a, primera)


async def miembro_salio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, salio = update.effective_chat, update.message.left_chat_member
    a = db.ajustes(chat.id)
    if a["eliminar"]["salidas"]:
        await _borrar(update.message)
    if salio.id == context.bot.id or salio.is_bot:
        return
    await dar_despedida(context, chat, salio, a)


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
