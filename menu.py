"""Menú /settings igual que el de Group Help.

callback_data:  g:<chat>:<vista>:<op>[:<arg>...]
  op v  = ver la vista (arg opcional: parte desplegada, p. ej. "modo")
  op k  = elegir castigo (arg: off|warn|kick|mute|ban)       op kb = interruptor "Borrar los Mensajes"
  op kd = pedir duración (arg: mute|ban)                     op x  = cancelar lo que se esperaba escribir
  op z  = borrar el valor que se esperaba (p. ej. "Eliminar la duración")
  otros = acciones propias de cada vista
Las secciones que todavía no se han rehecho siguen usando ajustes_menu (callback "cfg:...").
"""
from dataclasses import dataclass
from html import escape

from telegram import InlineKeyboardButton as Boton, InlineKeyboardMarkup as Teclado, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

import castigos
import db
import mensajes
import tiempo
from permisos import NIVELES, nivel, staff

SI_NO = {True: "✔️", False: "✖️"}


@dataclass
class Ctx:
    chat_id: int
    titulo: str
    a: dict
    arg: str = ""


def B(texto: str, chat_id: int, vista: str, op: str = "v", *args) -> Boton:
    return Boton(texto, callback_data=":".join(["g", str(chat_id), vista, op, *map(str, args)]))


def VIEJA(texto: str, chat_id: int, seccion: str) -> Boton:
    """Botón a una sección del menú anterior (aún no rehecha)."""
    return Boton(texto, callback_data=f"cfg:{chat_id}:s:{seccion}")


def leer(a: dict, ruta: tuple):
    for clave in ruta:
        a = a[clave]
    return a


def escribir(a: dict, ruta: tuple, valor):
    for clave in ruta[:-1]:
        a = a[clave]
    a[ruta[-1]] = valor


# =====================================================================
# Páginas principales
# =====================================================================

PAGINA_1 = [
    [("📜 Reglamento", "reglas"), ("📨 Antispam", "antispam")],
    [("💬 Bienvenida", "bienv"), ("🗣️ Anti-flood", "flood")],
    [("👋 Despedida", "desp"), ("🕉️ Alfabetos", "alfa")],
    [("🧠 Captcha", "captcha"), ("🔦 Filtros", "old:filtros")],
    [("🆘 Reportes", "old:reportes"), ("🔐 Bloqueos", "old:bloqueos")],
    [("📸 Multimedia", "old:multimedia"), ("🔞 Antiporno", "old:antiporno")],
    [("❗ Advertencias", "old:advertencias"), ("🌙 Modo nocturno", "old:nocturno")],
    [("🛎️ Etiqueta", "old:etiqueta"), ("🔗 Enlace del grupo", "old:enlace")],
    [("👮 Bot Guardián 🆕", "old:guardian")],
    [("📬 Modo de aprobación", "old:aprobacion")],
    [("🗑️ Eliminación Mensajes", "old:eliminacion")],
]
PAGINA_2 = [
    [("🗂️ Temas / Topics", "old:temas")],
    [("🔤 Palabras Prohibidas", "old:palabras")],
    [("🕐 Mensajes Recurrentes", "old:recurrentes")],
    [("👥 Gestión de Miembros", "old:miembros")],
    [("😶‍🌫️ Usuarios enmascarados", "old:enmascarados")],
    [("📣 Grupo de discusión 🆕", "old:discusion")],
    [("📱 Comandos Personales", "old:personales")],
    [("🎭 Stickers & GIFs Mágicos", "old:magicos")],
    [("📏 Longitud de Mensajes", "old:longitud")],
    [("📢 Gestión de canales 🆕", "canales")],
    [("👻 Extras de Danny Phantom", "extras")],
    [("✍️ Permisos", "old:permisos"), ("🔍 Canal de registro", "old:registro")],
]


def texto_pagina(titulo: str) -> str:
    return (f"<b>CONFIGURACIÓN</b>\n<b>Grupo:</b> {escape(titulo)}\n\n"
            "<i>Elige cual de los ajustes quieres editar.</i>")


def teclado_pagina(chat_id: int, pagina: int) -> Teclado:
    filas = []
    for fila in (PAGINA_1 if pagina == 0 else PAGINA_2):
        botones = []
        for texto, destino in fila:
            if destino.startswith("old:"):
                botones.append(VIEJA(texto, chat_id, destino[4:]))
            else:
                botones.append(B(texto, chat_id, destino))
        filas.append(botones)
    idioma = B("🇪🇸 Lang", chat_id, "main", "lang")
    cerrar = B("✅ Cerrar", chat_id, "main", "cerrar")
    if pagina == 0:
        filas.append([idioma, cerrar, B("▶️ Más", chat_id, "p2")])
    else:
        filas.append([B("◀️ Volver", chat_id, "p1"), cerrar, idioma])
    return Teclado(filas)


# =====================================================================
# Bloques reutilizables
# =====================================================================

def texto_castigo(cfg: dict, con_eliminacion: bool = True) -> str:
    texto = f"<b>Castigo:</b> {castigos.describir(cfg)}"
    if con_eliminacion:
        texto += f"\n<b>Eliminación:</b> {'Sí ✔️' if cfg['borrar'] else 'No ✖️'}"
    return texto


