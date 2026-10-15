"""Menú de configuración del grupo (/settings), con las mismas secciones que Group Help.

callback_data:
  cfg:<chat>:m:<página>         menú principal (página 0 o 1)
  cfg:<chat>:s:<sección>        abrir una sección
  cfg:<chat>:x:<sección>:<n>[:<+|->]   cambiar el control n de una sección
  cfg:<chat>:lang · cfg:<chat>:nada
"""
from dataclasses import dataclass, field
from html import escape

from telegram import InlineKeyboardButton as Boton, InlineKeyboardMarkup as Teclado, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

import db
from castigos import ACCIONES, NOMBRE_ACCION
from permisos import NIVELES, nivel, staff, texto_duracion

ZONAS = [
    ("America/Puerto_Rico", "🇵🇷 Puerto Rico"), ("America/New_York", "🇺🇸 Nueva York"),
    ("America/Mexico_City", "🇲🇽 México"), ("America/Bogota", "🇨🇴 Colombia"),
    ("America/Lima", "🇵🇪 Perú"), ("America/Caracas", "🇻🇪 Venezuela"),
    ("America/Santiago", "🇨🇱 Chile"), ("America/Argentina/Buenos_Aires", "🇦🇷 Argentina"),
    ("Europe/Madrid", "🇪🇸 España"),
]
SIN_OFF = [a for a in ACCIONES if a != "off"]
AL_ENTRAR = ["off", "mute", "kick", "ban"]


@dataclass
class Control:
    tipo: str            # interruptor | accion | numero | opcion
    ruta: tuple
    etiqueta: str
    opciones: list = field(default_factory=list)   # accion: lista de acciones; opcion: [(valor, texto)]
    minimo: int = 0
    maximo: int = 0
    paso: int = 1
    sufijo: str = ""
    cero: str | None = None   # texto a mostrar cuando el número vale 0


def I(ruta, etiqueta):
    return Control("interruptor", ruta, etiqueta)


def A(ruta, etiqueta, acciones=ACCIONES):
    return Control("accion", ruta, etiqueta, opciones=list(acciones))


def N(ruta, etiqueta, minimo, maximo, paso=1, sufijo="", cero=None):
    return Control("numero", ruta, etiqueta, minimo=minimo, maximo=maximo, paso=paso, sufijo=sufijo, cero=cero)


def O(ruta, etiqueta, opciones):
    return Control("opcion", ruta, etiqueta, opciones=opciones)


@dataclass
class Seccion:
    boton: str
    titulo: str
    descripcion: object          # str o función(ajustes) -> str
    controles: list = field(default_factory=list)


def _lista(elementos, vacio="ninguno") -> str:
    return ", ".join(f"<code>{escape(str(e))}</code>" for e in elementos) or vacio


def _recorte(texto: str, n: int = 300) -> str:
    texto = texto or ""
    return escape(texto[:n] + ("…" if len(texto) > n else ""))


