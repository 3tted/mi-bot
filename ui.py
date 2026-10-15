"""Textos, menús y botones con la temática de Danny Phantom."""
from html import escape

from telegram import InlineKeyboardButton as Boton, InlineKeyboardMarkup as Teclado

CABECERA = "👻 ━━━ <b>DANNY PHANTOM</b> ━━━ 👻"
SEPARADOR = "━━━━━━━━━━━━━━━━━━"


def tarjeta(titulo: str, cuerpo: str) -> str:
    return f"{CABECERA}\n<b>{titulo}</b>\n{SEPARADOR}\n{cuerpo}"


def si_no(valor: bool) -> str:
    return "✅" if valor else "❌"


# ---------- Menú de inicio (chat privado) ----------

def texto_inicio(nombre: str) -> str:
    return tarjeta(
        f"¡Wepa, {escape(nombre)}! 💚",
        "Soy <b>Danny Phantom</b>: mitad humano, mitad fantasma y guardián de tu grupo.\n\n"
        "🛡️ Modero con <code>/</code> y con <code>.</code> — da igual <code>/ban</code> o <code>.ban</code>\n"
        "🌀 Protejo contra flood, enlaces, palabras prohibidas y stickers bloqueados\n"
        "👋 Bienvenidas, reglas y captcha anti-bots\n"
        "🤖 Contesto con IA (Gemini) al estilo boricua\n\n"
        "<i>Añádeme a tu grupo como administrador para empezar a patrullar.</i>",
    )


def teclado_inicio(usuario_bot: str) -> Teclado:
    permisos = "delete_messages+restrict_members+pin_messages+invite_users+change_info"
    return Teclado([
        [Boton("➕ Añádeme a tu grupo", url=f"https://t.me/{usuario_bot}?startgroup=true&admin={permisos}")],
        [Boton("📜 Comandos", callback_data="menu:ayuda"), Boton("🤖 Hablar con la IA", callback_data="menu:ia")],
        [Boton("ℹ️ Acerca de", callback_data="menu:acerca")],
    ])


TEXTO_IA = tarjeta(
    "🤖 Inteligencia fantasma",
    "En privado contesto <b>todo</b> lo que me escribas.\n"
    "En grupos contesto si me mencionas (@) o si respondes a un mensaje mío.\n\n"
    "También puedes usar <code>/ia pregunta</code> o <code>.ia pregunta</code>,\n"
    "y <code>/traducir inglés</code> respondiendo a un mensaje.",
)

TEXTO_ACERCA = tarjeta(
    "ℹ️ Acerca de",
    "Bot de administración inspirado en Group Help, con alma de fantasma 👻\n\n"
    "• Comandos con <code>/</code> o <code>.</code>\n"
    "• IA: Google Gemini\n"
    "• Hecho en Python con python-telegram-bot",
)


def teclado_volver(destino: str = "menu:inicio") -> Teclado:
    return Teclado([[Boton("⬅️ Volver", callback_data=destino)]])


# ---------- Ayuda por categorías ----------

