"""Todos los comandos del bot. Cada uno funciona con "/" o con "." al principio."""
import io
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape

from telegram import ChatPermissions, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes
from telegram.helpers import mention_html

import ajustes_menu
import db
import ia
import ui
from castigos import borrar_mensaje_luego, programar_borrado, registrar
from permisos import (
    NIVELES, NOMBRES_ROL, Aviso, Objetivo, duracion, es_staff, nivel, objetivo, objetivos_multiples,
    olvidar_staff, rol_de, staff, texto_duracion,
)


@dataclass
class Peticion:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    nombre: str
    texto: str
    args: list[str] = field(init=False)

    def __post_init__(self):
        self.args = self.texto.split()

    @property
    def msg(self):
        return self.update.message

    @property
    def chat(self):
        return self.update.effective_chat

    @property
    def user(self):
        return self.update.effective_user

    @property
    def bot(self):
        return self.context.bot

    async def responder(self, texto: str, **kwargs):
        enviado = await self.msg.reply_text(texto, **kwargs)
        if self.chat.type != ChatType.PRIVATE:
            # Eliminación de mensajes: borrar mis respuestas después de X minutos
            programar_borrado(self.context, self.chat.id, enviado.message_id,
                              db.ajustes(self.chat.id)["eliminar"]["bot_min"] * 60)
        return enviado

    def respondido(self):
        respuesta = self.msg.reply_to_message
        if respuesta and not respuesta.forum_topic_created:
            return respuesta
        return None


@dataclass
class Comando:
    funcion: object
    rol: str | None
    extra: tuple
    solo_grupo: bool


COMANDOS: dict[str, Comando] = {}

# Comandos que un admin puede prohibir a los miembros normales (sección Permisos)
PERMISO_DE = {
    "rules": "rules", "reglas": "rules", "staff": "staff", "link": "link", "top10": "top10", "top": "top10",
    "ia": "ia", "ai": "ia", "pregunta": "ia", "traducir": "ia", "translate": "ia", "trad": "ia",
    "me": "me", "report": "report", "game": "game", "juegos": "game", "slot": "game",
    "chango": "sticker", "sticker": "sticker", "mono": "sticker",
}


def comando(*nombres, rol=None, extra=(), solo_grupo=True):
    def registrar(funcion):
        for nombre in nombres:
            COMANDOS[nombre] = Comando(funcion, rol, extra, solo_grupo)
        return funcion
    return registrar


async def ejecutar(update: Update, context: ContextTypes.DEFAULT_TYPE, nombre: str, texto: str):
    cmd = COMANDOS[nombre]
    p = Peticion(update, context, nombre, texto)
    if cmd.solo_grupo and p.chat.type == ChatType.PRIVATE:
        await p.responder("👥 Este comando funciona dentro de un grupo.")
        return
    en_grupo = p.chat.type != ChatType.PRIVATE
    rol = await rol_de(update, context) if en_grupo else None
    if cmd.rol and nivel(rol) < NIVELES[cmd.rol] and rol not in cmd.extra:
        return  # Igual que Group Help: los comandos de staff se ignoran si no tienes permiso
    a = db.ajustes(p.chat.id) if en_grupo else None
    if en_grupo and nombre in PERMISO_DE and not a["permisos"][PERMISO_DE[nombre]] and not es_staff(rol):
        return  # Un admin lo desactivó para los miembros normales
    try:
        await cmd.funcion(p)
    except Aviso as aviso:
        await p.responder(str(aviso))
    if en_grupo and a["eliminar"]["comandos"]:
        try:
            await p.msg.delete()
        except Exception:
            pass


def firma(p: Peticion, motivo: str = "") -> str:
    lineas = []
    if motivo:
        lineas.append(f"📝 Motivo: {escape(motivo)}")
    if p.msg.sender_chat:
        lineas.append("👮 Por: un admin anónimo")
    else:
        lineas.append(f"👮 Por: {mention_html(p.user.id, p.user.full_name)}")
    return "\n".join(lineas)


async def permisos_del_grupo(p: Peticion) -> ChatPermissions:
    chat = await p.bot.get_chat(p.chat.id)
    return chat.permissions or ChatPermissions.all_permissions()


async def proteger(p: Peticion, obj: Objetivo):
    if obj.id == p.bot.id:
        raise Aviso("😏 ¿Usar mis poderes contra mí? Soy intangible, mano.")
    if es_staff((await staff(p.bot, p.chat.id)).get(obj.id)):
        raise Aviso(f"🛡️ {obj.mencion} es del staff; mis poderes fantasma no funcionan con ellos.")


# =====================================================================
# Moderación
# =====================================================================

