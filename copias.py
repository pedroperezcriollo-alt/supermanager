"""Copias de seguridad: bajar todos los datos a un archivo .db y restaurar desde uno.

Sirve tambien para pasar a Turso los datos que ya tengas en el supermanager.db
de tu PC: lo subes desde el panel de admin y listo.
"""
import sqlite3
import tempfile
from pathlib import Path

from crear_db import TABLAS, crear_esquema
from db import filas, transaccion

LOTE = 50  # filas por INSERT, para hacer pocos viajes a Turso


def _existe(con, tabla):
    return bool(filas(con, "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (tabla,)))


def _columnas(con, tabla):
    # table_info no incluye columnas calculadas (valoracion), que no se copian
    return [r[1] for r in filas(con, f"PRAGMA table_info({tabla})")]


def copiar_datos(origen, destino):
    """Sustituye TODOS los datos de `destino` por los de `origen`, con los mismos ids.
    Va en una transaccion: si algo falla, `destino` se queda como estaba.
    Devuelve {tabla: filas copiadas}."""
    resumen = {}
    with transaccion(destino):
        for tabla in reversed(TABLAS):
            destino.execute(f"DELETE FROM {tabla}")
        for tabla in TABLAS:
            if not _existe(origen, tabla):
                resumen[tabla] = 0
                continue
            en_destino = set(_columnas(destino, tabla))
            cols = [c for c in _columnas(origen, tabla) if c in en_destino]
            datos = filas(origen, f"SELECT {', '.join(cols)} FROM {tabla} ORDER BY rowid")
            hueco = "(" + ", ".join("?" for _ in cols) + ")"
            for i in range(0, len(datos), LOTE):
                lote = datos[i:i + LOTE]
                destino.execute(
                    f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES {', '.join([hueco] * len(lote))}",
                    [v for fila in lote for v in fila])
            resumen[tabla] = len(datos)
    return resumen


def exportar(con):
    """Devuelve el contenido de un archivo .db con todos los datos actuales."""
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "copia.db"
        destino = sqlite3.connect(ruta)
        try:
            crear_esquema(destino)
            destino.commit()
            copiar_datos(con, destino)
        finally:
            destino.close()
        return ruta.read_bytes()


def importar(con, contenido):
    """Sustituye los datos de `con` por los del archivo .db recibido (bytes)."""
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "subida.db"
        ruta.write_bytes(contenido)
        origen = sqlite3.connect(ruta)
        try:
            try:
                valido = _existe(origen, "jugadores") and _existe(origen, "managers")
            except sqlite3.DatabaseError:
                valido = False
            if not valido:
                raise ValueError("ese archivo no es una base de datos del SuperManager")
            return copiar_datos(origen, con)
        finally:
            origen.close()
