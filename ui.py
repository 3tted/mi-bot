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
        f"¡Hola, {escape(nombre)}! 💚",
        "Soy <b>Danny Phantom</b>, mitad humano y mitad fantasma, y protejo tu grupo de Telegram.\n\n"
        "<b>Te ayudo a:</b>\n"
        "🛡️ Moderar: banear, expulsar, silenciar y advertir\n"
        "🧹 Mantener el chat limpio de spam, enlaces y flood\n"
        "🧩 Verificar a los nuevos miembros con captcha\n"
        "👋 Dar la bienvenida y mostrar las reglas\n"
        "👥 Organizar a tu staff con roles\n"
        "⚙️ Configurarlo todo desde un menú con botones\n\n"
        "<i>Añádeme a tu grupo como administrador y toca 📜 Comandos para ver todo lo que sé hacer.</i>",
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
    "ℹ️ Acerca de Danny Phantom",
    "Soy un bot para administrar grupos de Telegram. Mantengo tu grupo seguro, ordenado y activo "
    "para que tú no tengas que estar pendiente todo el día.\n\n"
    "<b>Lo que puedo hacer por tu grupo:</b>\n"
    "🛡️ Ban, kick, mute y advertencias, también por tiempo (30m, 2h, 1d)\n"
    "🧩 Captcha para frenar bots y cuentas falsas\n"
    "🌊 Antiflood, antilink, palabras prohibidas y stickers bloqueados\n"
    "👥 Roles de staff: cofundador, admin, moderador, muter, cleaner y helper\n"
    "📌 Reglas, bienvenidas, mensajes fijados y comandos personalizados\n"
    "📊 Ranking de los más activos y minijuegos\n\n"
    "📜 Toca <b>Comandos</b> en el menú o escribe /help en tu grupo.",
)


def teclado_volver(destino: str = "menu:inicio") -> Teclado:
    return Teclado([[Boton("⬅️ Volver", callback_data=destino)]])


# ---------- Menú de ayuda por niveles (como Group Help) ----------

AYUDA = {
    "basicos": ("🟢 Comandos básicos", "Lo esencial para moderar tu grupo.", [
        ("ban", "Banea a un usuario del grupo"),
        ("unban", "Le quita el ban"),
        ("kick", "Lo expulsa (puede volver a entrar)"),
        ("mute", "Lo silencia"),
        ("unmute", "Le quita el silencio"),
        ("warn", "Le da una advertencia"),
        ("unwarn", "Le quita una advertencia"),
        ("del", "Borra el mensaje al que respondes"),
        ("info", "Muestra la ficha de un usuario"),
        ("rules", "Muestra las reglas del grupo"),
        ("staff", "Muestra el staff del grupo"),
        ("report", "Avisa al staff (también escribiendo @admin)"),
        ("me", "Te envía tu ficha por privado"),
    ]),
    "avanzados": ("🟡 Comandos avanzados", "Más control sobre la moderación y el chat.", [
        ("ban 2h motivo", "Ban por tiempo: 30m, 2h, 1d, 1w (igual con mute)"),
        ("warns", "Ver y cambiar advertencias con botones"),
        ("ammoniti", "Lista de usuarios con advertencias"),
        ("delban · delkick · delmute · delwarn", "Borra el mensaje y castiga al autor"),
        ("mban · mkick · mmute · munban · munmute", "Lo mismo, hasta 20 usuarios a la vez"),
        ("purge", "Borra desde el mensaje respondido hasta el último"),
        ("delall → delallgo", "Marca inicio y fin, y borra lo de en medio"),
        ("pin · spin · unpin · unpinall", "Fijar (con o sin aviso) y desfijar"),
        ("delpin · repin · editpin · pinned", "Gestionar el mensaje fijado"),
        ("setrules", "Cambia las reglas"),
        ("setwelcome · setgoodbye", "Mensaje de bienvenida y despedida"),
        ("antiflood 5 4", "Máximo de mensajes en X segundos"),
        ("blacklist · unblacklist", "Palabras prohibidas"),
        ("block · unblock", "Bloquea un sticker o GIF"),
        ("link · geturl · chatid", "Enlace del grupo, de un mensaje, ID"),
        ("reload", "Actualiza la lista de administradores"),
        ("top10 · loteria · slot · game", "Ranking, sorteo y minijuegos"),
        ("tagall texto", "Menciona a todos (también escribiendo @all)"),
        ("filtro palabra respuesta · unfiltro · filtros", "Respuestas automáticas"),
        ("recurrente 6h texto · recurrentes · unrecurrente", "Mensajes que se repiten solos"),
    ]),
    "expertos": ("🔴 Comandos expertos", "Roles, ajustes y herramientas del fundador.", [
        ("settings · pvtsettings", "Menú de ajustes (en el grupo o por privado)"),
        ("cofounder · uncofounder", "Nombra cofundador (solo el fundador)"),
        ("admin · unadmin", "Administrador del bot"),
        ("mod · unmod", "Moderador: ban, kick, mute y warn"),
        ("muter · unmuter", "Solo puede silenciar"),
        ("cleaner · uncleaner", "Solo puede borrar mensajes"),
        ("helper · unhelper", "Puede ver fichas y advertencias"),
        ("free · unfree", "Lo libra de antiflood, antilink y filtros"),
        ("listroles", "Lista de roles por privado"),
        ("personal nombre texto", "Crea un comando propio del grupo"),
        ("unpersonal · commands", "Borra o lista los comandos propios"),
        ("silence · unsilence", "Silencio total: solo el staff escribe"),
        ("send texto", "El bot envía un mensaje en el grupo"),
        ("infopvt", "Ficha de un usuario por privado"),
        ("backup", "Copia de los ajustes por privado"),
        ("magic ban · unmagic", "Convierte un sticker o GIF en un comando"),
        ("setlog ID · setlink · settopic", "Canal de registro, enlace propio y tema de avisos"),
        ("id", "Tu ID y el del grupo"),
    ]),
}