async def aplicar(p: Peticion, obj: Objetivo, accion: str, segundos: int | None = None) -> str:
    hasta = datetime.now(timezone.utc) + timedelta(seconds=segundos) if segundos else None
    durante = f" por <b>{texto_duracion(segundos)}</b>" if segundos else ""
    chat_id = p.chat.id
    if accion == "ban":
        await p.bot.ban_chat_member(chat_id, obj.id, until_date=hasta)
        return f"👻 {obj.mencion} fue enviado a la <b>Zona Fantasma</b>{durante}."
    if accion == "kick":
        await p.bot.ban_chat_member(chat_id, obj.id)
        await p.bot.unban_chat_member(chat_id, obj.id, only_if_banned=True)
        return f"🌀 {obj.mencion} salió volando por un portal fantasma."
    if accion == "mute":
        await p.bot.restrict_chat_member(chat_id, obj.id, ChatPermissions.no_permissions(), until_date=hasta)
        return f"🔇 {obj.mencion} quedó con la boca llena de ectoplasma{durante}."
    if accion == "unmute":
        await p.bot.restrict_chat_member(chat_id, obj.id, await permisos_del_grupo(p))
        return f"🗣️ {obj.mencion} ya puede hablar otra vez."
    if accion == "unban":
        await p.bot.unban_chat_member(chat_id, obj.id, only_if_banned=True)
        return f"✨ {obj.mencion} regresó de la Zona Fantasma."
    raise ValueError(accion)


async def advertir(p: Peticion, obj: Objetivo, motivo: str) -> str:
    a = db.ajustes(p.chat.id)
    warns = db.miembro(p.chat.id, obj.id)["warns"] + 1
    if warns >= a["warn_limite"]:
        db.actualizar_miembro(p.chat.id, obj.id, warns=0)
        castigo = await aplicar(p, obj, a["warn_castigo"])
        return f"⚠️ {obj.mencion} llegó a {warns}/{a['warn_limite']} advertencias.\n{castigo}\n{firma(p, motivo)}"
    db.actualizar_miembro(p.chat.id, obj.id, warns=warns)
    return f"⚠️ Advertencia fantasma para {obj.mencion}: <b>{warns}/{a['warn_limite']}</b>\n{firma(p, motivo)}"


async def moderar(p: Peticion, accion: str, borrar: bool = False):
    obj, resto = await objetivo(p.update, p.context, p.args)
    if accion not in ("unban", "unmute"):
        await proteger(p, obj)
    segundos = None
    if accion in ("ban", "mute") and resto and duracion(resto[0]):
        segundos = duracion(resto[0])
        resto = resto[1:]
    motivo = " ".join(resto)
    if borrar:
        respondido = p.respondido()
        if not respondido:
            raise Aviso("↩️ Responde al mensaje que quieres borrar.")
        await respondido.delete()
    if accion == "warn":
        texto = await advertir(p, obj, motivo)
        await p.responder(texto, reply_markup=ui.teclado_warns(p.chat.id, obj.id))
    else:
        texto = f"{await aplicar(p, obj, accion, segundos)}\n{firma(p, motivo)}"
        await p.responder(texto)
    await registrar(p.bot, p.chat, texto)


async def moderar_varios(p: Peticion, accion: str):
    objs = await objetivos_multiples(p.update, p.context, p.args)
    hechos, fallos = [], []
    for obj in objs:
        try:
            if accion not in ("unban", "unmute"):
                await proteger(p, obj)
            await aplicar(p, obj, accion)
            hechos.append(obj.mencion)
        except Exception as e:
            fallos.append(f"{obj.mencion} ({escape(str(e))})")
    titulos = {
        "ban": "👻 Enviados a la Zona Fantasma", "kick": "🌀 Expulsados por el portal",
        "mute": "🔇 Silenciados", "unban": "✨ Regresaron de la Zona Fantasma", "unmute": "🗣️ Pueden hablar",
    }
    texto = f"<b>{titulos[accion]}:</b> {len(hechos)}\n" + "\n".join(f"• {h}" for h in hechos)
    if fallos:
        texto += "\n\n<b>❌ No se pudo:</b>\n" + "\n".join(f"• {f}" for f in fallos)
    await p.responder(f"{texto}\n{firma(p)}")
    await registrar(p.bot, p.chat, f"{texto}\n{firma(p)}")


def _registrar_moderacion():
    for accion in ("ban", "kick", "warn"):
        comando(accion, rol="mod")(lambda p, a=accion: moderar(p, a))
        comando(f"del{accion}", rol="mod")(lambda p, a=accion: moderar(p, a, borrar=True))
    comando("mute", rol="mod", extra=("muter",))(lambda p: moderar(p, "mute"))
    comando("delmute", rol="mod")(lambda p: moderar(p, "mute", borrar=True))
    comando("unban", rol="mod")(lambda p: moderar(p, "unban"))
    comando("unmute", rol="mod", extra=("muter",))(lambda p: moderar(p, "unmute"))
    for accion in ("ban", "kick", "mute", "unban", "unmute"):
        comando(f"m{accion}", f"multi{accion}", rol="mod")(lambda p, a=accion: moderar_varios(p, a))


_registrar_moderacion()