SECCIONES: dict[str, Seccion] = {
    "reglas": Seccion("📜 Reglamento", "📜 Reglamento", lambda a: (
        f"Reglas actuales:\n<i>{_recorte(a['reglas']) or 'todavía no hay reglas'}</i>\n\n"
        "✏️ Cámbialas con <code>/setrules texto</code>"),
        [I(("permisos", "rules"), "Cualquiera puede usar /rules")]),
    "antispam": Seccion("📨 Antispam", "📨 Antispam",
        "Frena el spam más común. Elige qué hacer con cada tipo de mensaje.",
        [A(("antispam", "telegram"), "Enlaces de Telegram"),
         A(("antispam", "reenvios_canal"), "Reenvíos de canales"),
         A(("antispam", "enlaces"), "Cualquier enlace")]),
    "bienvenida": Seccion("💬 Bienvenida", "💬 Bienvenida", lambda a: (
        f"Mensaje actual:\n<i>{_recorte(a['bienvenida']['texto'])}</i>\n\n"
        "✏️ Cámbialo con <code>/setwelcome texto</code>\n"
        "Variables: {nombre}, {usuario}, {id}, {grupo}"),
        [I(("bienvenida", "on"), "Bienvenida"),
         I(("bienvenida", "borrar_anterior"), "Borrar la bienvenida anterior"),
         N(("bienvenida", "autoborrar"), "Borrar tras", 0, 60, sufijo=" min", cero="nunca")]),
    "antiflood": Seccion("🗣️ Anti-flood", "🗣️ Anti-flood",
        "Castiga a quien manda muchos mensajes seguidos en poco tiempo.",
        [I(("antiflood", "on"), "Anti-flood"),
         N(("antiflood", "mensajes"), "Mensajes", 2, 30),
         N(("antiflood", "segundos"), "En segundos", 1, 60),
         A(("antiflood", "accion"), "Castigo", SIN_OFF),
         I(("antiflood", "borrar"), "Borrar los mensajes del flood")]),
    "despedida": Seccion("👋 Despedida", "👋 Despedida", lambda a: (
        f"Mensaje actual:\n<i>{_recorte(a['despedida']['texto'])}</i>\n\n"
        "✏️ Cámbialo con <code>/setgoodbye texto</code>"),
        [I(("despedida", "on"), "Despedida")]),
    "alfabetos": Seccion("🕉️ Alfabetos", "🕉️ Alfabetos",
        "Castiga los mensajes escritos con estos alfabetos (útil contra bots de spam extranjeros).",
        [A(("alfabetos", "arabe"), "Árabe"), A(("alfabetos", "cirilico"), "Cirílico"),
         A(("alfabetos", "chino"), "Chino"), A(("alfabetos", "latino"), "Latino")]),
    "captcha": Seccion("🧠 Captcha", "🧠 Captcha",
        "Los nuevos miembros quedan silenciados hasta demostrar que no son bots.",
        [I(("captcha", "on"), "Captcha"),
         N(("captcha", "minutos"), "Tiempo", 1, 30, sufijo=" min"),
         O(("captcha", "modo"), "Tipo", [("boton", "👆 Botón"), ("mates", "🧮 Suma")]),
         O(("captcha", "fallo"), "Si no lo resuelve", [("kick", "🌀 Expulsar"), ("ban", "👻 Banear"),
                                                       ("mute", "🔇 Dejar silenciado")])]),
    "filtros": Seccion("🔦 Filtros", "🔦 Filtros (respuestas automáticas)", lambda a: (
        f"Palabras con respuesta: {_lista(sorted(a['filtros']))}\n\n"
        "✏️ <code>/filtro palabra respuesta</code> · <code>/unfiltro palabra</code>"),
        [I(("filtros_on",), "Respuestas automáticas")]),
    "reportes": Seccion("🆘 Reportes", "🆘 Reportes",
        "Cuando alguien escribe @admin o /report, aviso al staff.",
        [I(("reportes", "on"), "Reportes"),
         O(("reportes", "destino"), "Avisar", [("grupo", "💬 En el grupo"), ("privado", "📬 Por privado"),
                                              ("ambos", "💬+📬 Ambos")])]),
    "bloqueos": Seccion("🔐 Bloqueos", "🔐 Bloqueos", "Bloquea tipos de mensajes y bots no deseados.",
        [I(("bloqueos", "bots"), "Expulsar bots que no añada un admin"),
         A(("bloqueos", "reenvios"), "Mensajes reenviados"),
         A(("bloqueos", "via_bot"), "Mensajes de bots inline")]),
    "multimedia": Seccion("📸 Multimedia", "📸 Multimedia", "Elige qué hacer con cada tipo de contenido.",
        [A(("multimedia", t), e) for t, e in [
            ("foto", "Fotos"), ("video", "Videos"), ("sticker", "Stickers"), ("gif", "GIFs"),
            ("audio", "Audios"), ("voz", "Notas de voz"), ("videonota", "Videomensajes"),
            ("documento", "Archivos"), ("encuesta", "Encuestas"), ("contacto", "Contactos"),
            ("ubicacion", "Ubicaciones"), ("dado", "Dados y juegos")]]),
    "antiporno": Seccion("🔞 Antiporno", "🔞 Antiporno",
        "🧪 <i>Experimental.</i> La IA revisa fotos y stickers y castiga el contenido sexual explícito. "
        "Usa tu clave de Gemini en cada imagen.",
        [I(("antiporno", "on"), "Antiporno"), A(("antiporno", "accion"), "Castigo", SIN_OFF)]),
    "advertencias": Seccion("❗ Advertencias", "❗ Advertencias",
        "Qué pasa cuando alguien llega al límite de advertencias (/warn).",
        [N(("warn_limite",), "Límite", 1, 10),
         O(("warn_castigo",), "Castigo", [("ban", "👻 Banear"), ("kick", "🌀 Expulsar"), ("mute", "🔇 Silenciar")]),
         N(("warn_dias",), "Duración", 0, 30, sufijo=" días", cero="para siempre")]),
    "nocturno": Seccion("🌙 Modo nocturno", "🌙 Modo nocturno",
        "Durante la noche, solo el staff puede escribir (o nadie puede enviar multimedia).",
        [I(("nocturno", "on"), "Modo nocturno"),
         N(("nocturno", "inicio"), "Empieza", 0, 23, sufijo=":00"),
         N(("nocturno", "fin"), "Termina", 0, 23, sufijo=":00"),
         O(("nocturno", "modo"), "Modo", [("silencio", "🤫 Solo el staff"), ("multimedia", "🖼️ Sin multimedia")]),
         O(("nocturno", "zona"), "Zona horaria", ZONAS)]),
    "etiqueta": Seccion("🛎️ Etiqueta", "🛎️ Etiqueta",
        "Menciona a todos los miembros que conozco con <code>/tagall texto</code> o escribiendo @all.",
        [I(("etiqueta", "on"), "Etiquetar a todos"),
         O(("etiqueta", "quien"), "Quién puede", [("admins", "⚡ Solo admins"), ("todos", "👥 Todos")])]),
    "enlace": Seccion("🔗 Enlace del grupo", "🔗 Enlace del grupo", lambda a: (
        f"Enlace personalizado: {escape(a['enlace']['personalizado']) or 'no (uso el de invitación)'}\n\n"
        "✏️ <code>/setlink https://t.me/...</code> · <code>/setlink off</code>"),
        [I(("permisos", "link"), "Cualquiera puede usar /link")]),
    "guardian": Seccion("👮 Bot Guardián", "👮 Bot Guardián 🆕",
        "🧪 <i>Experimental.</i> La IA revisa los primeros mensajes de cada persona y frena estafas, "
        "spam y ataques antes de que hagan daño.",
        [I(("guardian", "on"), "Bot Guardián"),
         N(("guardian", "primeros"), "Revisar los primeros", 1, 50, sufijo=" mensajes"),
         A(("guardian", "accion"), "Castigo", SIN_OFF)]),
    "aprobacion": Seccion("📬 Modo de aprobación", "📬 Modo de aprobación",
        "Para grupos con <b>solicitudes para unirse</b> activadas en Telegram.",
        [O(("aprobacion", "modo"), "Solicitudes", [
            ("off", "❌ Las revisan los admins"), ("auto", "✅ Aprobar a todos"),
            ("captcha", "🧩 Aprobar tras captcha por privado")])]),
    "eliminacion": Seccion("🗑️ Eliminación Mensajes", "🗑️ Eliminación de mensajes",
        "Mantén el chat limpio borrando mensajes automáticos.",
        [I(("eliminar", "entradas"), "Avisos de «se unió»"),
         I(("eliminar", "salidas"), "Avisos de «salió»"),
         I(("eliminar", "fijados"), "Avisos de «fijó un mensaje»"),
         I(("eliminar", "comandos"), "Comandos ya usados"),
         N(("eliminar", "bot_min"), "Borrar mis respuestas tras", 0, 60, sufijo=" min", cero="nunca")]),
    # ---- Página 2 ----
    "temas": Seccion("🗂️ Temas / Topics", "🗂️ Temas / Topics", lambda a: (
        f"Tema para bienvenidas y avisos: {('#' + str(a['temas']['avisos'])) if a['temas']['avisos'] else 'el general'}\n\n"
        "✏️ Escribe <code>/settopic</code> dentro de un tema para usarlo. <code>/settopic off</code> para quitarlo.")),
    "palabras": Seccion("🔤 Palabras Prohibidas", "🔤 Palabras prohibidas", lambda a: (
        f"Palabras: {_lista(a['palabras'])}\n\n"
        "✏️ <code>/blacklist palabra</code> · <code>/unblacklist palabra</code>"),
        [A(("palabras_castigo",), "Castigo", SIN_OFF)]),
    "recurrentes": Seccion("🕐 Mensajes Recurrentes", "🕐 Mensajes recurrentes", lambda a: (
        ("\n".join(f"{i}. cada {texto_duracion(r['segundos'])}: <i>{_recorte(r['texto'], 60)}</i>"
                   for i, r in enumerate(a["recurrentes"], 1)) or "No hay mensajes recurrentes.")
        + "\n\n✏️ <code>/recurrente 6h texto</code> · <code>/unrecurrente número</code>")),
    "miembros": Seccion("👥 Gestión de Miembros", "👥 Gestión de miembros",
        "Revisa a cada persona que entra al grupo.",
        [A(("miembros", "sin_username"), "Sin @usuario", AL_ENTRAR),
         A(("miembros", "sin_foto"), "Sin foto de perfil", AL_ENTRAR)]),
    "enmascarados": Seccion("😶‍🌫️ Usuarios enmascarados", "😶‍🌫️ Usuarios enmascarados",
        "Mensajes enviados «como un canal» para esconder quién escribe.",
        [O(("enmascarados", "accion"), "Acción", [("off", "❌ Apagado"), ("borrar", "🗑️ Borrar"),
                                                 ("ban", "👻 Banear el canal")]),
         I(("enmascarados", "permitir_vinculado"), "Permitir el canal vinculado")]),
    "discusion": Seccion("📣 Grupo de discusión", "📣 Grupo de discusión 🆕",
        "Para grupos de comentarios de un canal: qué hacer con las publicaciones que llegan del canal.",
        [I(("discusion", "desfijar"), "Desfijarlas automáticamente"),
         I(("discusion", "borrar"), "Borrarlas")]),
    "personales": Seccion("📱 Comandos Personales", "📱 Comandos personales", lambda a: (
        f"Comandos: {_lista('/' + n for n in sorted(a['alias']))}\n\n"
        "✏️ <code>/personal nombre texto</code> · <code>/unpersonal nombre</code>"),
        [I(("alias_solo_admins",), "Solo el staff puede usarlos")]),
    "magicos": Seccion("🎭 Stickers & GIFs Mágicos", "🎭 Stickers y GIFs mágicos", lambda a: (
        f"Mágicos guardados: {len(a['magicos'])}\n\n"
        "Responde a un sticker o GIF con <code>/magic ban</code> (o cualquier comando). Desde entonces, "
        "cuando un admin lo envíe respondiendo a alguien, hago ese comando.\n"
        "✏️ <code>/unmagic</code> respondiendo al sticker para quitarlo.")),
    "longitud": Seccion("📏 Longitud de Mensajes", "📏 Longitud de mensajes",
        "Castiga los mensajes demasiado largos o demasiado cortos.",
        [N(("longitud", "max"), "Máximo", 0, 4000, paso=100, sufijo=" letras", cero="sin límite"),
         N(("longitud", "min"), "Mínimo", 0, 20, sufijo=" letras", cero="sin límite"),
         A(("longitud", "accion"), "Castigo", SIN_OFF)]),
    "canales": Seccion("📢 Gestión de canales", "📢 Gestión de canales 🆕",
        "Controla lo que llega al grupo desde canales.",
        [A(("antispam", "reenvios_canal"), "Reenvíos de canales"),
         O(("enmascarados", "accion"), "Escribir como canal", [("off", "❌ Permitido"), ("borrar", "🗑️ Borrar"),
                                                              ("ban", "👻 Banear el canal")]),
         I(("enmascarados", "permitir_vinculado"), "Permitir el canal vinculado")]),
    "permisos": Seccion("✍️ Permisos", "✍️ Permisos",
        "Qué comandos pueden usar los miembros normales. El staff siempre puede usarlos todos.",
        [I(("permisos", c), f"/{c}") for c in ("rules", "staff", "link", "top10", "ia", "me", "report", "game")]),
    "registro": Seccion("🔍 Canal de registro", "🔍 Canal de registro", lambda a: (
        f"Canal actual: {('<code>' + str(a['registro']['chat_id']) + '</code>') if a['registro']['chat_id'] else 'ninguno'}\n\n"
        "1. Añádeme como admin a un canal o grupo privado.\n"
        "2. Escribe ahí <code>/id</code> para ver su ID.\n"
        "3. Aquí en el grupo: <code>/setlog ID</code> (o <code>/setlog off</code>)."),
        [I(("registro", "on"), "Registrar sanciones")]),
}