AYUDA = {
    "moderacion": ("🛡️ Moderación", [
        ("ban [tiempo] [motivo]", "Envía a la Zona Fantasma (banea). Tiempo: 30m, 2h, 1d, 1w"),
        ("unban", "Regresa a alguien de la Zona Fantasma"),
        ("kick", "Expulsa por un portal (puede volver a entrar)"),
        ("mute [tiempo]", "Silencia con ectoplasma"),
        ("unmute", "Le quita el silencio"),
        ("warn [motivo]", "Advertencia fantasma; al llegar al límite aplica el castigo"),
        ("unwarn", "Quita una advertencia"),
        ("warns", "Ver y gestionar advertencias con botones"),
        ("delban · delkick · delmute · delwarn", "Borra el mensaje y castiga al autor"),
        ("mban · mkick · mmute · munban · munmute", "Igual pero hasta 20 usuarios a la vez"),
        ("info · infopvt", "Información de un usuario (en el grupo o por privado)"),
        ("ammoniti", "Lista de usuarios con advertencias"),
        ("reload", "Actualiza la lista de administradores"),
    ]),
    "limpieza": ("🧹 Limpieza", [
        ("del", "Borra el mensaje al que respondes"),
        ("purge · mdel · multidel", "Borra desde el mensaje respondido hasta el último"),
        ("delall → delallgo", "Marca inicio y fin y borra todo lo de en medio"),
        ("block · unblock", "Bloquea/desbloquea un sticker o GIF"),
        ("blacklist palabra · unblacklist palabra", "Palabras prohibidas"),
    ]),
    "fijados": ("📌 Fijados", [
        ("pin [texto]", "Fija el mensaje respondido o envía y fija un texto"),
        ("npin · spin", "Fijar con notificación / en silencio"),
        ("unpin · delpin", "Desfija / borra el mensaje fijado"),
        ("unpinall", "Desfija todo"),
        ("pinned", "Muestra el mensaje fijado"),
    ]),
    "grupo": ("⚙️ Grupo", [
        ("settings · config", "Menú de ajustes con botones"),
        ("pvtsettings · pvtconfig", "Ajustes por privado"),
        ("setrules texto", "Cambia las reglas"),
        ("setwelcome texto · setgoodbye texto", "Bienvenida/despedida ({nombre}, {grupo}, {usuario}, {id})"),
        ("antiflood N [segundos]", "Mensajes permitidos antes de silenciar"),
        ("silence · unsilence", "Silencio total del grupo"),
        ("personal nombre texto · unpersonal nombre", "Comandos personalizados"),
        ("commands", "Lista los comandos personalizados"),
        ("send texto", "El bot envía un mensaje"),
        ("chatid · geturl · link", "ID del grupo, enlace a un mensaje, enlace del grupo"),
        ("backup", "Copia de los ajustes por privado"),
    ]),
    "roles": ("👥 Roles", [
        ("cofounder · uncofounder", "Cofundador (solo el fundador)"),
        ("admin · unadmin", "Administrador del bot"),
        ("mod · unmod", "Moderador: ban, kick, warn, mute"),
        ("muter · unmuter", "Solo puede silenciar"),
        ("cleaner · uncleaner", "Solo puede borrar mensajes"),
        ("helper · unhelper", "Puede ver info y advertencias"),
        ("free · unfree", "Libre de antiflood, antilink y filtros"),
        ("staff · listroles", "Ver el staff y los roles"),
    ]),
    "diversion": ("🎲 Diversión", [
        ("top10", "Los 10 más activos"),
        ("loteria", "Elige a alguien al azar"),
        ("slot", "Máquina tragamonedas"),
        ("game", "Minijuegos"),
    ]),
    "publicos": ("🌐 Para todos", [
        ("rules", "Reglas del grupo"),
        ("me", "Tu información por privado"),
        ("report · @admin", "Avisa al staff"),
        ("ia pregunta", "Pregúntale a la IA"),
        ("traducir [idioma]", "Traduce el mensaje respondido"),
        ("help", "Esta ayuda"),
    ]),
}


def texto_ayuda_indice() -> str:
    return tarjeta(
        "📜 Comandos",
        "Todos funcionan con <b>/</b> o con <b>.</b> al principio.\n"
        "Ejemplo: <code>/ban</code> = <code>.ban</code>\n\n"
        "Para usarlos sobre alguien: <b>responde a su mensaje</b>, o escribe su <code>@usuario</code> o su ID.\n\n"
        "Elige una categoría 👇",
    )


def teclado_ayuda_indice(volver: bool = True) -> Teclado:
    claves = list(AYUDA)
    filas = [
        [Boton(AYUDA[a][0], callback_data=f"ayuda:{a}") for a in claves[i:i + 2]]
        for i in range(0, len(claves), 2)
    ]
    if volver:
        filas.append([Boton("⬅️ Volver", callback_data="menu:inicio")])
    else:
        filas.append([Boton("❌ Cerrar", callback_data="cerrar")])
    return Teclado(filas)