@comando("unwarn", rol="mod")
async def unwarn(p: Peticion):
    obj, _ = await objetivo(p.update, p.context, p.args)
    warns = max(0, db.miembro(p.chat.id, obj.id)["warns"] - 1)
    db.actualizar_miembro(p.chat.id, obj.id, warns=warns)
    limite = db.ajustes(p.chat.id)["warn_limite"]
    await p.responder(f"💚 Le quité una advertencia a {obj.mencion}: <b>{warns}/{limite}</b>")


def texto_warns(chat_id: int, obj: Objetivo) -> str:
    warns = db.miembro(chat_id, obj.id)["warns"]
    limite = db.ajustes(chat_id)["warn_limite"]
    barra = "🟥" * warns + "⬜" * max(0, limite - warns)
    return f"⚠️ Advertencias de {obj.mencion}\n{barra} <b>{warns}/{limite}</b>"


@comando("warns", rol="mod", extra=("helper",))
async def warns(p: Peticion):
    obj, _ = await objetivo(p.update, p.context, p.args)
    await p.responder(texto_warns(p.chat.id, obj), reply_markup=ui.teclado_warns(p.chat.id, obj.id))


@comando("ammoniti", "advertidos", rol="mod", extra=("helper",))
async def advertidos(p: Peticion):
    lista = db.con_advertencias(p.chat.id)
    if not lista:
        raise Aviso("😇 Nadie tiene advertencias. ¡Grupo tranquilo!")
    limite = db.ajustes(p.chat.id)["warn_limite"]
    lineas = [f"• {mention_html(uid, db.nombre_usuario(uid) or str(uid))}: {n}/{limite}" for uid, n in lista]
    await p.responder(ui.tarjeta("⚠️ Usuarios advertidos", "\n".join(lineas)))


async def texto_info(p: Peticion, obj: Objetivo) -> str:
    m = db.miembro(p.chat.id, obj.id)
    rol = (await staff(p.bot, p.chat.id)).get(obj.id)
    limite = db.ajustes(p.chat.id)["warn_limite"]
    estados = {
        ChatMemberStatus.OWNER: "👑 Dueño", ChatMemberStatus.ADMINISTRATOR: "⚡ Administrador",
        ChatMemberStatus.MEMBER: "👤 Miembro", ChatMemberStatus.RESTRICTED: "🔇 Restringido",
        ChatMemberStatus.LEFT: "🚪 Fuera del grupo", ChatMemberStatus.BANNED: "👻 En la Zona Fantasma",
    }
    try:
        cm = await p.bot.get_chat_member(p.chat.id, obj.id)
        estado = estados.get(cm.status, cm.status)
        username = f"@{cm.user.username}" if cm.user.username else "—"
    except Exception:
        estado, username = "❓ Desconocido", "—"
    return ui.tarjeta(
        "👤 Ficha fantasma",
        f"Nombre: {obj.mencion}\n"
        f"🆔 ID: <code>{obj.id}</code>\n"
        f"🔗 Usuario: {escape(username)}\n"
        f"🎭 Rol: {NOMBRES_ROL.get(rol, '👤 Miembro')}\n"
        f"📊 Estado: {estado}\n"
        f"⚠️ Advertencias: {m['warns']}/{limite}\n"
        f"💬 Mensajes: {m['msgs']}",
    )


async def _objetivo_o_yo(p: Peticion) -> Objetivo:
    if p.args or p.respondido() or any(e.type == "text_mention" for e in p.msg.entities):
        return (await objetivo(p.update, p.context, p.args))[0]
    return Objetivo(p.user.id, p.user.full_name)


@comando("info", rol="mod", extra=("helper",))
async def info(p: Peticion):
    await p.responder(await texto_info(p, await _objetivo_o_yo(p)))


async def enviar_privado(p: Peticion, texto: str, **kwargs):
    try:
        await p.bot.send_message(p.user.id, texto, **kwargs)
    except Exception:
        raise Aviso(
            f"📭 No te puedo escribir por privado. Abre el chat conmigo (@{p.bot.username}), "
            "toca Iniciar y vuelve a intentarlo."
        )


@comando("infopvt", rol="mod", extra=("helper",))
async def infopvt(p: Peticion):
    await enviar_privado(p, await texto_info(p, await _objetivo_o_yo(p)))
    await p.responder("📬 Te lo envié por privado.")


@comando("reload", rol="mod")
async def reload(p: Peticion):
    olvidar_staff(p.chat.id)
    lista = await staff(p.bot, p.chat.id, forzar=True)
    await p.responder(f"🔄 Lista de staff actualizada: <b>{len(lista)}</b> miembros con rol. ¡Listo pa' patrullar!")


# =====================================================================
# Limpieza
# =====================================================================

@comando("del", rol="admin", extra=("cleaner",))
async def borrar(p: Peticion):
    respondido = p.respondido()
    if not respondido:
        raise Aviso("↩️ Responde al mensaje que quieres borrar.")
    await respondido.delete()
    await p.msg.delete()