PAGINAS = [
    [["reglas", "antispam"], ["bienvenida", "antiflood"], ["despedida", "alfabetos"], ["captcha", "filtros"],
     ["reportes", "bloqueos"], ["multimedia", "antiporno"], ["advertencias", "nocturno"], ["etiqueta", "enlace"],
     ["guardian"], ["aprobacion"], ["eliminacion"]],
    [["temas"], ["palabras"], ["recurrentes"], ["miembros"], ["enmascarados"], ["discusion"], ["personales"],
     ["magicos"], ["longitud"], ["canales"], ["permisos", "registro"]],
]


# ---------- Lectura y escritura por ruta ----------

def leer(a: dict, ruta: tuple):
    valor = a
    for clave in ruta:
        valor = valor[clave]
    return valor


def escribir(a: dict, ruta: tuple, valor):
    destino = a
    for clave in ruta[:-1]:
        destino = destino[clave]
    destino[ruta[-1]] = valor


def valor_legible(control: Control, valor) -> str:
    if control.tipo == "interruptor":
        return "✅" if valor else "❌"
    if control.tipo == "accion":
        return NOMBRE_ACCION[valor]
    if control.tipo == "numero":
        return control.cero if (valor == 0 and control.cero) else f"{valor}{control.sufijo}"
    return dict(control.opciones).get(valor, str(valor))


