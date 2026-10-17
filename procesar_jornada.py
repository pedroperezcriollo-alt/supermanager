from db import conectar, filas

MOTIVO_AUTOTOPILLO = "Castigo Autotopillo"

CAMPOS = ["pts", "reb", "ast", "rob", "tap", "fr", "t3f", "tlf", "t2f",
          "per", "fc", "airballs", "game_winner"]

# Parametros editables desde el panel de admin (tabla `config`)
CONFIG_DEFECTO = {
    "precio_base": 500_000,
    "factor_precio": 15_000,         # euros por punto de valoracion
    "peso_precio_anterior": 0.70,    # 70% precio anterior + 30% partido actual
    "suelo": 300_000,
    "techo": 1_500_000,
    "pen_autotopillo": -3,
}


def leer_config(con):
    """Reglas del mercado. Si falta alguna en la BD, se usa la de por defecto."""
    cfg = dict(CONFIG_DEFECTO)
    cfg.update(dict(filas(con, "SELECT clave, valor FROM config")))
    return cfg


def guardar_config(con, valores):
    con.executemany("INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)",
                    [(k, float(v)) for k, v in valores.items()])


def procesar_cierre_jornada(numero_jornada, stats_jugadores, penalizaciones=None, con=None):
    """
    stats_jugadores: {"Pedro": {"pts": 20, "reb": 5, ..., "airballs": 0, "game_winner": 0}, ...}
    penalizaciones:  [{"manager": "Koke", "motivo": "Cambio tarde", "puntos": -15}, ...]

    Es idempotente: se puede reprocesar la misma jornada (por ejemplo para corregir
    una estadistica) sin que los precios ni las sanciones se dupliquen.
    Las sanciones de la jornada se rehacen desde `penalizaciones`, asi que hay que
    pasarlas todas cada vez. Reprocesa siempre la ULTIMA jornada procesada.
    Devuelve una lista de lineas de log.

    Las consultas van agrupadas (pocas idas y vueltas) porque con Turso cada
    consulta viaja por internet.
    """
    log = []
    propia = con is None
    con = con or conectar()
    try:
        cfg = leer_config(con)

        con.execute("INSERT OR IGNORE INTO jornadas (numero, estado) VALUES (?, 'cerrada')",
                    (numero_jornada,))
        jornada_id = filas(con, "SELECT id FROM jornadas WHERE numero = ?", (numero_jornada,))[0][0]

        # Ultimo precio de cada jugador en jornadas anteriores a esta
        # (el orden ascendente hace que el dict se quede con el mas reciente)
        previo = dict(filas(con,
            """SELECT h.jugador_id, h.precio FROM historial_precios h
               JOIN jornadas j ON j.id = h.jornada_id
               WHERE j.numero < ?
               ORDER BY j.numero, h.id""", (numero_jornada,)))

        # 0. Deshacer un proceso anterior de esta jornada
        ya_procesados = [r[0] for r in filas(con,
            "SELECT DISTINCT jugador_id FROM historial_precios WHERE jornada_id = ?", (jornada_id,))]
        if ya_procesados:
            con.executemany("UPDATE jugadores SET precio_actual = ? WHERE id = ?",
                            [(int(previo.get(jid, cfg["precio_base"])), jid) for jid in ya_procesados])
        con.execute("DELETE FROM historial_precios WHERE jornada_id = ?", (jornada_id,))
        con.execute("DELETE FROM puntos_extra WHERE jornada_id = ?", (jornada_id,))
        con.execute("DELETE FROM estadisticas WHERE jornada_id = ?", (jornada_id,))

        # 1. Estadisticas
        jugadores = {nombre: (jid, precio)
                     for jid, nombre, precio in filas(con, "SELECT id, nombre, precio_actual FROM jugadores")}
        nuevas = [(jornada_id, jugadores[nombre][0], *[int(stats.get(c, 0) or 0) for c in CAMPOS])
                  for nombre, stats in stats_jugadores.items() if nombre in jugadores]
        if nuevas:
            con.executemany(
                f"""INSERT INTO estadisticas (jornada_id, jugador_id, {', '.join(CAMPOS)}, fuente)
                    VALUES (?, ?, {', '.join('?' for _ in CAMPOS)}, 'manual')""", nuevas)
        valoraciones = dict(filas(con,
            "SELECT jugador_id, valoracion FROM estadisticas WHERE jornada_id = ?", (jornada_id,)))

        # 2. Mercado dinamico
        cambios = []
        for nombre in stats_jugadores:
            if nombre not in jugadores:
                log.append(f"AVISO: el jugador {nombre} no existe en la BD. Saltado.")
                continue
            jugador_id, precio_actual = jugadores[nombre]
            valoracion = valoraciones[jugador_id]

            base = previo.get(jugador_id, precio_actual)
            teorico = cfg["precio_base"] + valoracion * cfg["factor_precio"]
            peso = cfg["peso_precio_anterior"]
            nuevo = base * peso + teorico * (1 - peso)
            precio_final = int(min(max(round(nuevo, -3), cfg["suelo"]), cfg["techo"]))

            cambios.append((precio_final, jugador_id))
            log.append(f"{nombre}: valoracion {valoracion} | {int(base):,} -> {precio_final:,} EUR")
        if cambios:
            con.executemany("UPDATE jugadores SET precio_actual = ? WHERE id = ?", cambios)
            con.executemany("INSERT INTO historial_precios (jugador_id, jornada_id, precio) VALUES (?, ?, ?)",
                            [(jid, jornada_id, precio) for precio, jid in cambios])

        # 3. Sanciones manuales (cambio tarde, camiseta, etc.)
        id_manager = dict(filas(con, "SELECT nombre, id FROM managers"))
        for p in penalizaciones or []:
            if p["manager"] not in id_manager:
                log.append(f"AVISO: el manager {p['manager']} no existe. Sancion ignorada.")
                continue
            con.execute("INSERT INTO puntos_extra (jornada_id, manager_id, motivo, puntos) VALUES (?, ?, ?, ?)",
                        (jornada_id, id_manager[p["manager"]], p["motivo"], int(p["puntos"])))
            log.append(f"Sancion a {p['manager']}: {p['motivo']} ({int(p['puntos'])} pts)")

        # 4. Ley del Autotopillo: te fichas a ti mismo y eres el peor de tu quinteto
        pen_auto = int(cfg["pen_autotopillo"])
        quintetos = {}
        for m_id, jug_id, val in filas(con,
                """SELECT p.manager_id, p.jugador_id, e.valoracion FROM plantillas p
                   JOIN estadisticas e ON e.jornada_id = p.jornada_id AND e.jugador_id = p.jugador_id
                   WHERE p.jornada_id = ?""", (jornada_id,)):
            quintetos.setdefault(m_id, {})[jug_id] = val
        for m_id, m_nombre, propio in filas(con,
                "SELECT id, nombre, jugador_id FROM managers WHERE jugador_id IS NOT NULL"):
            vals = quintetos.get(m_id, {})
            if propio not in vals or len(vals) < 2:
                continue  # no se ficho a si mismo, no jugo, o no hay con quien compararse
            otros = [v for k, v in vals.items() if k != propio]
            if vals[propio] < min(otros):  # estrictamente el peor (un empate no castiga)
                con.execute("INSERT INTO puntos_extra (jornada_id, manager_id, motivo, puntos) VALUES (?, ?, ?, ?)",
                            (jornada_id, m_id, MOTIVO_AUTOTOPILLO, pen_auto))
                log.append(f"{m_nombre} se ficho a si mismo y fue el peor ({vals[propio]}): {pen_auto} pts")

        con.execute("UPDATE jornadas SET estado = 'puntuada' WHERE id = ?", (jornada_id,))
        con.commit()
        log.append("Jornada procesada.")
        return log
    except Exception:
        con.rollback()
        raise
    finally:
        if propia:
            con.close()