GUIA_PRO = tarjeta(
    "⭐ Guía Pro",
    "<b>1. Ponme a trabajar</b>\n"
    "Añádeme al grupo como <b>administrador</b> con permiso para borrar mensajes, "
    "restringir miembros y fijar mensajes.\n\n"
    "<b>2. Configúrame</b>\n"
    "Escribe /settings en el grupo y activa lo que necesites: bienvenida, captcha, "
    "antiflood, antilink y el castigo al llegar al límite de advertencias.\n\n"
    "<b>3. A quién va dirigido un comando</b>\n"
    "Responde al mensaje de la persona, o escribe su <code>@usuario</code> o su ID: "
    "<code>/ban @usuario 1d spam</code>\n\n"
    "<b>4. Bienvenida a tu medida</b>\n"
    "<code>/setwelcome ¡Hola {nombre}, bienvenid@ a {grupo}!</code>\n"
    "Variables: {nombre}, {usuario}, {id}, {grupo}\n\n"
    "<b>5. Reparte el trabajo</b>\n"
    "Fundador → Cofundador → Admin → Moderador. Los muter, cleaner y helper "
    "solo tienen su tarea. Mira quién es quién con /staff.\n\n"
    "<b>6. Trucos</b>\n"
    "• Todos los comandos también funcionan con punto: <code>.ban</code>\n"
    "• Crea respuestas rápidas con /personal (ej. <code>/personal precios ...</code>)\n"
    "• /silence cierra el chat en una emergencia",
)


def texto_ayuda_indice() -> str:
    return tarjeta(
        "📜 Menú de ayuda",
        "Aquí tienes todos mis comandos, ordenados por nivel. Elige una sección 👇\n\n"
        "🟢 <b>Básicos</b>: lo esencial para moderar\n"
        "🟡 <b>Avanzados</b>: limpieza, fijados, bienvenidas y filtros\n"
        "🔴 <b>Expertos</b>: roles, ajustes y herramientas del fundador\n"
        "⭐ <b>Guía Pro</b>: cómo configurarme paso a paso",
    )


def teclado_ayuda_indice(volver: bool = True) -> Teclado:
    filas = [
        [Boton("🟢 Básicos", callback_data="ayuda:basicos"), Boton("🟡 Avanzados", callback_data="ayuda:avanzados")],
        [Boton("🔴 Expertos", callback_data="ayuda:expertos"), Boton("⭐ Guía Pro", callback_data="ayuda:guia")],
    ]
    if volver:
        filas.append([Boton("⬅️ Volver", callback_data="menu:inicio")])
    else:
        filas.append([Boton("❌ Cerrar", callback_data="cerrar")])
    return Teclado(filas)


def texto_ayuda(categoria: str) -> str:
    if categoria == "guia":
        return GUIA_PRO
    titulo, subtitulo, comandos = AYUDA[categoria]
    lineas = [f"• <code>/{c}</code> — {escape(d)}" for c, d in comandos]
    return tarjeta(titulo, f"<i>{subtitulo}</i>\n\n" + "\n".join(lineas))


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