# ---------- Pantallas ----------

def texto_menu(titulo_grupo: str) -> str:
    return (f"⚙️ <b>CONFIGURACIÓN</b>\n<b>Grupo:</b> {escape(titulo_grupo)}\n\n"
            "<i>Elige cuál de los ajustes quieres editar.</i>")


def teclado_menu(chat_id: int, pagina: int) -> Teclado:
    filas = [[Boton(SECCIONES[s].boton, callback_data=f"cfg:{chat_id}:s:{s}") for s in fila]
             for fila in PAGINAS[pagina]]
    idioma = Boton("🇪🇸 Lang", callback_data=f"cfg:{chat_id}:lang")
    cerrar = Boton("✅ Cerrar", callback_data=f"cfg:{chat_id}:cerrar")
    if pagina == 0:
        filas.append([idioma, cerrar, Boton("▶️ Más", callback_data=f"cfg:{chat_id}:m:1")])
    else:
        filas.append([Boton("◀️ Volver", callback_data=f"cfg:{chat_id}:m:0"), cerrar, idioma])
    return Teclado(filas)


def pagina_de(seccion: str) -> int:
    return next(i for i, p in enumerate(PAGINAS) if any(seccion in fila for fila in p))


def texto_seccion(titulo_grupo: str, clave: str, a: dict) -> str:
    s = SECCIONES[clave]
    descripcion = s.descripcion(a) if callable(s.descripcion) else s.descripcion
    lineas = [f"• {c.etiqueta}: <b>{valor_legible(c, leer(a, c.ruta))}</b>" for c in s.controles]
    cuerpo = descripcion + ("\n\n" + "\n".join(lineas) if lineas else "")
    return f"<b>{s.titulo}</b>\n<b>Grupo:</b> {escape(titulo_grupo)}\n\n{cuerpo}"