async def borrar_rango(p: Peticion, desde: int, hasta: int) -> int:
    ids = list(range(desde, hasta + 1))
    for i in range(0, len(ids), 100):
        await p.bot.delete_messages(p.chat.id, ids[i:i + 100])
    return len(ids)


@comando("purge", "mdel", "multidel", rol="admin", extra=("cleaner",))
async def purge(p: Peticion):
    respondido = p.respondido()
    if not respondido:
        raise Aviso("↩️ Responde al primer mensaje desde el que quieres borrar.")
    n = await borrar_rango(p, respondido.message_id, p.msg.message_id)
    aviso = await p.bot.send_message(p.chat.id, f"🧹 Limpié hasta {n} mensajes. ¡Zona despejada!")
    p.context.job_queue.run_once(borrar_mensaje_luego, 10, data=(p.chat.id, aviso.message_id))


@comando("delall", rol="admin", extra=("cleaner",))
async def delall(p: Peticion):
    respondido = p.respondido()
    if not respondido:
        raise Aviso("↩️ Responde al primer mensaje que quieres borrar y luego usa /delallgo en el último.")
    p.context.chat_data["delall_desde"] = respondido.message_id
    await p.responder("📍 Inicio marcado. Ahora responde al último mensaje con /delallgo")


@comando("delallgo", rol="admin", extra=("cleaner",))
async def delallgo(p: Peticion):
    desde = p.context.chat_data.pop("delall_desde", None)
    respondido = p.respondido()
    if not desde or not respondido:
        raise Aviso("📍 Primero marca el inicio con /delall y luego responde al último mensaje con /delallgo.")
    n = await borrar_rango(p, min(desde, respondido.message_id), max(desde, respondido.message_id))
    await p.msg.delete()
    aviso = await p.bot.send_message(p.chat.id, f"🧹 Borré hasta {n} mensajes.")
    p.context.job_queue.run_once(borrar_mensaje_luego, 10, data=(p.chat.id, aviso.message_id))


@comando("block", "unblock", rol="admin")
async def bloquear(p: Peticion):
    respondido = p.respondido()
    media = respondido and (respondido.sticker or respondido.animation)
    if not media:
        raise Aviso("↩️ Responde a un sticker o GIF.")
    a = db.ajustes(p.chat.id)
    if p.nombre == "block":
        if media.file_unique_id not in a["bloqueados"]:
            a["bloqueados"].append(media.file_unique_id)
        texto = "🚫 Bloqueado. Si alguien lo envía, lo desaparezco 👻"
        await respondido.delete()
    else:
        if media.file_unique_id in a["bloqueados"]:
            a["bloqueados"].remove(media.file_unique_id)
        texto = "✅ Desbloqueado."
    db.guardar_ajustes(p.chat.id, a)
    await p.responder(texto)


@comando("blacklist", "unblacklist", rol="admin")
async def palabras(p: Peticion):
    a = db.ajustes(p.chat.id)
    if not p.args:
        lista = ", ".join(f"<code>{escape(x)}</code>" for x in a["palabras"]) or "ninguna"
        await p.responder(f"🤐 Palabras prohibidas: {lista}")
        return
    palabra = p.texto.strip().lower()
    if p.nombre == "blacklist":
        if palabra not in a["palabras"]:
            a["palabras"].append(palabra)
        texto = f"🤐 Prohibida: <code>{escape(palabra)}</code>"
    else:
        if palabra in a["palabras"]:
            a["palabras"].remove(palabra)
        texto = f"✅ Ya se puede decir: <code>{escape(palabra)}</code>"
    db.guardar_ajustes(p.chat.id, a)
    await p.responder(texto)


# =====================================================================
# Mensajes fijados
# =====================================================================

async def fijar(p: Peticion, silencioso: bool):
    respondido = p.respondido()
    if respondido:
        await respondido.pin(disable_notification=silencioso)
    elif p.texto:
        enviado = await p.bot.send_message(p.chat.id, escape(p.texto))
        await enviado.pin(disable_notification=silencioso)
        await p.msg.delete()
        return
    else:
        raise Aviso("📌 Responde a un mensaje o escribe el texto que quieres fijar.")
    await p.responder("📌 ¡Fijado!")


comando("pin", "npin", rol="admin")(lambda p: fijar(p, silencioso=False))
comando("spin", rol="admin")(lambda p: fijar(p, silencioso=True))


async def mensaje_fijado(p: Peticion):
    chat = await p.bot.get_chat(p.chat.id)
    if not chat.pinned_message:
        raise Aviso("📌 No hay ningún mensaje fijado.")
    return chat.pinned_message


@comando("unpin", rol="admin")
async def unpin(p: Peticion):
    respondido = p.respondido()
    await p.bot.unpin_chat_message(p.chat.id, respondido.message_id if respondido else None)
    await p.responder("📍 Desfijado.")


@comando("unpinall", rol="admin")
async def unpinall(p: Peticion):
    await p.bot.unpin_all_chat_messages(p.chat.id)
    await p.responder("📍 Desfijé todos los mensajes.")