def filas_castigo(chat_id: int, vista: str, cfg: dict, con_borrar: bool = True) -> list:
    filas = [
        [B("❌ Off", chat_id, vista, "k", "off"), B("❕ Warn", chat_id, vista, "k", "warn"),
         B("❗ Kick", chat_id, vista, "k", "kick")],
        [B("🔇 Silenciar", chat_id, vista, "k", "mute"), B("🚷 Ban", chat_id, vista, "k", "ban")],
    ]
    if con_borrar:
        filas.append([B(f"🗑️ Borrar los Mensajes {SI_NO[cfg['borrar']]}", chat_id, vista, "kb")])
    if cfg["accion"] == "mute":
        filas.append([B("🔇⏱️ Escoger duración de silencio", chat_id, vista, "kd", "mute")])
    elif cfg["accion"] == "ban":
        filas.append([B("🚷⏱️ Escoger duración de ban", chat_id, vista, "kd", "ban")])
    return filas


def volver(chat_id: int, vista: str) -> Boton:
    return B("🔙 Volver", chat_id, vista)


# =====================================================================
# Esperando que el admin escriba algo (duración, texto, multimedia...)
# =====================================================================

@dataclass
class Espera:
    chat_id: int          # grupo que se está configurando
    tipo: str             # dur_mute | dur_ban | texto | media | botones | lista_add | lista_del
    ruta: tuple
    vista: str            # a dónde volver
    menu_chat: int
    menu_id: int


ESPERAS: dict[tuple[int, int], Espera] = {}

PROMPTS = {
    "dur_mute": ("⏱️ <b>Duración de Silenciar</b>", "Silenciar"),
    "dur_ban": ("⏱️ <b>Duración de Ban</b>", "Ban"),
}


def texto_espera(e: Espera, a: dict) -> tuple[str, list]:
    if e.tipo in ("dur_mute", "dur_ban"):
        titulo, nombre = PROMPTS[e.tipo]
        actual = leer(a, e.ruta)
        texto = (f"{titulo}\n\nEnvía ahora la duración del castigo establecido ({nombre})\n\n"
                 f"<b>Mínimo:</b> 30 segundos\n<b>Máximo:</b> 365 días\n\n"
                 f"<b>Ejemplo de formato de elección:</b> <code>3 meses 2 días 12 horas 4 minutos 34 segundos</code>\n\n"
                 f"<b>Duración actual:</b> {tiempo.escribir(actual)}")
        filas = [[B("0️⃣ Eliminar la duración", e.chat_id, e.vista, "z")], [B("❌ Cancelar", e.chat_id, e.vista, "x")]]
    elif e.tipo == "texto":
        texto = ("📄 <b>Texto</b>\n\nEnvía ahora el texto del mensaje. Puedes usar formato (negrita, cursiva, enlaces...).\n\n"
                 + mensajes.VARIABLES_AYUDA)
        filas = [[B("🗑️ Eliminar", e.chat_id, e.vista, "z")], [B("❌ Cancelar", e.chat_id, e.vista, "x")]]
    elif e.tipo == "media":
        texto = "🖼️ <b>Multimedia</b>\n\nEnvía ahora una foto, video, GIF, sticker, audio o archivo."
        filas = [[B("🗑️ Eliminar", e.chat_id, e.vista, "z")], [B("❌ Cancelar", e.chat_id, e.vista, "x")]]
    elif e.tipo == "botones":
        texto = "⌨️ <b>Teclado Inline</b>\n\n" + mensajes.BOTONES_AYUDA
        filas = [[B("🗑️ Eliminar", e.chat_id, e.vista, "z")], [B("❌ Cancelar", e.chat_id, e.vista, "x")]]
    elif e.tipo == "lista_add":
        texto = ("➕ <b>Añadir</b>\n\nEnvía ahora los enlaces o @usernames que quieres añadir a la lista blanca "
                 "(uno por línea).")
        filas = [[B("❌ Cancelar", e.chat_id, e.vista, "x")]]
    else:  # lista_del
        texto = "➖ <b>Eliminar</b>\n\nEnvía ahora los enlaces o @usernames que quieres quitar de la lista blanca."
        filas = [[B("❌ Cancelar", e.chat_id, e.vista, "x")]]
    return texto, filas


def _normalizar_excepcion(x: str) -> str:
    x = x.strip().lower()
    for prefijo in ("https://", "http://", "www."):
        x = x.removeprefix(prefijo)
    return x.rstrip("/")