def teclado_seccion(chat_id: int, clave: str, a: dict) -> Teclado:
    filas = []
    for i, c in enumerate(SECCIONES[clave].controles):
        base = f"cfg:{chat_id}:x:{clave}:{i}"
        valor = valor_legible(c, leer(a, c.ruta))
        if c.tipo == "numero":
            filas.append([Boton(c.etiqueta, callback_data=f"cfg:{chat_id}:nada"),
                          Boton("➖", callback_data=f"{base}:-"),
                          Boton(valor, callback_data=f"cfg:{chat_id}:nada"),
                          Boton("➕", callback_data=f"{base}:+")])
        else:
            filas.append([Boton(f"{c.etiqueta}: {valor}", callback_data=base)])
    filas.append([Boton("◀️ Volver", callback_data=f"cfg:{chat_id}:m:{pagina_de(clave)}"),
                  Boton("✅ Cerrar", callback_data=f"cfg:{chat_id}:cerrar")])
    return Teclado(filas)


def cambiar(a: dict, control: Control, operacion: str | None):
    actual = leer(a, control.ruta)
    if control.tipo == "interruptor":
        nuevo = not actual
    elif control.tipo == "numero":
        delta = control.paso if operacion == "+" else -control.paso
        nuevo = max(control.minimo, min(control.maximo, actual + delta))
    else:
        valores = control.opciones if control.tipo == "accion" else [v for v, _ in control.opciones]
        nuevo = valores[(valores.index(actual) + 1) % len(valores)] if actual in valores else valores[0]
    escribir(a, control.ruta, nuevo)


# ---------- Dónde configurar: en el grupo o por privado ----------

def texto_donde(titulo_grupo: str) -> str:
    return (f"⚙️ <b>CONFIGURACIÓN</b>\n<b>Grupo:</b> {escape(titulo_grupo)}\n\n"
            "<i>¿Dónde quieres abrir el menú de ajustes?</i>")


