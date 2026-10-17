from db import conectar, descripcion, filas, transaccion
from procesar_jornada import CONFIG_DEFECTO, leer_config

AMIGOS = ["Pedro", "Balms", "Koke", "Migui", "Caellum", "Liam", "Gabriel",
          "Nico", "Angel", "Adrian", "Wilker", "Jaime", "Damian"]

PRESUPUESTO = 3_000_000
PRECIO_BASE = 500_000
FACTOR_PRECIO = 15_000  # precio = base + valoracion * factor (como en el Excel)

# Tablas en orden de dependencias (las de arriba no dependen de las de abajo).
# Se usa tambien para las copias de seguridad.
TABLAS = ["jugadores", "managers", "jornadas", "config",
          "estadisticas", "plantillas", "puntos_extra", "historial_precios"]
OBJETOS = TABLAS + ["max_5_titulares", "clasificacion"]

# Una sentencia por elemento: Turso no garantiza ejecutar varias de golpe.
SCHEMA = [
    # Jugadores: vosotros (es_amigo=1) y, si se quiere, rivales de liga (es_amigo=0)
    """CREATE TABLE IF NOT EXISTS jugadores (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre        TEXT UNIQUE NOT NULL,
        equipo_real   TEXT NOT NULL DEFAULT 'Vuestro equipo',
        es_amigo      INTEGER NOT NULL DEFAULT 1 CHECK (es_amigo IN (0, 1)),
        precio_actual INTEGER NOT NULL DEFAULT 500000
    )""",

    # Mánagers: cada uno puede estar enlazado con su propio jugador (para el autotopillo).
    # pin_hash: huella del código personal (ver identidad.py), nunca el código en claro
    """CREATE TABLE IF NOT EXISTS managers (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre       TEXT UNIQUE NOT NULL,
        presupuesto  INTEGER NOT NULL DEFAULT 3000000,
        jugador_id   INTEGER UNIQUE REFERENCES jugadores(id),
        pin_hash     TEXT
    )""",

    # Jornadas: cada partido real. El cierre de mercado es la hora del salto inicial
    """CREATE TABLE IF NOT EXISTS jornadas (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        numero          INTEGER UNIQUE NOT NULL,
        fecha           TEXT,
        cierre_mercado  TEXT,
        estado          TEXT NOT NULL DEFAULT 'abierta'
                        CHECK (estado IN ('abierta', 'cerrada', 'puntuada'))
    )""",

    # Parametros del mercado editables desde el panel de admin
    """CREATE TABLE IF NOT EXISTS config (
        clave TEXT PRIMARY KEY,
        valor REAL NOT NULL
    )""",

    # Estadisticas de cada jugador en cada jornada. La valoracion se calcula sola.
    """CREATE TABLE IF NOT EXISTS estadisticas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        jornada_id  INTEGER NOT NULL REFERENCES jornadas(id),
        jugador_id  INTEGER NOT NULL REFERENCES jugadores(id),
        pts INTEGER NOT NULL DEFAULT 0,
        reb INTEGER NOT NULL DEFAULT 0,
        ast INTEGER NOT NULL DEFAULT 0,
        rob INTEGER NOT NULL DEFAULT 0,
        tap INTEGER NOT NULL DEFAULT 0,
        fr  INTEGER NOT NULL DEFAULT 0,   -- faltas recibidas
        t3f INTEGER NOT NULL DEFAULT 0,   -- triples fallados
        tlf INTEGER NOT NULL DEFAULT 0,   -- tiros libres fallados
        t2f INTEGER NOT NULL DEFAULT 0,   -- tiros de 2 fallados
        per INTEGER NOT NULL DEFAULT 0,   -- perdidas
        fc  INTEGER NOT NULL DEFAULT 0,   -- faltas cometidas
        airballs    INTEGER NOT NULL DEFAULT 0,
        game_winner INTEGER NOT NULL DEFAULT 0 CHECK (game_winner IN (0, 1)),
        fuente      TEXT NOT NULL DEFAULT 'manual' CHECK (fuente IN ('manual', 'feb', 'acb', 'csv')),
        valoracion  INTEGER GENERATED ALWAYS AS
            (pts + reb + ast + rob + tap + fr - t3f - tlf - t2f - per - fc) VIRTUAL,
        UNIQUE (jornada_id, jugador_id)
    )""",

    # Quinteto de cada mánager en cada jornada (permite repetidos entre mánagers)
    """CREATE TABLE IF NOT EXISTS plantillas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        jornada_id  INTEGER NOT NULL REFERENCES jornadas(id),
        manager_id  INTEGER NOT NULL REFERENCES managers(id),
        jugador_id  INTEGER NOT NULL REFERENCES jugadores(id),
        precio_pagado INTEGER NOT NULL,
        UNIQUE (jornada_id, manager_id, jugador_id)
    )""",

    # Maximo 5 titulares por mánager y jornada
    """CREATE TRIGGER IF NOT EXISTS max_5_titulares
    BEFORE INSERT ON plantillas
    WHEN (SELECT COUNT(*) FROM plantillas
          WHERE jornada_id = NEW.jornada_id AND manager_id = NEW.manager_id) >= 5
    BEGIN
        SELECT RAISE(ABORT, 'Un manager solo puede tener 5 titulares por jornada');
    END""",

    # Bonus y sanciones (airball, autotopillo, cambio tarde, camiseta, etc.)
    """CREATE TABLE IF NOT EXISTS puntos_extra (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        jornada_id  INTEGER NOT NULL REFERENCES jornadas(id),
        manager_id  INTEGER NOT NULL REFERENCES managers(id),
        motivo      TEXT NOT NULL,
        puntos      INTEGER NOT NULL
    )""",

    # Historial de precios para ver subidas y bajadas
    """CREATE TABLE IF NOT EXISTS historial_precios (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        jugador_id  INTEGER NOT NULL REFERENCES jugadores(id),
        jornada_id  INTEGER REFERENCES jornadas(id),
        precio      INTEGER NOT NULL
    )""",

    # Clasificacion general: se calcula, no se guarda
    """CREATE VIEW IF NOT EXISTS clasificacion AS
    SELECT m.id AS manager_id,
           m.nombre,
           COALESCE((SELECT SUM(e.valoracion
                                * CASE WHEN e.game_winner = 1 THEN 2 ELSE 1 END
                                - e.airballs * 2)
                     FROM plantillas p
                     JOIN estadisticas e ON e.jornada_id = p.jornada_id
                                        AND e.jugador_id = p.jugador_id
                     WHERE p.manager_id = m.id), 0)
           + COALESCE((SELECT SUM(x.puntos) FROM puntos_extra x
                       WHERE x.manager_id = m.id), 0) AS puntos_totales,
           m.presupuesto - COALESCE((SELECT SUM(p.precio_pagado) FROM plantillas p
                                     WHERE p.manager_id = m.id
                                       AND p.jornada_id = (SELECT MAX(jornada_id) FROM plantillas
                                                           WHERE manager_id = m.id)), 0) AS dinero_restante
    FROM managers m
    ORDER BY puntos_totales DESC""",
]


