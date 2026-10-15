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


engine = create_engine(_url_base_datos(), pool_pre_ping=True)
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

metadata.create_all(engine)

BIENVENIDA = (
    "👻 ¡Bienvenid@ {nombre} a <b>{grupo}</b>!\n"
    "Esta zona está protegida por Danny Phantom. Lee las reglas con /rules 💚"
)
DESPEDIDA = "🌀 {nombre} cruzó el portal a la Zona Fantasma... ¡hasta pronto!"

AJUSTES_POR_DEFECTO = {
    "reglas": "",
    "bienvenida": {"on": True, "texto": BIENVENIDA},
    "despedida": {"on": False, "texto": DESPEDIDA},
    "captcha": {"on": False, "minutos": 5},
    "antiflood": {"on": True, "mensajes": 5, "segundos": 4},
    "antilink": False,
    "warn_limite": 3,
    "warn_castigo": "ban",
    "ia": True,
    "alias": {},
    "bloqueados": [],
    "palabras": [],
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