@comando("delpin", rol="admin")
async def delpin(p: Peticion):
    fijado = await mensaje_fijado(p)
    await fijado.delete()
    await p.responder("🗑️ Borré el mensaje fijado.")


@comando("repin", rol="admin")
async def repin(p: Peticion):
    fijado = await mensaje_fijado(p)
    await p.bot.unpin_chat_message(p.chat.id, fijado.message_id)
    await p.bot.pin_chat_message(p.chat.id, fijado.message_id, disable_notification=False)
    await p.responder("🔔 Volví a fijarlo con notificación.")


@comando("editpin", rol="admin")
async def editpin(p: Peticion):
    if not p.texto:
        raise Aviso("✏️ Escribe el nuevo texto: /editpin texto")
    fijado = await mensaje_fijado(p)
    if not fijado.from_user or fijado.from_user.id != p.bot.id:
        raise Aviso("✏️ Solo puedo editar mensajes fijados que envié yo (usa /pin texto).")
    await p.bot.edit_message_text(escape(p.texto), chat_id=p.chat.id, message_id=fijado.message_id)
    await p.responder("✏️ Mensaje fijado actualizado.")


def enlace_mensaje(chat, mensaje_id: int) -> str:
    if chat.username:
        return f"https://t.me/{chat.username}/{mensaje_id}"
    return f"https://t.me/c/{str(chat.id).removeprefix('-100')}/{mensaje_id}"


@comando("pinned")
async def pinned(p: Peticion):
    fijado = await mensaje_fijado(p)
    await p.responder(f"📌 <a href=\"{enlace_mensaje(p.chat, fijado.message_id)}\">Ver mensaje fijado</a>")


@comando("geturl", rol="mod")
async def geturl(p: Peticion):
    respondido = p.respondido()
    if not respondido:
        raise Aviso("↩️ Responde al mensaje del que quieres el enlace.")
    await p.responder(f"🔗 {enlace_mensaje(p.chat, respondido.message_id)}")


# =====================================================================
# Grupo
# =====================================================================

@comando("settings", "config", solo_grupo=False)
async def settings(p: Peticion):
    if p.chat.type == ChatType.PRIVATE:
        # Por privado: elegir cuál de tus grupos configurar
        grupos = await ajustes_menu.grupos_que_administra(p.bot, p.user.id)
        if not grupos:
            raise Aviso("⚙️ No encontré grupos donde seas administrador y yo esté. "
                        "Escribe /settings dentro del grupo que quieres configurar.")
        await p.responder(ajustes_menu.TEXTO_ELEGIR_GRUPO, reply_markup=ajustes_menu.teclado_elegir_grupo(grupos))
        return
    if nivel(await rol_de(p.update, p.context)) < NIVELES["admin"]:
        return
    # En el grupo: preguntar si lo configura aquí o por privado
    await p.responder(ajustes_menu.texto_donde(p.chat.title), reply_markup=ajustes_menu.teclado_donde(p.chat.id))


@comando("pvtsettings", "pvtconfig", rol="admin")
async def pvtsettings(p: Peticion):
    if not await ajustes_menu.enviar_menu_privado(p.bot, p.user.id, p.chat.id):
        raise Aviso(f"📭 Primero abre el chat conmigo: "
                    f"<a href=\"{ajustes_menu.enlace_inicio(p.bot.username, p.chat.id)}\">toca aquí</a> y te llegará el menú.")
    await p.responder("📬 Te envié los ajustes por privado.")


def _texto_o_respondido(p: Peticion) -> str:
    if p.texto:
        return p.texto
    respondido = p.respondido()
    if respondido and (respondido.text or respondido.caption):
        return respondido.text or respondido.caption
    return ""


@comando("setrules", rol="admin")
async def setrules(p: Peticion):
    texto = _texto_o_respondido(p)
    if not texto:
        raise Aviso("📜 Escribe las reglas: /setrules 1. Respeto... (o responde a un mensaje con ellas)")
    a = db.ajustes(p.chat.id)
    a["reglas"] = texto
    db.guardar_ajustes(p.chat.id, a)
    await p.responder("📜 ¡Reglas guardadas! Se ven con /rules")


@comando("rules", "reglas")
async def rules(p: Peticion):
    reglas = db.ajustes(p.chat.id)["reglas"]
    if not reglas:
        raise Aviso("📜 Este grupo todavía no tiene reglas. Un admin las puede poner con /setrules")
    await p.responder(ui.tarjeta(f"📜 Reglas de {escape(p.chat.title)}", escape(reglas)))


async def _cambiar_mensaje(p: Peticion, clave: str, nombre: str):
    a = db.ajustes(p.chat.id)
    texto = _texto_o_respondido(p)
    if texto.lower() in ("on", "off"):
        a[clave]["on"] = texto.lower() == "on"
        respuesta = f"{nombre}: {ui.si_no(a[clave]['on'])}"
    elif texto:
        a[clave] = {"on": True, "texto": texto}
        respuesta = f"{nombre} guardada ✅. Así se verá:\n\n" + rellenar(texto, p.user, p.chat)
    else:
        raise Aviso(
            f"✏️ Escribe el texto, o <code>on</code>/<code>off</code>.\n"
            "Puedes usar {nombre}, {usuario}, {id} y {grupo}."
        )
    db.guardar_ajustes(p.chat.id, a)
    await p.responder(respuesta)