def crear_esquema(con):
    """Crea tablas, trigger y vista que falten (no toca los datos)."""
    for sentencia in SCHEMA:
        con.execute(sentencia)


def esquema_completo(con):
    marcas = ", ".join("?" for _ in OBJETOS)
    n = filas(con, f"SELECT COUNT(*) FROM sqlite_master WHERE name IN ({marcas})", OBJETOS)[0][0]
    return n == len(OBJETOS)


def _sembrar(con):
    """Amigos (como jugadores y mánagers) y reglas por defecto, sin duplicar nada."""
    for nombre in AMIGOS:
        con.execute(
            "INSERT OR IGNORE INTO jugadores (nombre, precio_actual) VALUES (?, ?)",
            (nombre, PRECIO_BASE))
        con.execute(
            """INSERT OR IGNORE INTO managers (nombre, presupuesto, jugador_id)
               VALUES (?, ?, (SELECT id FROM jugadores WHERE nombre = ?))""",
            (nombre, PRESUPUESTO, nombre))
    con.executemany("INSERT OR IGNORE INTO config (clave, valor) VALUES (?, ?)",
                    list(CONFIG_DEFECTO.items()))


def inicializar(con=None):
    """Crea lo que falte y mete a los amigos y las reglas por defecto.
    Se puede ejecutar las veces que haga falta: no duplica ni borra nada."""
    propia = con is None
    con = con or conectar()
    try:
        with transaccion(con):
            crear_esquema(con)
            _sembrar(con)
    finally:
        if propia:
            con.close()
    print(f"Base de datos lista ({descripcion()}) con {len(AMIGOS)} managers/jugadores.")


def _migrar(con):
    """Pone al día bases de datos creadas con versiones anteriores."""
    columnas = [r[1] for r in filas(con, "PRAGMA table_info(managers)")]
    if "pin_hash" not in columnas:
        with transaccion(con):
            con.execute("ALTER TABLE managers ADD COLUMN pin_hash TEXT")


def asegurar_esquema(con):
    """Inicializa solo si falta algo (dos consultas en el caso normal)."""
    if not esquema_completo(con):
        inicializar(con)
    _migrar(con)


def empezar_de_cero(con, reglas_por_defecto=False):
    """Borra todo lo jugado (jornadas, quintetos, estadísticas, sanciones e historial)
    y deja a todos los jugadores con el precio base. Mantiene los mánagers y sus
    códigos. Con reglas_por_defecto=True, también vuelve a las reglas iniciales."""
    with transaccion(con):
        for tabla in ["historial_precios", "puntos_extra", "plantillas", "estadisticas", "jornadas"]:
            con.execute(f"DELETE FROM {tabla}")
        if reglas_por_defecto:
            con.execute("DELETE FROM config")
        _sembrar(con)  # repone amigos o reglas que falten
        precio_base = int(leer_config(con)["precio_base"])
        con.execute("UPDATE jugadores SET precio_actual = ?", (precio_base,))


if __name__ == "__main__":
    inicializar()
