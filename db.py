"""Conexion a la base de datos, en un solo sitio.

- Si existen TURSO_DATABASE_URL y TURSO_AUTH_TOKEN (variables de entorno o
  secretos de Streamlit), se usa la base de datos de Turso en la nube.
- Si no, se usa el archivo local supermanager.db, como hasta ahora.

El resto del codigo solo usa conectar(), consultar() y transaccion(), asi que
no necesita saber cual de las dos esta en uso.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

DB_LOCAL = Path(__file__).resolve().parent / "supermanager.db"


def secreto(nombre, defecto=None):
    """Lee un valor de las variables de entorno o de los secretos de Streamlit."""
    valor = os.environ.get(nombre)
    if valor:
        return valor
    try:
        import streamlit as st
        valor = st.secrets.get(nombre)
    except Exception:  # no hay secrets.toml o no estamos dentro de Streamlit
        valor = None
    return valor if valor else defecto


def usa_turso():
    return bool(secreto("TURSO_DATABASE_URL") and secreto("TURSO_AUTH_TOKEN"))


def descripcion():
    return "Turso (nube)" if usa_turso() else f"archivo local {DB_LOCAL.name}"


def conectar():
    url, token = secreto("TURSO_DATABASE_URL"), secreto("TURSO_AUTH_TOKEN")
    if url and token:
        import libsql  # solo hace falta cuando se usa Turso
        con = libsql.connect(database=url, auth_token=token)
    else:
        con = sqlite3.connect(DB_LOCAL)
    try:
        con.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass  # si el servidor no lo admite, seguimos sin esa red de seguridad
    return con


def filas(con, sql, params=()):
    """Ejecuta una consulta y devuelve todas las filas como tuplas."""
    return con.execute(sql, tuple(params)).fetchall()


def consultar(con, sql, params=()):
    """Ejecuta una consulta y devuelve un DataFrame (sustituye a pd.read_sql_query,
    que no funciona con la conexion de Turso)."""
    cur = con.execute(sql, tuple(params))
    columnas = [d[0] for d in cur.description]
    return pd.DataFrame.from_records(cur.fetchall(), columns=columnas, coerce_float=True)


@contextmanager
def transaccion(con):
    """Agrupa varias escrituras: o se guardan todas o ninguna."""
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