def rellenar(plantilla: str, usuario, chat) -> str:
    texto = escape(plantilla)
    reemplazos = {
        "{nombre}": mention_html(usuario.id, usuario.full_name),
        "{usuario}": f"@{usuario.username}" if usuario.username else escape(usuario.full_name),
        "{id}": str(usuario.id),
        "{grupo}": escape(chat.title or ""),
    }
    for clave, valor in reemplazos.items():
        texto = texto.replace(clave, valor)
    return texto


comando("setwelcome", "welcome", rol="admin")(lambda p: _cambiar_mensaje(p, "bienvenida", "👋 Bienvenida"))
comando("setgoodbye", "goodbye", rol="admin")(lambda p: _cambiar_mensaje(p, "despedida", "🚪 Despedida"))


@comando("antiflood", rol="admin")
async def antiflood(p: Peticion):
    a = db.ajustes(p.chat.id)
    if p.args and p.args[0].lower() in ("on", "off"):
        a["antiflood"]["on"] = p.args[0].lower() == "on"
    elif p.args and p.args[0].isdigit():
        a["antiflood"]["on"] = True
        a["antiflood"]["mensajes"] = max(2, min(50, int(p.args[0])))
        if len(p.args) > 1 and p.args[1].isdigit():
            a["antiflood"]["segundos"] = max(1, min(60, int(p.args[1])))
    else:
        raise Aviso("🌊 Uso: /antiflood 5 [segundos] · /antiflood off")
    db.guardar_ajustes(p.chat.id, a)
    f = a["antiflood"]
    await p.responder(f"🌊 Antiflood {ui.si_no(f['on'])}: máximo {f['mensajes']} mensajes en {f['segundos']} s.")


@comando("silence", rol="cofounder")
async def silence(p: Peticion):
    a = db.ajustes(p.chat.id)
    a["silencio_previo"] = (await permisos_del_grupo(p)).to_dict()
    db.guardar_ajustes(p.chat.id, a)
    await p.bot.set_chat_permissions(p.chat.id, ChatPermissions.no_permissions())
    await p.responder("🤫 <b>Silencio fantasma</b> activado. Solo el staff puede escribir.")


@comando("unsilence", rol="cofounder")
async def unsilence(p: Peticion):
    a = db.ajustes(p.chat.id)
    previo = a.get("silencio_previo")
    permisos = ChatPermissions.de_json(previo, p.bot) if previo else ChatPermissions(
        can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True,
        can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True,
        can_send_other_messages=True, can_add_web_page_previews=True, can_invite_users=True,
    )
    await p.bot.set_chat_permissions(p.chat.id, permisos)
    a["silencio_previo"] = None
    db.guardar_ajustes(p.chat.id, a)
    await p.responder("🗣️ Se acabó el silencio. ¡A janguear otra vez!")


@comando("personal", "alias", rol="admin")
async def personal(p: Peticion):
    if not p.args:
        raise Aviso("✏️ Uso: /personal nombre texto (o responde a un mensaje con /personal nombre)")
    nombre = p.args[0].lower().lstrip("/.")
    texto = p.texto[len(p.args[0]):].strip()
    respondido = p.respondido()
    if not texto and respondido:
        texto = respondido.text or respondido.caption or ""
    if not texto:
        raise Aviso("✏️ Falta el texto que debe responder el comando.")
    if nombre in COMANDOS:
        raise Aviso(f"⛔ /{nombre} ya es un comando del bot.")
    a = db.ajustes(p.chat.id)
    a["alias"][nombre] = texto
    db.guardar_ajustes(p.chat.id, a)
    await p.responder(f"✨ Comando creado: <code>/{escape(nombre)}</code> o <code>.{escape(nombre)}</code>")


@comando("unpersonal", "unalias", "remove", rol="admin")
async def unpersonal(p: Peticion):
    if not p.args:
        raise Aviso("✏️ Uso: /unpersonal nombre")
    a = db.ajustes(p.chat.id)
    nombre = p.args[0].lower().lstrip("/.")
    if a["alias"].pop(nombre, None) is None:
        raise Aviso("🔍 Ese comando personalizado no existe.")
    db.guardar_ajustes(p.chat.id, a)
    await p.responder(f"🗑️ Borré <code>/{escape(nombre)}</code>")


@comando("commands", rol="admin")
async def commands(p: Peticion):
    alias = db.ajustes(p.chat.id)["alias"]
    if not alias:
        raise Aviso("📭 No hay comandos personalizados. Crea uno con /personal nombre texto")
    await p.responder(ui.tarjeta("✨ Comandos personalizados", "\n".join(f"• /{escape(n)}" for n in sorted(alias))))


