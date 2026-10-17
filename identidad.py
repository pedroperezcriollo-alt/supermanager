"""Códigos personales de los mánagers.

Cada mánager tiene un código de 4 cifras para poder guardar su quinteto.
En la base de datos solo se guarda una huella (hash) del código, nunca el
código en sí: ni mirando la base de datos se puede saber el de nadie.
"""
import hashlib
import hmac
import secrets

from db import filas, transaccion

ITERACIONES = 100_000


def _huella(codigo, sal):
    return hashlib.pbkdf2_hmac("sha256", codigo.encode(), bytes.fromhex(sal), ITERACIONES).hex()


def cifrar(codigo):
    sal = secrets.token_hex(16)
    return f"{sal}${_huella(codigo, sal)}"


def nuevo_codigo():
    return f"{secrets.randbelow(10_000):04d}"


def tiene_codigo(con, manager_id):
    fila = filas(con, "SELECT pin_hash FROM managers WHERE id = ?", (manager_id,))
    return bool(fila and fila[0][0])


def comprobar(con, manager_id, codigo):
    fila = filas(con, "SELECT pin_hash FROM managers WHERE id = ?", (manager_id,))
    guardado = fila[0][0] if fila else None
    if not guardado or not codigo:
        return False
    sal, huella = guardado.split("$", 1)
    return hmac.compare_digest(_huella(codigo.strip(), sal), huella)


def generar_codigos(con, nombres):
    """Da un código nuevo a cada mánager de la lista (el anterior deja de valer).
    Devuelve {nombre: código}: es la única vez que se pueden ver."""
    nuevos = {nombre: nuevo_codigo() for nombre in nombres}
    with transaccion(con):
        con.executemany("UPDATE managers SET pin_hash = ? WHERE nombre = ?",
                        [(cifrar(codigo), nombre) for nombre, codigo in nuevos.items()])
    return nuevos