def teclado_donde(chat_id: int) -> Teclado:
    return Teclado([
        [Boton("👥 Aquí en el grupo", callback_data=f"cfg:{chat_id}:m:0"),
         Boton("👤 En privado", callback_data=f"cfg:{chat_id}:pvt")],
        [Boton("❌ Cancelar", callback_data=f"cfg:{chat_id}:cerrar")],
    ])


def enlace_inicio(usuario_bot: str, chat_id: int) -> str:
    """Abre el chat privado con el bot y le pide el menú de ese grupo (/start cfg_<id>)."""
    return f"https://t.me/{usuario_bot}?start=cfg_{chat_id}"


async def enviar_menu_privado(bot, user_id: int, chat_id: int) -> bool:
    try:
        await bot.send_message(user_id, texto_menu(await titulo_de(bot, chat_id)),
                               reply_markup=teclado_menu(chat_id, 0))
        return True
    except (BadRequest, Forbidden):
        return False  # La persona todavía no ha abierto el chat conmigo


async def grupos_que_administra(bot, user_id: int) -> list[tuple[int, str]]:
    grupos = []
    for g in db.lista_grupos()[:50]:
        if nivel((await staff(bot, g["chat_id"])).get(user_id)) >= NIVELES["admin"]:
            grupos.append((g["chat_id"], g["titulo"] or str(g["chat_id"])))
    return grupos


TEXTO_ELEGIR_GRUPO = ("⚙️ <b>CONFIGURACIÓN</b>\n\n"
                      "<i>Elige el grupo que quieres configurar.</i>")


def teclado_elegir_grupo(grupos: list[tuple[int, str]]) -> Teclado:
    filas = [[Boton(f"👥 {titulo[:40]}", callback_data=f"cfg:{chat_id}:m:0")] for chat_id, titulo in grupos]
    filas.append([Boton("❌ Cerrar", callback_data="cerrar")])
    return Teclado(filas)


async def titulo_de(bot, chat_id: int) -> str:
    g = db.grupo(chat_id)
    if g and g.get("titulo"):
        return g["titulo"]
    try:
        return (await bot.get_chat(chat_id)).title
    except Exception:
        return str(chat_id)


async def manejar(update: Update, context: ContextTypes.DEFAULT_TYPE, partes: list[str]):
    q = update.callback_query
    chat_id, accion = int(partes[0]), partes[1]
    if accion == "nada":
        await q.answer()
        return
    if nivel((await staff(context.bot, chat_id)).get(q.from_user.id)) < NIVELES["admin"]:
        await q.answer("⛔ Solo los administradores pueden cambiar los ajustes.", show_alert=True)
        return
    if accion == "cerrar":
        await q.message.delete()
        await q.answer()
        return
    if accion == "lang":
        await q.answer("🇪🇸 Por ahora hablo solo español.", show_alert=True)
        return
    if accion == "pvt":
        if await enviar_menu_privado(context.bot, q.from_user.id, chat_id):
            await q.edit_message_text(
                "📬 Te envié el menú de ajustes por privado.",
                reply_markup=Teclado([[Boton("👤 Ir al chat privado", url=f"https://t.me/{context.bot.username}")]]),
            )
            await q.answer()
        else:
            # Nunca me ha escrito: Telegram abre el chat conmigo y allí le mando el menú
            await q.answer(url=enlace_inicio(context.bot.username, chat_id))
        return

    titulo = await titulo_de(context.bot, chat_id)
    a = db.ajustes(chat_id)
    aviso = None
    if accion == "m":
        texto, teclado = texto_menu(titulo), teclado_menu(chat_id, int(partes[2]))
    elif accion == "s" and partes[2] in SECCIONES:
        texto, teclado = texto_seccion(titulo, partes[2], a), teclado_seccion(chat_id, partes[2], a)
    elif accion == "x" and partes[2] in SECCIONES:
        clave, indice = partes[2], int(partes[3])
        cambiar(a, SECCIONES[clave].controles[indice], partes[4] if len(partes) > 4 else None)
        db.guardar_ajustes(chat_id, a)
        texto, teclado = texto_seccion(titulo, clave, a), teclado_seccion(chat_id, clave, a)
        aviso = "✅ Guardado"
    else:
        await q.answer()
        return
    try:
        await q.edit_message_text(texto, reply_markup=teclado)
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise
    await q.answer(aviso)