@comando("send", rol="admin")
async def send(p: Peticion):
    if not p.texto:
        raise Aviso("✏️ Uso: /send texto")
    await p.bot.send_message(p.chat.id, escape(p.texto))
    await p.msg.delete()


@comando("chatid", rol="mod")
async def chatid(p: Peticion):
    await p.responder(f"🆔 ID del grupo: <code>{p.chat.id}</code>")


@comando("link")
async def link(p: Peticion):
    chat = await p.bot.get_chat(p.chat.id)
    enlace = db.ajustes(p.chat.id)["enlace"]["personalizado"] or chat.invite_link or (
        f"https://t.me/{chat.username}" if chat.username else None)
    if not enlace:
        enlace = await p.bot.export_chat_invite_link(p.chat.id)
    await p.responder(f"🔗 Enlace de <b>{escape(chat.title)}</b>:\n{enlace}")


@comando("backup", rol="founder")
async def backup(p: Peticion):
    a = db.ajustes(p.chat.id)
    archivo = io.BytesIO(json.dumps(a, ensure_ascii=False, indent=2).encode())
    try:
        await p.bot.send_document(p.user.id, archivo, filename=f"backup_{p.chat.id}.json",
                                  caption=f"💾 Copia de los ajustes de {escape(p.chat.title)}")
    except Exception:
        raise Aviso(f"📭 Abre el chat conmigo (@{p.bot.username}) y toca Iniciar para recibir la copia.")
    await p.responder("💾 Te envié la copia por privado.")


# =====================================================================
# Roles
# =====================================================================

async def cambiar_rol(p: Peticion, rol: str | None, nombre_rol: str):
    obj, _ = await objetivo(p.update, p.context, p.args)
    if obj.id == p.bot.id:
        raise Aviso("😏 Yo ya soy el guardián de este grupo.")
    actual = (await staff(p.bot, p.chat.id)).get(obj.id)
    if actual == "founder":
        raise Aviso("👑 Al fundador no se le cambia el rol.")
    db.actualizar_miembro(p.chat.id, obj.id, rol=rol)
    olvidar_staff(p.chat.id)
    if rol:
        await p.responder(f"🎭 {obj.mencion} ahora es <b>{NOMBRES_ROL[rol]}</b>.")
    else:
        await p.responder(f"🎭 {obj.mencion} ya no es {nombre_rol}.")


def _registrar_roles():
    quien_asigna = {"cofounder": "founder", "free": "mod"}
    for rol in ("cofounder", "admin", "mod", "muter", "cleaner", "helper", "free"):
        requiere = quien_asigna.get(rol, "cofounder")
        comando(rol, rol=requiere)(lambda p, r=rol: cambiar_rol(p, r, NOMBRES_ROL[r]))
        comando(f"un{rol}", rol=requiere)(lambda p, r=rol: cambiar_rol(p, None, NOMBRES_ROL[r]))


_registrar_roles()


async def texto_staff(p: Peticion, solo_bot: bool) -> str:
    roles = (await staff(p.bot, p.chat.id)).items()
    if solo_bot:
        guardados = db.roles_del_chat(p.chat.id)
        roles = guardados.items()
    por_rol: dict[str, list[str]] = {}
    for user_id, rol in roles:
        por_rol.setdefault(rol, []).append(mention_html(user_id, db.nombre_usuario(user_id) or str(user_id)))
    if not por_rol:
        return "👥 No hay roles asignados todavía."
    bloques = []
    for rol in sorted(por_rol, key=nivel, reverse=True):
        bloques.append(f"<b>{NOMBRES_ROL[rol]}</b>\n" + "\n".join(f"  • {m}" for m in por_rol[rol]))
    return ui.tarjeta(f"👥 Staff de {escape(p.chat.title)}", "\n\n".join(bloques))


@comando("staff")
async def staff_cmd(p: Peticion):
    await p.responder(await texto_staff(p, solo_bot=False))


@comando("listroles", rol="admin")
async def listroles(p: Peticion):
    await enviar_privado(p, await texto_staff(p, solo_bot=True))
    await p.responder("📬 Te envié la lista de roles por privado.")


# =====================================================================
# Diversión
# =====================================================================

@comando("top10", "top")
async def top10(p: Peticion):
    db.guardar_conteo_mensajes()
    top = db.top_mensajes(p.chat.id)
    if not top:
        raise Aviso("📊 Todavía no he contado mensajes aquí.")
    medallas = ["🥇", "🥈", "🥉"] + ["👻"] * 7
    lineas = [
        f"{medallas[i]} {mention_html(uid, db.nombre_usuario(uid) or str(uid))} — {n} mensajes"
        for i, (uid, n) in enumerate(top)
    ]
    await p.responder(ui.tarjeta("📊 Los más activos", "\n".join(lineas)))


