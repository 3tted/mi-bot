"""Panel del dueño del bot: en qué grupos está, quién lo usa, y avisos cuando lo añaden o lo sacan.

Solo funciona para la persona cuyo ID de Telegram está en la variable de entorno OWNER_ID.
"""
import math
import os
import time
from html import escape

from telegram import InlineKeyboardButton as Boton, InlineKeyboardMarkup as Teclado, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

import db
import ui
from comandos import Peticion, comando

ES_GRUPO = (ChatType.GROUP, ChatType.SUPERGROUP)
DENTRO = (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.RESTRICTED)
POR_PAGINA = 10


def id_dueno() -> int | None:
    valor = os.environ.get("OWNER_ID", "").strip()
    return int(valor) if valor.isdigit() else None


def es_dueno(user_id: int) -> bool:
    return id_dueno() is not None and user_id == id_dueno()


def hace(segundos_epoch: int | None) -> str:
    if not segundos_epoch:
        return "nunca"
    diferencia = int(time.time()) - segundos_epoch
    if diferencia < 60:
        return "ahora mismo"
    for unidad, singular, plural in ((86400, "día", "días"), (3600, "hora", "horas"), (60, "minuto", "minutos")):
        if diferencia >= unidad:
            n = diferencia // unidad
            return f"hace {n} {singular if n == 1 else plural}"
    return "ahora mismo"


def nombre_grupo(g: dict) -> str:
    titulo = escape(g.get("titulo") or str(g["chat_id"]))
    if g.get("username"):
        return f"<a href=\"https://t.me/{g['username']}\">{titulo}</a>"
    return f"<b>{titulo}</b>"


async def avisar_dueno(context: ContextTypes.DEFAULT_TYPE, texto: str, **kwargs):
    dueno = id_dueno()
    if not dueno:
        return
    try:
        await context.bot.send_message(dueno, texto, **kwargs)
    except (BadRequest, Forbidden):
        pass  # El dueño todavía no ha iniciado el chat con el bot


# =====================================================================
# Registro automático: cuando añaden, sacan o cambian de rol al bot
# =====================================================================

async def cambio_en_el_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cambio = update.my_chat_member
    chat, quien = cambio.chat, cambio.from_user
    if chat.type not in ES_GRUPO:
        return
    nuevo, viejo = cambio.new_chat_member.status, cambio.old_chat_member.status
    es_admin = int(nuevo == ChatMemberStatus.ADMINISTRATOR)
    por = f"👤 Por: {mention_html(quien.id, quien.full_name)} (<code>{quien.id}</code>)"
    boton_ver = Teclado([[Boton("📊 Ver grupo", callback_data=f"own:g:{chat.id}")]])

    if nuevo in DENTRO and viejo not in DENTRO:
        try:
            miembros = await context.bot.get_chat_member_count(chat.id)
        except (BadRequest, Forbidden):
            miembros = None
        ahora = int(time.time())
        db.guardar_grupo(
            chat.id, titulo=chat.title, username=chat.username, activo=1, es_admin=es_admin, miembros=miembros,
            agregado_por=quien.id, agregado_nombre=quien.full_name, alta=ahora, ultima_actividad=ahora,
        )
        await avisar_dueno(context, ui.tarjeta(
            "➕ Me añadieron a un grupo",
            f"🏠 {nombre_grupo({'chat_id': chat.id, 'titulo': chat.title, 'username': chat.username})}\n"
            f"👥 Miembros: {miembros if miembros is not None else '?'}\n{por}",
        ), reply_markup=boton_ver)
    elif viejo in DENTRO and nuevo not in DENTRO:
        db.guardar_grupo(chat.id, titulo=chat.title, username=chat.username, activo=0, es_admin=0)
        await avisar_dueno(context, ui.tarjeta(
            "➖ Me sacaron de un grupo", f"🏠 <b>{escape(chat.title or str(chat.id))}</b>\n{por}",
        ))
    elif nuevo in DENTRO:
        db.guardar_grupo(chat.id, titulo=chat.title, username=chat.username, activo=1, es_admin=es_admin)
        if (viejo == ChatMemberStatus.ADMINISTRATOR) != bool(es_admin):
            titulo = "⚡ Ahora soy administrador" if es_admin else "⚠️ Me quitaron el admin"
            await avisar_dueno(context, ui.tarjeta(titulo, f"🏠 <b>{escape(chat.title)}</b>\n{por}"),
                               reply_markup=boton_ver)


