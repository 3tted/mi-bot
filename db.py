"""Almacenamiento del bot.

Usa DATABASE_URL si existe (por ejemplo una base Postgres gratis de Neon o Supabase).
Sin esa variable guarda todo en un archivo SQLite local (bot.db).

Ojo: en el plan gratis de Render el disco se borra cada vez que el servidor se reinicia,
así que allí conviene usar DATABASE_URL para no perder reglas, advertencias y ajustes.
"""
import copy
import json
import os
import random
import time
from collections import defaultdict

from sqlalchemy import (
    BigInteger, Column, Integer, MetaData, String, Table, Text, create_engine, func, select, update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


def _url_base_datos() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///bot.db")
    # Neon, Supabase y Render entregan "postgres://..." o "postgresql://..."
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


# pool_pre_ping y pool_recycle: Neon duerme la base cuando no se usa y corta las conexiones viejas
engine = create_engine(_url_base_datos(), pool_pre_ping=True, pool_recycle=240)


def descripcion() -> str:
    """Qué base de datos se está usando, sin mostrar la contraseña (para los logs)."""
    if engine.dialect.name == "postgresql":
        return f"Postgres en {engine.url.host} ✅ (los datos se guardan para siempre)"
    return "SQLite local ⚠️ (en Render gratis se borra al reiniciar; configura DATABASE_URL)"
metadata = MetaData()

chats = Table(
    "chats", metadata,
    Column("chat_id", BigInteger, primary_key=True),
    Column("data", Text, nullable=False),
)

miembros = Table(
    "miembros", metadata,
    Column("chat_id", BigInteger, primary_key=True),
    Column("user_id", BigInteger, primary_key=True),
    Column("warns", Integer, nullable=False, default=0),
    Column("msgs", Integer, nullable=False, default=0),
    Column("rol", String(20)),
)

usuarios = Table(
    "usuarios", metadata,
    Column("user_id", BigInteger, primary_key=True),
    Column("username", String(64), index=True),
    Column("nombre", String(256)),
)

# Grupos donde está (o estuvo) el bot. Las fechas son segundos desde 1970 (UTC).
grupos = Table(
    "grupos", metadata,
    Column("chat_id", BigInteger, primary_key=True),
    Column("titulo", String(256)),
    Column("username", String(64)),
    Column("activo", Integer, nullable=False, default=1),
    Column("es_admin", Integer, nullable=False, default=0),
    Column("miembros", Integer),
    Column("agregado_por", BigInteger),
    Column("agregado_nombre", String(256)),
    Column("alta", BigInteger),
    Column("ultima_actividad", BigInteger),
)

# Personas que han usado el bot por privado
privados = Table(
    "privados", metadata,
    Column("user_id", BigInteger, primary_key=True),
    Column("primera_vez", BigInteger),
    Column("ultima_vez", BigInteger),
)

metadata.create_all(engine)

BIENVENIDA = (
    "👻 ¡Bienvenid@ {nombre} a <b>{grupo}</b>!\n"
    "Esta zona está protegida por Danny Phantom. Lee las reglas con /rules 💚"
)
DESPEDIDA = "🌀 {nombre} cruzó el portal a la Zona Fantasma... ¡hasta pronto!"

TIPOS_MEDIA = ["foto", "video", "sticker", "gif", "audio", "voz", "videonota", "documento",
               "encuesta", "contacto", "ubicacion", "dado"]

# Las acciones automáticas usan siempre estos valores: "off", "borrar", "warn", "mute", "kick", "ban"
AJUSTES_POR_DEFECTO = {
    "reglas": "",
    "bienvenida": {"on": True, "texto": BIENVENIDA, "borrar_anterior": False, "autoborrar": 0, "ultimo_id": None},
    "despedida": {"on": False, "texto": DESPEDIDA},
    "captcha": {"on": False, "minutos": 5, "modo": "boton", "fallo": "kick"},
    "antiflood": {"on": True, "mensajes": 5, "segundos": 4, "accion": "mute", "borrar": True},
    "antispam": {"telegram": "off", "reenvios_canal": "off", "enlaces": "off"},
    "alfabetos": {"arabe": "off", "cirilico": "off", "chino": "off", "latino": "off"},
    "reportes": {"on": True, "destino": "grupo"},
    "bloqueos": {"bots": False, "reenvios": "off", "via_bot": "off"},
    "multimedia": {tipo: "off" for tipo in TIPOS_MEDIA},
    "antiporno": {"on": False, "accion": "ban"},
    "warn_limite": 3,
    "warn_castigo": "ban",
    "warn_dias": 0,
    "nocturno": {"on": False, "inicio": 23, "fin": 7, "modo": "silencio", "zona": "America/Puerto_Rico", "avisado": None},
    "etiqueta": {"on": True, "quien": "admins"},
    "enlace": {"personalizado": ""},
    "guardian": {"on": False, "accion": "borrar", "primeros": 5},
    "aprobacion": {"modo": "off"},
    "eliminar": {"entradas": False, "salidas": False, "fijados": False, "comandos": False, "bot_min": 0},
    "temas": {"avisos": None},
    "palabras": [],
    "palabras_castigo": "borrar",
    "recurrentes": [],
    "miembros": {"sin_username": "off", "sin_foto": "off"},
    "enmascarados": {"accion": "off", "permitir_vinculado": True},
    "discusion": {"desfijar": False, "borrar": False},
    "alias": {},
    "alias_solo_admins": False,
    "magicos": {},
    "longitud": {"max": 0, "min": 0, "accion": "borrar"},
    "permisos": {"rules": True, "staff": True, "link": True, "top10": True, "ia": True, "me": True,
                 "report": True, "game": True, "sticker": True},
    "stickers": {"packs": [], "auto": 0, "cada": 0},
    "registro": {"on": False, "chat_id": None},
    "filtros": {},
    "filtros_on": True,
    "ia": True,
    "bloqueados": [],
    "silencio_previo": None,
}

_cache_chats: dict[int, dict] = {}


def _upsert(tabla, valores: dict, claves: list[str], actualizar: dict):
    insertar = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    stmt = insertar(tabla).values(**valores)
    return stmt.on_conflict_do_update(index_elements=claves, set_=actualizar)


# ---------- Ajustes del grupo ----------

def ajustes(chat_id: int) -> dict:
    """Ajustes del grupo (con caché en memoria). Modifica la copia y guárdala con guardar_ajustes."""
    if chat_id not in _cache_chats:
        with engine.connect() as con:
            fila = con.execute(select(chats.c.data).where(chats.c.chat_id == chat_id)).first()
        datos = copy.deepcopy(AJUSTES_POR_DEFECTO)
        if fila:
            for clave, valor in json.loads(fila.data).items():
                if isinstance(valor, dict) and isinstance(datos.get(clave), dict):
                    datos[clave].update(valor)
                else:
                    datos[clave] = valor
        # Versiones anteriores tenían un "antilink" sí/no; ahora vive dentro de antispam
        if datos.pop("antilink", False) and datos["antispam"]["enlaces"] == "off":
            datos["antispam"]["enlaces"] = "borrar"
        _cache_chats[chat_id] = datos
    return copy.deepcopy(_cache_chats[chat_id])


def guardar_ajustes(chat_id: int, datos: dict):
    _cache_chats[chat_id] = copy.deepcopy(datos)
    texto = json.dumps(datos, ensure_ascii=False)
    with engine.begin() as con:
        con.execute(_upsert(chats, {"chat_id": chat_id, "data": texto}, ["chat_id"], {"data": texto}))


# ---------- Miembros (advertencias, roles, mensajes) ----------

def miembro(chat_id: int, user_id: int) -> dict:
    with engine.connect() as con:
        fila = con.execute(
            select(miembros).where(miembros.c.chat_id == chat_id, miembros.c.user_id == user_id)
        ).first()
    if fila:
        return dict(fila._mapping)
    return {"chat_id": chat_id, "user_id": user_id, "warns": 0, "msgs": 0, "rol": None}


def actualizar_miembro(chat_id: int, user_id: int, **campos):
    base = {"chat_id": chat_id, "user_id": user_id, "warns": 0, "msgs": 0, "rol": None}
    base.update(campos)
    with engine.begin() as con:
        con.execute(_upsert(miembros, base, ["chat_id", "user_id"], campos))


def roles_del_chat(chat_id: int) -> dict[int, str]:
    with engine.connect() as con:
        filas = con.execute(
            select(miembros.c.user_id, miembros.c.rol).where(
                miembros.c.chat_id == chat_id, miembros.c.rol.is_not(None)
            )
        ).all()
    return {f.user_id: f.rol for f in filas}


def con_advertencias(chat_id: int) -> list[tuple[int, int]]:
    with engine.connect() as con:
        filas = con.execute(
            select(miembros.c.user_id, miembros.c.warns)
            .where(miembros.c.chat_id == chat_id, miembros.c.warns > 0)
            .order_by(miembros.c.warns.desc())
        ).all()
    return [(f.user_id, f.warns) for f in filas]


def top_mensajes(chat_id: int, limite: int = 10) -> list[tuple[int, int]]:
    with engine.connect() as con:
        filas = con.execute(
            select(miembros.c.user_id, miembros.c.msgs)
            .where(miembros.c.chat_id == chat_id, miembros.c.msgs > 0)
            .order_by(miembros.c.msgs.desc())
            .limit(limite)
        ).all()
    return [(f.user_id, f.msgs) for f in filas]


def miembro_al_azar(chat_id: int, excluir: set[int]) -> int | None:
    with engine.connect() as con:
        ids = con.execute(select(miembros.c.user_id).where(miembros.c.chat_id == chat_id)).scalars().all()
    candidatos = [i for i in ids if i not in excluir]
    return random.choice(candidatos) if candidatos else None


# Los mensajes se cuentan en memoria y se guardan cada minuto para no escribir en cada mensaje.
_mensajes_pendientes: dict[tuple[int, int], int] = defaultdict(int)


def contar_mensaje(chat_id: int, user_id: int):
    _mensajes_pendientes[(chat_id, user_id)] += 1


def guardar_conteo_mensajes():
    if not _mensajes_pendientes:
        return
    pendientes = dict(_mensajes_pendientes)
    _mensajes_pendientes.clear()
    with engine.begin() as con:
        for (chat_id, user_id), n in pendientes.items():
            base = {"chat_id": chat_id, "user_id": user_id, "warns": 0, "msgs": n, "rol": None}
            con.execute(_upsert(miembros, base, ["chat_id", "user_id"], {"msgs": miembros.c.msgs + n}))


# ---------- Usuarios vistos (para encontrar @usuario) ----------

_cache_usuarios: dict[int, tuple[str | None, str]] = {}


def recordar_usuario(user_id: int, username: str | None, nombre: str):
    username = username.lower() if username else None
    if _cache_usuarios.get(user_id) == (username, nombre):
        return
    _cache_usuarios[user_id] = (username, nombre)
    with engine.begin() as con:
        if username:
            # El @usuario pudo pasar a otra cuenta
            con.execute(
                update(usuarios).where(usuarios.c.username == username, usuarios.c.user_id != user_id)
                .values(username=None)
            )
        con.execute(_upsert(
            usuarios, {"user_id": user_id, "username": username, "nombre": nombre},
            ["user_id"], {"username": username, "nombre": nombre},
        ))


def buscar_usuario(username: str) -> tuple[int, str] | None:
    with engine.connect() as con:
        fila = con.execute(
            select(usuarios.c.user_id, usuarios.c.nombre).where(
                func.lower(usuarios.c.username) == username.lstrip("@").lower()
            )
        ).first()
    return (fila.user_id, fila.nombre) if fila else None


def nombre_usuario(user_id: int) -> str | None:
    if user_id in _cache_usuarios:
        return _cache_usuarios[user_id][1]
    with engine.connect() as con:
        fila = con.execute(select(usuarios.c.nombre).where(usuarios.c.user_id == user_id)).first()
    return fila.nombre if fila else None


# ---------- Grupos del bot y uso por privado (panel del dueño) ----------

_ultimo_toque: dict[int, tuple[float, str | None]] = {}


def guardar_grupo(chat_id: int, **campos):
    """Crea o actualiza un grupo. Solo cambia los campos que se pasan."""
    ahora = int(time.time())
    base = {"chat_id": chat_id, "activo": 1, "es_admin": 0, "alta": ahora, "ultima_actividad": ahora}
    base.update(campos)
    actualizar = dict(campos) or {"ultima_actividad": ahora}
    with engine.begin() as con:
        con.execute(_upsert(grupos, base, ["chat_id"], actualizar))


def tocar_grupo(chat_id: int, titulo: str | None, username: str | None):
    """Marca actividad en un grupo, como mucho una escritura cada 5 minutos por grupo."""
    ahora = time.time()
    ultimo = _ultimo_toque.get(chat_id)
    if ultimo and ahora - ultimo[0] < 300 and ultimo[1] == titulo:
        return
    _ultimo_toque[chat_id] = (ahora, titulo)
    guardar_grupo(chat_id, titulo=titulo, username=username, activo=1, ultima_actividad=int(ahora))


def lista_grupos(activos: bool = True) -> list[dict]:
    with engine.connect() as con:
        filas = con.execute(
            select(grupos).where(grupos.c.activo == (1 if activos else 0))
            .order_by(grupos.c.ultima_actividad.desc())
        ).all()
    return [dict(f._mapping) for f in filas]


def grupo(chat_id: int) -> dict | None:
    with engine.connect() as con:
        fila = con.execute(select(grupos).where(grupos.c.chat_id == chat_id)).first()
    return dict(fila._mapping) if fila else None


def actividad_grupo(chat_id: int) -> tuple[int, int]:
    """(personas que han escrito, mensajes contados)"""
    with engine.connect() as con:
        fila = con.execute(
            select(func.count(), func.coalesce(func.sum(miembros.c.msgs), 0))
            .where(miembros.c.chat_id == chat_id, miembros.c.msgs > 0)
        ).first()
    return fila[0], fila[1]


_ultimo_privado: dict[int, float] = {}


def registrar_privado(user_id: int):
    """Como mucho una escritura cada 5 minutos por persona."""
    if time.time() - _ultimo_privado.get(user_id, 0) < 300:
        return
    _ultimo_privado[user_id] = time.time()
    ahora = int(time.time())
    with engine.begin() as con:
        con.execute(_upsert(
            privados, {"user_id": user_id, "primera_vez": ahora, "ultima_vez": ahora},
            ["user_id"], {"ultima_vez": ahora},
        ))


def totales() -> dict:
    hace_una_semana = int(time.time()) - 7 * 86400
    with engine.connect() as con:
        return {
            "grupos": con.execute(select(func.count()).where(grupos.c.activo == 1)).scalar(),
            "grupos_fuera": con.execute(select(func.count()).where(grupos.c.activo == 0)).scalar(),
            "privados": con.execute(select(func.count()).select_from(privados)).scalar(),
            "privados_semana": con.execute(
                select(func.count()).where(privados.c.ultima_vez >= hace_una_semana)).scalar(),
            "usuarios": con.execute(select(func.count()).select_from(usuarios)).scalar(),
            "mensajes": con.execute(select(func.coalesce(func.sum(miembros.c.msgs), 0))).scalar(),
        }


def chats_con_ajustes() -> list[int]:
    """IDs de todos los grupos que tienen ajustes guardados."""
    with engine.connect() as con:
        return list(con.execute(select(chats.c.chat_id)).scalars().all())


def ids_miembros(chat_id: int) -> list[int]:
    with engine.connect() as con:
        return list(con.execute(select(miembros.c.user_id).where(miembros.c.chat_id == chat_id)).scalars().all())


def mensajes_de(chat_id: int, user_id: int) -> int:
    """Mensajes de una persona en un grupo, contando los que aún no se guardaron."""
    return miembro(chat_id, user_id)["msgs"] + _mensajes_pendientes.get((chat_id, user_id), 0)