@comando("loteria", "lotteria", rol="admin")
async def loteria(p: Peticion):
    db.guardar_conteo_mensajes()
    excluir = {p.bot.id} | set(await staff(p.bot, p.chat.id))
    for _ in range(5):
        elegido = db.miembro_al_azar(p.chat.id, excluir)
        if elegido is None:
            break
        try:
            cm = await p.bot.get_chat_member(p.chat.id, elegido)
        except Exception:
            cm = None
        if cm and cm.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED):
            await p.responder(f"🎰 La ruleta fantasma eligió a... {mention_html(elegido, cm.user.full_name)} 🎉")
            return
        excluir.add(elegido)
    raise Aviso("🎰 No encontré a nadie para la lotería todavía.")


@comando("slot")
async def slot(p: Peticion):
    await p.bot.send_dice(p.chat.id, emoji="🎰")


@comando("game", "juegos", solo_grupo=False)
async def game(p: Peticion):
    await p.responder("🎮 <b>Minijuegos fantasma</b>\nElige uno 👇", reply_markup=ui.teclado_juegos())


# =====================================================================
# Para todos
# =====================================================================

@comando("start", solo_grupo=False)
async def start(p: Peticion):
    if p.chat.type == ChatType.PRIVATE and p.texto.startswith("cfg_") and p.texto[4:].lstrip("-").isdigit():
        # Llegó desde el botón "👤 En privado" de /settings
        chat_id = int(p.texto[4:])
        if nivel((await staff(p.bot, chat_id)).get(p.user.id)) < NIVELES["admin"]:
            raise Aviso("⛔ Solo los administradores de ese grupo pueden configurarlo.")
        await ajustes_menu.enviar_menu_privado(p.bot, p.user.id, chat_id)
    elif p.chat.type == ChatType.PRIVATE:
        await p.responder(ui.texto_inicio(p.user.first_name), reply_markup=ui.teclado_inicio(p.bot.username))
    else:
        await p.responder("👻 ¡Aquí estoy patrullando! Usa /help para ver mis comandos.")


@comando("help", "ayuda", solo_grupo=False)
async def ayuda(p: Peticion):
    privado = p.chat.type == ChatType.PRIVATE
    await p.responder(ui.texto_ayuda_indice(), reply_markup=ui.teclado_ayuda_indice(volver=privado))


@comando("me")
async def me(p: Peticion):
    obj = Objetivo(p.user.id, p.user.full_name)
    texto = await texto_info(p, obj)
    reglas = db.ajustes(p.chat.id)["reglas"]
    if reglas:
        texto += f"\n\n📜 <b>Reglas</b>\n{escape(reglas)}"
    await enviar_privado(p, texto)
    await p.responder("📬 Te envié tu ficha por privado.")


@comando("report")
async def report(p: Peticion):
    await avisar_staff(p.update, p.context)


async def avisar_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    config = db.ajustes(chat.id)["reportes"]
    if not config["on"]:
        return
    roles = await staff(context.bot, chat.id)
    admins = [uid for uid, rol in roles.items() if nivel(rol) >= NIVELES["mod"]]
    respuesta = update.message.reply_to_message
    sobre = f" sobre {mention_html(respuesta.from_user.id, respuesta.from_user.full_name)}" if (
        respuesta and respuesta.from_user and not respuesta.forum_topic_created) else ""
    if config["destino"] in ("grupo", "ambos"):
        menciones = "".join(mention_html(uid, "​") for uid in admins)
        await update.message.reply_text(f"🚨 <b>¡Llamando al staff!</b> Hay un reporte{sobre}.{menciones}")
    if config["destino"] in ("privado", "ambos"):
        enlace = enlace_mensaje(chat, (respuesta or update.message).message_id)
        quien = update.effective_user
        texto = (f"🚨 <b>Reporte en {escape(chat.title)}</b>{sobre}\n"
                 f"👤 Lo hizo: {mention_html(quien.id, quien.full_name)}\n"
                 f"🔗 <a href=\"{enlace}\">Ver mensaje</a>")
        for uid in admins:
            try:
                await context.bot.send_message(uid, texto)
            except Exception:
                pass
        if config["destino"] == "privado":
            await update.message.reply_text("🚨 Avisé al staff por privado.")


@comando("ia", "ai", "pregunta", solo_grupo=False)
async def preguntar_ia(p: Peticion):
    pregunta = _texto_o_respondido(p)
    if not pregunta:
        raise Aviso("🤖 Uso: /ia tu pregunta")
    await p.bot.send_chat_action(p.chat.id, "typing")
    await p.responder(await ia.preguntar(pregunta), parse_mode=None)


@comando("traducir", "translate", "trad", solo_grupo=False)
async def traducir(p: Peticion):
    respondido = p.respondido()
    original = respondido and (respondido.text or respondido.caption)
    if not original:
        raise Aviso("🌐 Responde a un mensaje con /traducir [idioma] (por defecto, español).")
    idioma = p.texto or "español"
    await p.bot.send_chat_action(p.chat.id, "typing")
    await p.responder(await ia.traducir(original, idioma), parse_mode=None)