async def capturar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Si el admin estaba escribiendo un valor pedido por el menú, lo guarda. True si lo consumió."""
    mensaje, usuario = update.message, update.effective_user
    if not usuario:
        return False
    e = ESPERAS.get((update.effective_chat.id, usuario.id))
    if not e:
        return False
    a = db.ajustes(e.chat_id)
    error = None
    if e.tipo in ("dur_mute", "dur_ban"):
        segundos = tiempo.leer(mensaje.text or "")
        if segundos is None or not tiempo.MINIMO <= segundos <= tiempo.MAXIMO:
            error = "❌ Duración no válida. Ejemplo: <code>30 minutos</code>, <code>2 horas</code>, <code>1 día</code>."
        else:
            escribir(a, e.ruta, segundos)
    elif e.tipo == "texto":
        html = mensaje.text_html if mensaje.text else (mensaje.caption_html if mensaje.caption else None)
        if not html:
            error = "❌ Envía un mensaje de texto."
        else:
            escribir(a, e.ruta + ("texto",), html)
    elif e.tipo == "media":
        media = mensajes.media_de(mensaje)
        if not media:
            error = "❌ Envía una foto, video, GIF, sticker, audio o archivo."
        else:
            escribir(a, e.ruta + ("media",), media)
    elif e.tipo == "botones":
        if not mensaje.text or not mensajes.botones_validos(mensaje.text):
            error = "❌ Formato no válido.\n\n" + mensajes.BOTONES_AYUDA
        else:
            escribir(a, e.ruta + ("botones",), mensaje.text)
    elif e.tipo in ("lista_add", "lista_del"):
        elementos = [_normalizar_excepcion(x) for x in (mensaje.text or "").split() if x.strip()]
        lista = leer(a, e.ruta)
        if e.tipo == "lista_add":
            lista.extend(x for x in elementos if x not in lista)
        else:
            lista[:] = [x for x in lista if x not in elementos]
    if error:
        await mensaje.reply_text(error)
        return True

    db.guardar_ajustes(e.chat_id, a)
    del ESPERAS[(update.effective_chat.id, usuario.id)]
    try:
        await mensaje.delete()
    except (BadRequest, Forbidden):
        pass
    await mostrar(context.bot, e.menu_chat, e.menu_id, e.chat_id, e.vista, editar=True)
    return True


# =====================================================================
# Vistas: Reglamento
# =====================================================================

def v_reglas(c: Ctx):
    texto = (
        "📜 <b>Reglamento</b>\n\nEn esta sección puedes crear y gestionar las normas que regulan la conducta de los "
        "miembros de tu grupo.\n\nUna vez configuradas, los usuarios podrán consultar el reglamento utilizando el "
        "comando:\n<code>/rules</code>\n\nTambién es posible mostrar las reglas mediante botones, incluirlas en el "
        "Captcha o complementar su contenido con mensajes personalizados.\n\n"
        "<blockquote expandable>📚 <b>Todo lo que puedes hacer con las reglas</b>\n\n"
        "<b>BOTONES</b>\nLas reglas pueden mostrarse mediante botones personalizados usando esta sintaxis al crear "
        "el botón:\n<code>Nombre del botón - rules</code>\nAl pulsarlo, el usuario verá el reglamento del grupo.\n\n"
        "<b>CAPTCHA</b>\nPuedes utilizar el tag <code>{RULES}</code>: el bot lo reemplazará por el texto completo de "
        "las reglas.\n\n<b>ARGUMENTOS</b>\nMuestra solo una parte del reglamento con números, palabras o emojis:\n"
        "<code>/rules 1</code> · <code>/rules spam</code>\n\n<b>CONTENIDO DEL MENSAJE</b>\nDesde "
        "<b>Personalizar mensaje</b>: Texto, Multimedia y Teclado (botones).</blockquote>\n\n"
        "📍 <b>Acceso al comando</b>\nConfigura quién puede utilizar <code>/rules</code> desde el botón "
        "🔏 <b>Permisos de comandos</b> o mediante la ruta:\n<code>Settings ➜ ▶️ Más ➜ 🔏Permisos</code>"
    )
    filas = [[B("✍️ Personalizar mensaje", c.chat_id, "ed.reglas")],
             [VIEJA("🔏 Permisos de comandos", c.chat_id, "permisos")],
             [volver(c.chat_id, "p1")]]
    return texto, filas


# =====================================================================
# Editor de mensajes (Personalizar mensaje)
# =====================================================================

EDITORES = {
    "reglas": (("reglas_msg",), "reglas", "📜 Reglamento"),
    "bienv": (("bienvenida", "mensaje"), "bienv", "💬 Bienvenida"),
    "desp": (("despedida", "mensaje"), "desp", "👋 Despedida"),
    "captcha": (("captcha", "mensaje"), "captcha", "🧠 Captcha"),
}


def v_editor(c: Ctx, clave: str):
    ruta, padre, titulo = EDITORES[clave]
    hecho = mensajes.configurado(leer(c.a, ruta))
    marca = {True: "✅", False: "❌"}
    vista = f"ed.{clave}"
    texto = (f"<b>{titulo}</b>\n\n📄 Texto {marca[hecho['texto']]}\n🖼️ Multimedia {marca[hecho['media']]}\n"
             f"⌨️ Teclado Inline {marca[hecho['botones']]}\n\n👉 Usa los botones a continuación para elegir lo que "
             "deseas configurar")
    filas = [
        [B("📄 Texto", c.chat_id, vista, "i", "texto"), B("👀 Ver", c.chat_id, vista, "ver", "texto")],
        [B("🖼️ Multimedia", c.chat_id, vista, "i", "media"), B("👀 Ver", c.chat_id, vista, "ver", "media")],
        [B("⌨️ Teclado Inline", c.chat_id, vista, "i", "botones"), B("👀 Ver", c.chat_id, vista, "ver", "botones")],
        [B("👀 Vista previa completa", c.chat_id, vista, "prev")],
        [volver(c.chat_id, padre)],
    ]
    return texto, filas


# =====================================================================
# Antispam
# =====================================================================

ORIGENES = [("canales", "📢 Canales"), ("grupos", "👥 Grupos"), ("usuarios", "👤 Usuarios"), ("bots", "🤖 Bots")]


def v_antispam(c: Ctx):
    texto = ("📨 <b>Antispam</b>\nEn este menú puedes decidir si deseas proteger tus grupos de enlaces, reenvíos "
             "y citas innecesarias.")
    filas = [[B("📘 Telegram", c.chat_id, "as.tg")],
             [B("📩 Reenvío", c.chat_id, "as.fw"), B("💭 Citas", c.chat_id, "as.qt")],
             [B("🔗 General de internet", c.chat_id, "as.web")],
             [volver(c.chat_id, "p1")]]
    return texto, filas


def v_as_tg(c: Ctx):
    cfg = c.a["antispam"]["telegram"]
    texto = ("📘 <b>Telegram</b>\nDesde este menú puedes establecer un castigo para los usuarios que envíen mensajes "
             "que contengan <b>Enlaces de Telegram</b>.\n\n🎯 <b>Antispam de usernames</b>: esta opción activa el "
             "antispam cuando se envía un @username considerado spam.\n\n🤖 <b>Antispam de bots</b>: esta opción "
             "activa el antispam cuando se envía un <b>enlace de bot</b>.\n\n" + texto_castigo(cfg))
    filas = filas_castigo(c.chat_id, "as.tg", cfg)
    filas += [[B(f"🎯 Antispam de usernames {SI_NO[cfg['usernames']]}", c.chat_id, "as.tg", "t", "usernames")],
              [B(f"🤖 Antispam de bots {SI_NO[cfg['bots']]}", c.chat_id, "as.tg", "t", "bots")],
              [volver(c.chat_id, "antispam"), B("🔆 Excepciones", c.chat_id, "as.exc")]]
    return texto, filas


def _v_origenes(c: Ctx, clave: str, vista: str, titulo: str, descripcion: str):
    lineas = "\n".join(f"{nombre}\n└ {castigos.describir(c.a['antispam'][clave][k])}" for k, nombre in ORIGENES)
    texto = f"{titulo}\n{descripcion}\n\n{lineas}"
    filas = [[B(ORIGENES[0][1], c.chat_id, f"{vista}.canales"), B(ORIGENES[1][1], c.chat_id, f"{vista}.grupos")],
             [B(ORIGENES[2][1], c.chat_id, f"{vista}.usuarios"), B(ORIGENES[3][1], c.chat_id, f"{vista}.bots")],
             [volver(c.chat_id, "antispam"), B("🔆 Excepciones", c.chat_id, "as.exc")]]
    return texto, filas


def v_as_fw(c: Ctx):
    return _v_origenes(c, "reenvio", "as.fw", "📩 <b>Reenvío</b>",
                       "Desde este menú puedes seleccionar un castigo para cualquier usuario que <b>reenvíe mensajes</b> "
                       "al grupo.\n\nEl Reenvío desde 👥 Grupos bloquea mensajes escritos por un administrador anónimo de "
                       "otro grupo y reenviados a este grupo.")


def v_as_qt(c: Ctx):
    return _v_origenes(c, "citas", "as.qt", "💭 <b>Citas</b>",
                       "Desde este menú puedes seleccionar un castigo para cualquier usuario que envíe mensajes que "
                       "contengan <b>citas de chats externos</b>. Pueden provenir de:")


def _v_origen(c: Ctx, clave: str, origen: str):
    nombre = dict(ORIGENES)[origen]
    cfg = c.a["antispam"][clave][origen]
    que = "reenvíen mensajes de" if clave == "reenvio" else "citen mensajes de"
    vista = f"as.{'fw' if clave == 'reenvio' else 'qt'}.{origen}"
    texto = (f"{nombre}\nCastigo para los usuarios que {que} <b>{nombre.split(' ', 1)[1].lower()}</b>.\n\n"
             + texto_castigo(cfg))
    return texto, filas_castigo(c.chat_id, vista, cfg) + [[volver(c.chat_id, vista.rsplit(".", 1)[0])]]


def v_as_web(c: Ctx):
    cfg = c.a["antispam"]["enlaces"]
    texto = ("🔗 <b>Bloqueo total de enlaces</b>\nDesde este menú puedes establecer un castigo para los usuarios que "
             "envíen cualquier clase de enlace al grupo.\n\n" + texto_castigo(cfg))
    return texto, filas_castigo(c.chat_id, "as.web", cfg) + [
        [volver(c.chat_id, "antispam"), B("🔆 Excepciones", c.chat_id, "as.exc")]]


def v_as_exc(c: Ctx):
    lista = c.a["antispam"]["excepciones"]
    texto = ("🔆 <b>Excepciones Antispam</b>\nEdita aquí los enlaces/@username de canales/grupos de telegram que no "
             "serán considerados como spam.\n\n<i>El enlace de invitación de este grupo está automáticamente en las "
             "excepciones.</i>")
    if c.arg == "lista":
        texto += "\n\n📝 <b>Lista Blanca</b>\n" + ("\n".join(f"• <code>{escape(x)}</code>" for x in lista) or "Vacía")
    filas = [[B("📝 Lista Blanca", c.chat_id, "as.exc", "v", "lista")],
             [B("➕ Añadir", c.chat_id, "as.exc", "i", "lista_add"), B("➖ Eliminar", c.chat_id, "as.exc", "i", "lista_del")],
             [volver(c.chat_id, "antispam")]]
    return texto, filas


# =====================================================================
# Bienvenida y Despedida
# =====================================================================

def v_bienv(c: Ctx):
    b = c.a["bienvenida"]
    if b["modo"] == "siempre":
        modo = "🔔 Siempre\nEnvía el mensaje de bienvenida cada vez que un usuario se une al grupo"
    else:
        modo = "1️⃣ Primera entrada\nEnvía el mensaje de bienvenida solo la primera vez que un usuario se une al grupo"
    texto = ("💬 <b>Mensaje de bienvenida</b>\nDesde este menú puedes configurar un mensaje de bienvenida que se enviará "
             f"cuando alguien se una a este grupo.\n\n<b>Estado:</b> {'Activo ✅' if b['on'] else 'Apagado ❌'}\n"
             f"<b>Modo:</b> {modo}")
    filas = [[B("✖️ Desactivar", c.chat_id, "bienv", "on", 0), B("✔️ Activar", c.chat_id, "bienv", "on", 1)],
             [B("✍️ Personalizar mensaje", c.chat_id, "ed.bienv")],
             [B("🔔 Enviar siempre", c.chat_id, "bienv", "modo", "siempre"),
              B("1️⃣ Enviar 1° entrada", c.chat_id, "bienv", "modo", "primera")],
             [B(f"♻️ Eliminar último mensaje {SI_NO[b['borrar_ultimo']]}", c.chat_id, "bienv", "t", "borrar_ultimo")],
             [volver(c.chat_id, "p1")]]
    return texto, filas


def v_desp(c: Ctx):
    d = c.a["despedida"]
    texto = ("👋 <b>Despedida</b>\nDesde este menú puedes establecer un mensaje de despedida que se enviará cuando "
             f"alguien abandone este grupo.\n\n<b>Estado:</b> {'Activo ✅' if d['on'] else 'Apagado ❌'}")
    filas = [[B("✖️ Desactivar", c.chat_id, "desp", "on", 0), B("✔️ Activar", c.chat_id, "desp", "on", 1)],
             [B("✍️ Personalizar mensaje", c.chat_id, "ed.desp")],
             [B(f"💌 Enviar en chat privado {SI_NO[d['privado']]}", c.chat_id, "desp", "t", "privado")],
             [B(f"♻️ Eliminar último mensaje {SI_NO[d['borrar_ultimo']]}", c.chat_id, "desp", "t", "borrar_ultimo")],
             [volver(c.chat_id, "p1")]]
    return texto, filas


# =====================================================================
# Anti-flood
# =====================================================================

REJILLA = [[2, 3, 4, 5], [6, 7, 8, 9], [10, 12, 15, 20]]


def v_flood(c: Ctx):
    f = c.a["antiflood"]
    texto = ("🗣️ <b>Anti-flood</b>\nDesde este menú puedes establecer un castigo para quienes envíen muchos mensajes "
             "en poco tiempo.\n\nActualmente el antiflood (anti-inundación) se activa si se envían:\n"
             f"<blockquote>{f['mensajes']} mensajes en {f['segundos']} segundos.</blockquote>\n\n"
             + texto_castigo(f["castigo"], con_eliminacion=False))
    filas = [[B("📄 Mensajes", c.chat_id, "fl.n"), B("🕐 Tiempo", c.chat_id, "fl.t")]]
    filas += filas_castigo(c.chat_id, "flood", f["castigo"])
    filas.append([volver(c.chat_id, "p1")])
    return texto, filas


def _v_rejilla(c: Ctx, clave: str, vista: str, titulo: str, descripcion: str):
    f = c.a["antiflood"]
    texto = (f"{titulo}\n\n{descripcion}\n\nActualmente se activa cuando se envían:\n"
             f"<blockquote>{f['mensajes']} mensajes en {f['segundos']} segundos.</blockquote>")
    filas = [[B(f"{n}{' ✅' if f[clave] == n else ''}", c.chat_id, vista, "n", n) for n in fila] for fila in REJILLA]
    filas.append([volver(c.chat_id, "flood")])
    return texto, filas


def v_fl_n(c: Ctx):
    return _v_rejilla(c, "mensajes", "fl.n", "📄 <b>Cantidad de Mensajes</b>",
                      "Desde aquí puedes establecer la <b>cantidad mínima</b> de mensajes para activar el <b>antiflood</b>.")


def v_fl_t(c: Ctx):
    return _v_rejilla(c, "segundos", "fl.t", "🕐 <b>Intervalo de Tiempo</b>",
                      "Desde aquí puedes establecer el <b>intervalo de tiempo</b> para activar el <b>antiflood</b> si "
                      "se envían mensajes de forma masiva.")


# =====================================================================
# Alfabetos
# =====================================================================

ALFABETOS = [("arabe", "☪️ Árabe", "ÁRABE"), ("cirilico", "🇷🇺 Cirílico", "CIRÍLICO"), ("chino", "🇨🇳 Chino", "CHINO"),
             ("latino", "🔤 Latino", "LATINO"), ("hindi", "🇮🇳 Hindi", "HINDI"), ("bengali", "🇧🇩 Bengalí", "BENGALÍ")]


def v_alfa(c: Ctx):
    lineas = "\n\n".join(f"{nombre}\n└ <b>Estado:</b> {castigos.describir(c.a['alfabetos'][k])}"
                         for k, nombre, _ in ALFABETOS)
    texto = ("🕉️ <b>Alfabetos</b>\nDesde este menú puedes seleccionar un castigo para cualquier usuario que envíe "
             "mensajes escritos en los alfabetos: Árabe, Cirílico, Chino, Latino, Hindi (Devanagari) y Bengalí:\n\n"
             + lineas)
    botones = [B(f"{nombre.split(' ')[0]} {mayus}", c.chat_id, f"alfa.{k}") for k, nombre, mayus in ALFABETOS]
    filas = [botones[i:i + 2] for i in range(0, 6, 2)] + [[volver(c.chat_id, "p1")]]
    return texto, filas


def _v_alfabeto(c: Ctx, clave: str):
    nombre = next(n for k, n, _ in ALFABETOS if k == clave)
    cfg = c.a["alfabetos"][clave]
    texto = (f"{nombre}\nDesde este menú puedes establecer un castigo para los usuarios que envíen mensajes escritos "
             f"en alfabeto <b>{nombre.split(' ', 1)[1].lower()}</b>.\n\n" + texto_castigo(cfg))
    return texto, filas_castigo(c.chat_id, f"alfa.{clave}", cfg) + [[volver(c.chat_id, "alfa")]]


# =====================================================================
# Captcha
# =====================================================================

MODOS = [("boton", "Botón", "El usuario deberá presionar un botón para verificar su ingreso.\n<i>Es un captcha simple, pero menos seguro.</i>"),
         ("recaptcha", "reCaptcha", "El usuario deberá verificarse en el chat privado del bot antes de poder escribir.\n<i>Más seguro que el botón.</i>"),
         ("presentacion", "Presentación", "El usuario deberá enviar un mensaje de presentación en el grupo dentro del tiempo establecido."),
         ("reglamento", "Reglamento", "El usuario deberá leer y aceptar el reglamento del grupo para poder escribir."),
         ("matematicas", "Matemáticas", "El usuario deberá resolver una operación matemática sencilla."),
         ("prueba", "Prueba", "El usuario deberá elegir el emoji correcto entre varias opciones.")]
TIEMPOS = [[(15, "15 sec."), (30, "30 sec.")], [(60, "1"), (120, "2"), (180, "3"), (300, "5")],
           [(600, "10"), (900, "15"), (1200, "20"), (1800, "30")]]
NOMBRE_FALLO = {"ban": "Ban", "mute": "Silenciar", "kick": "Kick"}
NUMEROS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]


def v_captcha(c: Ctx):
    cap = c.a["captcha"]
    intro = ("🧠 <b>Captcha</b>\nAl activar el captcha, cuando un usuario ingrese al grupo <b>no podrá enviar mensajes</b> "
             "hasta que haya confirmado que <b>no es un robot</b>.\n\n🕑 También puedes decidir un <b>CASTIGO</b> en caso de "
             "que no resuelva el captcha dentro del <b>tiempo establecido</b> a continuación y si se borrará o no el "
             "mensaje de servicio en caso de fallar al completarla.\n\n")
    if not cap["on"]:
        return intro + "<b>Estado:</b> Apagado ❌", [[B("✅ Activar", c.chat_id, "captcha", "on", 1)],
                                                    [volver(c.chat_id, "p1")]]
    nombre_modo, desc_modo = next((n, d) for k, n, d in MODOS if k == cap["modo"])
    texto = (intro + f"<b>Estado:</b> Activo ✅\n🕑 <b>Tiempo:</b> {tiempo.escribir(cap['tiempo'])}\n"
             f"⛔ <b>Castigo:</b> {NOMBRE_FALLO[cap['castigo']]}\n🔲 <b>Modo:</b> {nombre_modo}\n└ {desc_modo}\n\n"
             f"🗑️ <b>Eliminar mensaje de servicio:</b> {'Activo' if cap['borrar_servicio'] else 'Apagado'}")
    abierto = c.arg
    filas = [[B("❌ Desactivar ❌", c.chat_id, "captcha", "on", 0)]]
    filas.append([B("» 🔲 Modo 🔲 «" if abierto == "modo" else "🔲 Modo 🔲", c.chat_id, "captcha", "v",
                    "" if abierto == "modo" else "modo")])
    if abierto == "modo":
        botones = [B(f"{'✅' if k == cap['modo'] else NUMEROS[i]} {n}", c.chat_id, "captcha", "modo", k)
                   for i, (k, n, _) in enumerate(MODOS)]
        filas += [botones[i:i + 2] for i in range(0, 6, 2)]
    filas.append([B("» 🕑 Tiempo (Minutos) 🕑 «" if abierto == "tiempo" else "🕑 Tiempo 🕑", c.chat_id, "captcha", "v",
                    "" if abierto == "tiempo" else "tiempo")])
    if abierto == "tiempo":
        filas += [[B(f"{t}{'✅' if s == cap['tiempo'] else ''}", c.chat_id, "captcha", "tiempo", s) for s, t in fila]
                  for fila in TIEMPOS]
    filas.append([B("» ⛔ Castigo ⛔ «" if abierto == "castigo" else "⛔ Castigo ⛔", c.chat_id, "captcha", "v",
                    "" if abierto == "castigo" else "castigo")])
    if abierto == "castigo":
        def f(k, e):
            return B(f"{e} {NOMBRE_FALLO[k]}{' ✅' if cap['castigo'] == k else ''}", c.chat_id, "captcha", "fallo", k)
        filas += [[f("ban", "🚷")], [f("mute", "🔇"), f("kick", "❗")]]
    filas += [[B("✍️ Personalizar mensaje ✍️", c.chat_id, "ed.captcha")],
              [VIEJA("📁 Selecciona un tema 🆕", c.chat_id, "temas")],
              [B(f"🗑️ Eliminar mensaje de servicio {SI_NO[cap['borrar_servicio']]}", c.chat_id, "captcha", "t",
                 "borrar_servicio")],
              [volver(c.chat_id, "p1")]]
    return texto, filas


# =====================================================================
# Página 2: Gestión de canales y Extras de Danny Phantom
# =====================================================================

def v_canales(c: Ctx):
    texto = ("📢 <b>Gestión de canales</b>\nControla todo lo que llega a tu grupo desde canales:\n\n"
             "• Reenvíos de canales (Antispam ➜ Reenvío)\n• Usuarios que escriben como canal\n"
             "• Publicaciones del canal vinculado (Grupo de discusión)")
    filas = [[B("📢 Reenvíos de canales", c.chat_id, "as.fw.canales")],
             [VIEJA("😶‍🌫️ Usuarios enmascarados", c.chat_id, "enmascarados")],
             [VIEJA("📣 Grupo de discusión", c.chat_id, "discusion")],
             [volver(c.chat_id, "p2")]]
    return texto, filas


def v_extras(c: Ctx):
    texto = ("👻 <b>Extras de Danny Phantom</b>\nFunciones propias de Danny Phantom que Group Help no tiene "
             "(o que allí son de pago).\n\n"
             f"🤖 <b>IA en el grupo:</b> {'Activa ✅' if c.a['ia'] else 'Apagada ❌'}\n"
             "└ Contesta cuando la mencionan o le responden.")
    filas = [[B(f"🤖 IA en el grupo {SI_NO[c.a['ia']]}", c.chat_id, "extras", "ia")],
             [VIEJA("👮 Guardián IA (estafas y spam)", c.chat_id, "guardian")],
             [VIEJA("🔞 Antiporno IA", c.chat_id, "antiporno")],
             [VIEJA("🐒 Stickers automáticos", c.chat_id, "stickers")],
             [VIEJA("📣 Mencionar a todos (/tagall)", c.chat_id, "etiqueta")],
             [volver(c.chat_id, "p2")]]
    return texto, filas


# =====================================================================
# Registro de vistas y rutas de castigo
# =====================================================================

def vista_de(nombre: str):
    if nombre.startswith("ed."):
        return lambda c: v_editor(c, nombre[3:])
    if nombre.startswith("alfa."):
        return lambda c: _v_alfabeto(c, nombre[5:])
    if nombre.startswith(("as.fw.", "as.qt.")):
        clave = "reenvio" if nombre.startswith("as.fw.") else "citas"
        return lambda c: _v_origen(c, clave, nombre[6:])
    return {
        "reglas": v_reglas, "antispam": v_antispam, "as.tg": v_as_tg, "as.fw": v_as_fw, "as.qt": v_as_qt,
        "as.web": v_as_web, "as.exc": v_as_exc, "bienv": v_bienv, "desp": v_desp, "flood": v_flood,
        "fl.n": v_fl_n, "fl.t": v_fl_t, "alfa": v_alfa, "captcha": v_captcha, "canales": v_canales,
        "extras": v_extras,
    }.get(nombre)


def ruta_castigo(vista: str) -> tuple | None:
    if vista == "as.tg":
        return ("antispam", "telegram")
    if vista == "as.web":
        return ("antispam", "enlaces")
    if vista.startswith("as.fw."):
        return ("antispam", "reenvio", vista[6:])
    if vista.startswith("as.qt."):
        return ("antispam", "citas", vista[6:])
    if vista.startswith("alfa."):
        return ("alfabetos", vista[5:])
    if vista == "flood":
        return ("antiflood", "castigo")
    return None


# Interruptores simples: vista -> ruta base donde vive la clave del interruptor
BASE_INTERRUPTOR = {"as.tg": ("antispam", "telegram"), "bienv": ("bienvenida",), "desp": ("despedida",),
                    "captcha": ("captcha",)}


# =====================================================================
# Mostrar y manejar botones
# =====================================================================

async def titulo_de(bot, chat_id: int) -> str:
    g = db.grupo(chat_id)
    if g and g.get("titulo"):
        return g["titulo"]
    try:
        return (await bot.get_chat(chat_id)).title or str(chat_id)
    except Exception:
        return str(chat_id)


async def render(bot, chat_id: int, vista: str, arg: str = "") -> tuple[str, Teclado]:
    titulo = await titulo_de(bot, chat_id)
    if vista in ("p1", "p2", "main"):
        return texto_pagina(titulo), teclado_pagina(chat_id, 1 if vista == "p2" else 0)
    funcion = vista_de(vista)
    texto, filas = funcion(Ctx(chat_id, titulo, db.ajustes(chat_id), arg))
    return texto, Teclado(filas)


async def mostrar(bot, menu_chat: int, menu_id: int, chat_id: int, vista: str, arg: str = "", editar: bool = True):
    texto, teclado = await render(bot, chat_id, vista, arg)
    try:
        if editar:
            await bot.edit_message_text(texto, chat_id=menu_chat, message_id=menu_id, reply_markup=teclado)
            return
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
    await bot.send_message(menu_chat, texto, reply_markup=teclado)


async def es_admin(bot, chat_id: int, user_id: int) -> bool:
    return nivel((await staff(bot, chat_id)).get(user_id)) >= NIVELES["admin"]


async def manejar(update: Update, context: ContextTypes.DEFAULT_TYPE, partes: list[str]):
    q = update.callback_query
    chat_id, vista, op, args = int(partes[0]), partes[1], partes[2] if len(partes) > 2 else "v", partes[3:]
    if not await es_admin(context.bot, chat_id, q.from_user.id):
        await q.answer("⛔ Solo los administradores pueden cambiar los ajustes.", show_alert=True)
        return
    clave_espera = (q.message.chat.id, q.from_user.id)

    if op == "cerrar":
        ESPERAS.pop(clave_espera, None)
        try:
            await q.message.delete()
        except (BadRequest, Forbidden):
            pass
        await q.answer("Configuración cerrada.")
        return
    if op == "lang":
        await q.answer("🇪🇸 Por ahora hablo solo español.", show_alert=True)
        return

    a = db.ajustes(chat_id)
    aviso, arg = None, ""
    if op == "v":
        arg = args[0] if args else ""
    elif op == "x":
        ESPERAS.pop(clave_espera, None)
    elif op == "z":
        e = ESPERAS.pop(clave_espera, None)
        if e:
            if e.tipo in ("dur_mute", "dur_ban"):
                escribir(a, e.ruta, 0)
            elif e.tipo in ("texto", "media", "botones"):
                escribir(a, e.ruta + (e.tipo,), None if e.tipo == "media" else "")
            db.guardar_ajustes(chat_id, a)
            aviso = "🗑️ Eliminado"
    elif op in ("k", "kb", "kd"):
        ruta = ruta_castigo(vista)
        cfg = leer(a, ruta)
        if op == "k":
            cfg["accion"] = args[0]
            if args[0] == "mute" and not cfg["dur_mute"]:
                cfg["dur_mute"] = 1800
        elif op == "kb":
            cfg["borrar"] = not cfg["borrar"]
        else:
            ESPERAS[clave_espera] = Espera(chat_id, f"dur_{args[0]}", ruta + (f"dur_{args[0]}",), vista,
                                           q.message.chat.id, q.message.message_id)
            texto, filas = texto_espera(ESPERAS[clave_espera], a)
            await q.edit_message_text(texto, reply_markup=Teclado(filas))
            await q.answer()
            return
        db.guardar_ajustes(chat_id, a)
        aviso = "✅ Guardado"
    elif op == "i":
        tipo = args[0]
        ruta = EDITORES[vista[3:]][0] if vista.startswith("ed.") else ("antispam", "excepciones")
        ESPERAS[clave_espera] = Espera(chat_id, tipo, ruta, vista, q.message.chat.id, q.message.message_id)
        texto, filas = texto_espera(ESPERAS[clave_espera], a)
        await q.edit_message_text(texto, reply_markup=Teclado(filas))
        await q.answer()
        return
    elif op in ("ver", "prev"):
        m = leer(a, EDITORES[vista[3:]][0])
        parcial = dict(mensajes.vacio())
        if op == "prev":
            parcial = m
        else:
            parcial[args[0]] = m.get(args[0])
        reglas = a["reglas_msg"]["texto"]
        chat = await context.bot.get_chat(chat_id)
        enviado = await mensajes.enviar(context.bot, q.message.chat.id, parcial, q.from_user, chat, reglas)
        await q.answer(None if enviado else "📭 Esa parte está vacía.", show_alert=not enviado)
        return
    elif op == "t":
        base = BASE_INTERRUPTOR[vista]
        escribir(a, base + (args[0],), not leer(a, base + (args[0],)))
        db.guardar_ajustes(chat_id, a)
        aviso = "✅ Guardado"
    elif op == "on":
        escribir(a, BASE_INTERRUPTOR[vista] + ("on",), args[0] == "1")
        db.guardar_ajustes(chat_id, a)
        aviso = "✅ Guardado"
    elif op == "modo" and vista == "bienv":
        a["bienvenida"]["modo"] = args[0]
        db.guardar_ajustes(chat_id, a)
        aviso = "✅ Guardado"
    elif op in ("modo", "tiempo", "fallo") and vista == "captcha":
        clave = {"modo": "modo", "tiempo": "tiempo", "fallo": "castigo"}[op]
        a["captcha"][clave] = int(args[0]) if op == "tiempo" else args[0]
        db.guardar_ajustes(chat_id, a)
        arg = {"modo": "modo", "tiempo": "tiempo", "fallo": "castigo"}[op]
        aviso = "✅ Guardado"
    elif op == "n" and vista in ("fl.n", "fl.t"):
        a["antiflood"]["mensajes" if vista == "fl.n" else "segundos"] = int(args[0])
        db.guardar_ajustes(chat_id, a)
        aviso = "✅ Guardado"
    elif op == "ia" and vista == "extras":
        a["ia"] = not a["ia"]
        db.guardar_ajustes(chat_id, a)
        aviso = "✅ Guardado"

    texto, teclado = await render(context.bot, chat_id, vista, arg)
    try:
        await q.edit_message_text(texto, reply_markup=teclado)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise
    await q.answer(aviso)