def texto_ayuda(categoria: str) -> str:
    titulo, comandos = AYUDA[categoria]
    lineas = [f"• <code>/{c}</code>\n   {escape(d)}" for c, d in comandos]
    return tarjeta(titulo, "\n".join(lineas) + "\n\n<i>Recuerda: también con punto, ej. <code>.ban</code></i>")


# ---------- Ajustes del grupo ----------

CASTIGOS = ["ban", "kick", "mute"]
NOMBRE_CASTIGO = {"ban": "🚫 Ban", "kick": "🌀 Kick", "mute": "🔇 Mute"}


def texto_ajustes(titulo_grupo: str, a: dict) -> str:
    flood = a["antiflood"]
    return tarjeta(
        f"⚙️ Ajustes de {escape(titulo_grupo)}",
        f"👋 Bienvenida: {si_no(a['bienvenida']['on'])}\n"
        f"🚪 Despedida: {si_no(a['despedida']['on'])}\n"
        f"🧩 Captcha anti-bots: {si_no(a['captcha']['on'])}\n"
        f"🌊 Antiflood: {si_no(flood['on'])} ({flood['mensajes']} mensajes en {flood['segundos']}s)\n"
        f"🔗 Antilink: {si_no(a['antilink'])}\n"
        f"⚠️ Advertencias: límite {a['warn_limite']} → {NOMBRE_CASTIGO[a['warn_castigo']]}\n"
        f"🤖 IA en el grupo: {si_no(a['ia'])}\n"
        f"🚫 Palabras prohibidas: {len(a['palabras'])} · Stickers/GIF bloqueados: {len(a['bloqueados'])}\n\n"
        "<i>Toca un botón para cambiarlo.</i>",
    )


def teclado_ajustes(chat_id: int, a: dict) -> Teclado:
    def b(texto, accion):
        return Boton(texto, callback_data=f"cfg:{chat_id}:{accion}")

    return Teclado([
        [b(f"👋 Bienvenida {si_no(a['bienvenida']['on'])}", "bienvenida"),
         b(f"🚪 Despedida {si_no(a['despedida']['on'])}", "despedida")],
        [b(f"🧩 Captcha {si_no(a['captcha']['on'])}", "captcha"),
         b(f"🔗 Antilink {si_no(a['antilink'])}", "antilink")],
        [b(f"🌊 Antiflood {si_no(a['antiflood']['on'])}", "antiflood"),
         b("➖", "flood-"), b(f"{a['antiflood']['mensajes']}", "nada"), b("➕", "flood+")],
        [b("⚠️ Límite", "nada"), b("➖", "warn-"), b(f"{a['warn_limite']}", "nada"), b("➕", "warn+")],
        [b(f"Castigo: {NOMBRE_CASTIGO[a['warn_castigo']]}", "castigo")],
        [b(f"🤖 IA {si_no(a['ia'])}", "ia")],
        [Boton("❌ Cerrar", callback_data="cerrar")],
    ])


# ---------- Advertencias ----------

def teclado_warns(chat_id: int, user_id: int) -> Teclado:
    def b(texto, op):
        return Boton(texto, callback_data=f"warn:{chat_id}:{user_id}:{op}")

    return Teclado([[b("➖ Quitar", "-"), b("➕ Añadir", "+"), b("🗑️ Reiniciar", "0")]])


# ---------- Captcha y juegos ----------

def teclado_captcha(user_id: int) -> Teclado:
    return Teclado([[Boton("👻 ¡No soy un fantasma! (toca aquí)", callback_data=f"cap:{user_id}")]])


JUEGOS = ["🎲", "🎯", "🏀", "⚽", "🎳", "🎰"]


def teclado_juegos() -> Teclado:
    return Teclado([
        [Boton(e, callback_data=f"juego:{i}") for i, e in enumerate(JUEGOS[:3])],
        [Boton(e, callback_data=f"juego:{i + 3}") for i, e in enumerate(JUEGOS[3:])],
    ])