async def grupo_migrado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cuando un grupo pasa a supergrupo cambia de ID: el viejo deja de existir."""
    mensaje = update.message
    if mensaje.migrate_to_chat_id:
        db.guardar_grupo(update.effective_chat.id, activo=0)


# =====================================================================
# Comandos
# =====================================================================

@comando("id", "miid", solo_grupo=False)
async def mi_id(p: Peticion):
    texto = f"🆔 Tu ID de Telegram: <code>{p.user.id}</code>"
    if p.chat.type in ES_GRUPO:
        texto += f"\n🏠 ID de este grupo: <code>{p.chat.id}</code>"
    await p.responder(texto)


async def solo_para_dueno(p: Peticion) -> bool:
    if id_dueno() is None:
        if p.chat.type == ChatType.PRIVATE:
            await p.responder(
                "🔐 El panel del dueño todavía no está activado.\n\n"
                f"En Render, en <b>Environment</b>, agrega la variable <code>OWNER_ID</code> con este valor:\n"
                f"<code>{p.user.id}</code>\n\nEse es tu ID. Solo esa persona podrá ver el panel."
            )
        return False
    if not es_dueno(p.user.id):
        return False  # A los demás no les decimos que existe
    if p.chat.type != ChatType.PRIVATE:
        await p.responder("🔐 Por seguridad, el panel solo funciona por privado conmigo.")
        return False
    return True


def texto_panel() -> tuple[str, Teclado]:
    t = db.totales()
    texto = ui.tarjeta(
        "🔐 Panel del dueño",
        f"🏠 Grupos donde estoy: <b>{t['grupos']}</b>\n"
        f"🚪 Grupos de los que me sacaron: {t['grupos_fuera']}\n"
        f"💬 Personas que me usan por privado: <b>{t['privados']}</b> ({t['privados_semana']} esta semana)\n"
        f"👥 Personas que he visto en total: {t['usuarios']}\n"
        f"📨 Mensajes contados en grupos: {t['mensajes']}\n\n"
        "<i>Solo cuento lo que ha pasado desde que guardo estos datos. Un grupo antiguo aparece "
        "en cuanto alguien escribe en él.</i>",
    )
    teclado = Teclado([
        [Boton("📋 Ver mis grupos", callback_data="own:lista:0")],
        [Boton("🔄 Actualizar", callback_data="own:panel")],
    ])
    return texto, teclado


def texto_lista(pagina: int) -> tuple[str, Teclado]:
    todos = db.lista_grupos()
    if not todos:
        return ui.tarjeta(
            "📋 Mis grupos",
            "Todavía no tengo grupos registrados. Aparecerán aquí cuando me añadan a uno "
            "o cuando alguien escriba en un grupo donde ya estoy.",
        ), Teclado([[Boton("⬅️ Volver", callback_data="own:panel")]])

    paginas = math.ceil(len(todos) / POR_PAGINA)
    pagina = max(0, min(pagina, paginas - 1))
    trozo = todos[pagina * POR_PAGINA:(pagina + 1) * POR_PAGINA]
    lineas, botones = [], []
    for i, g in enumerate(trozo, start=pagina * POR_PAGINA + 1):
        admin = "⚡ admin" if g["es_admin"] else "⚠️ sin admin"
        miembros = g["miembros"] if g["miembros"] is not None else "?"
        lineas.append(f"{i}. {nombre_grupo(g)}\n    👥 {miembros} · {admin} · 🕒 {hace(g['ultima_actividad'])}")
        botones.append([Boton(f"{i}. {(g['titulo'] or str(g['chat_id']))[:30]}", callback_data=f"own:g:{g['chat_id']}")])

    navegacion = []
    if pagina > 0:
        navegacion.append(Boton("◀️", callback_data=f"own:lista:{pagina - 1}"))
    if paginas > 1:
        navegacion.append(Boton(f"{pagina + 1}/{paginas}", callback_data="own:nada"))
    if pagina < paginas - 1:
        navegacion.append(Boton("▶️", callback_data=f"own:lista:{pagina + 1}"))
    if navegacion:
        botones.append(navegacion)
    botones.append([Boton("⬅️ Volver al panel", callback_data="own:panel")])

    texto = ui.tarjeta(f"📋 Mis grupos ({len(todos)})", "\n".join(lineas) + "\n\n<i>Toca un grupo para ver más.</i>")
    return texto, Teclado(botones)


async def texto_grupo(bot, chat_id: int) -> tuple[str, Teclado]:
    volver = [Boton("⬅️ Volver a la lista", callback_data="own:lista:0")]
    g = db.grupo(chat_id) or {"chat_id": chat_id}
    try:
        chat = await bot.get_chat(chat_id)
    except (BadRequest, Forbidden):
        db.guardar_grupo(chat_id, activo=0, es_admin=0)
        return ui.tarjeta("🚪 Ya no estoy en ese grupo", nombre_grupo(g)), Teclado([volver])

    try:
        miembros = await bot.get_chat_member_count(chat_id)
    except (BadRequest, Forbidden):
        miembros = g.get("miembros")
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except (BadRequest, Forbidden):
        admins = []
    soy_admin = any(a.user.id == bot.id for a in admins)
    db.guardar_grupo(chat_id, titulo=chat.title, username=chat.username, activo=1,
                     es_admin=int(soy_admin), miembros=miembros)
    g = db.grupo(chat_id)

    if chat.invite_link:
        enlace = chat.invite_link
    elif chat.username:
        enlace = f"https://t.me/{chat.username}"
    else:
        enlace = "no disponible (necesito ser admin con permiso para invitar)"

    staff = []
    for a in admins:
        if a.user.is_bot:
            continue
        corona = "👑" if a.status == ChatMemberStatus.OWNER else "⚡"
        staff.append(f"  {corona} {mention_html(a.user.id, a.user.full_name)}")

    personas, mensajes = db.actividad_grupo(chat_id)
    top = db.top_mensajes(chat_id, 5)
    activos = [f"  • {mention_html(uid, db.nombre_usuario(uid) or str(uid))}: {n}" for uid, n in top]
    a = db.ajustes(chat_id)
    agrego = (mention_html(g["agregado_por"], g["agregado_nombre"] or str(g["agregado_por"]))
              if g.get("agregado_por") else "desconocido")

    texto = ui.tarjeta(
        f"🏠 {escape(chat.title)}",
        f"🆔 <code>{chat_id}</code>\n"
        f"👥 Miembros: <b>{miembros if miembros is not None else '?'}</b>\n"
        f"🔗 Enlace: {escape(enlace)}\n"
        f"➕ Me añadió: {agrego} · {hace(g.get('alta'))}\n"
        f"🕒 Última actividad: {hace(g.get('ultima_actividad'))}\n"
        f"⚡ Soy admin: {ui.si_no(soy_admin)}\n\n"
        f"<b>👑 Administradores</b>\n" + ("\n".join(staff) or "  (no los puedo ver)") + "\n\n"
        f"<b>💬 Actividad</b>\n  {personas} personas han escrito · {mensajes} mensajes\n"
        + ("<b>📊 Más activos</b>\n" + "\n".join(activos) + "\n" if activos else "")
        + f"\n<b>⚙️ Protecciones</b>\n  Captcha {ui.si_no(a['captcha']['on'])} · "
        f"Antiflood {ui.si_no(a['antiflood']['on'])} · Antilink {ui.si_no(a['antilink'])}",
    )
    teclado = Teclado([
        [Boton("🔄 Actualizar", callback_data=f"own:g:{chat_id}"),
         Boton("🚪 Salir del grupo", callback_data=f"own:salir:{chat_id}")],
        volver,
    ])
    return texto, teclado


@comando("panel", "stats", "estadisticas", solo_grupo=False)
async def panel(p: Peticion):
    if await solo_para_dueno(p):
        texto, teclado = texto_panel()
        await p.responder(texto, reply_markup=teclado)


@comando("grupos", "misgrupos", solo_grupo=False)
async def mis_grupos(p: Peticion):
    if await solo_para_dueno(p):
        texto, teclado = texto_lista(0)
        await p.responder(texto, reply_markup=teclado)


# =====================================================================
# Botones del panel (callback_data "own:...")
# =====================================================================

async def botones(update: Update, context: ContextTypes.DEFAULT_TYPE, partes: list[str]):
    q = update.callback_query
    if not es_dueno(q.from_user.id):
        await q.answer("🔐 Este panel es solo para el dueño del bot.", show_alert=True)
        return
    accion = partes[0]
    if accion == "panel":
        texto, teclado = texto_panel()
    elif accion == "lista":
        texto, teclado = texto_lista(int(partes[1]))
    elif accion == "g":
        texto, teclado = await texto_grupo(context.bot, int(partes[1]))
    elif accion == "salir":
        chat_id = int(partes[1])
        g = db.grupo(chat_id) or {"chat_id": chat_id}
        texto = ui.tarjeta("🚪 ¿Salir del grupo?", f"Voy a salir de {nombre_grupo(g)}. Para volver tendrán que añadirme otra vez.")
        teclado = Teclado([[Boton("✅ Sí, salir", callback_data=f"own:salirok:{chat_id}"),
                            Boton("⬅️ No", callback_data=f"own:g:{chat_id}")]])
    elif accion == "salirok":
        chat_id = int(partes[1])
        g = db.grupo(chat_id) or {"chat_id": chat_id}
        try:
            await context.bot.leave_chat(chat_id)
        except (BadRequest, Forbidden):
            pass
        db.guardar_grupo(chat_id, activo=0, es_admin=0)
        texto = ui.tarjeta("🚪 Salí del grupo", nombre_grupo(g))
        teclado = Teclado([[Boton("⬅️ Volver a la lista", callback_data="own:lista:0")]])
    else:
        await q.answer()
        return
    try:
        await q.edit_message_text(texto, reply_markup=teclado)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise
    await q.answer()
