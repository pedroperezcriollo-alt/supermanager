from datetime import datetime, date, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import streamlit as st

import copias
import crear_db
import db
import extras
from procesar_jornada import (CAMPOS, CONFIG_DEFECTO, MOTIVO_AUTOTOPILLO,
                              guardar_config, leer_config, procesar_cierre_jornada)

ADMIN_PASSWORD = db.secreto("SM_ADMIN_PASSWORD", "cambiame")

# El servidor de Streamlit Cloud va en hora UTC: todas las horas de la liga
# (cierre del mercado) se interpretan en hora de Madrid.
try:
    ZONA = ZoneInfo("Europe/Madrid")
except ZoneInfoNotFoundError:  # Windows sin el paquete tzdata
    ZONA = None


def ahora():
    """Hora actual en Madrid, sin zona (para comparar con las horas guardadas)."""
    return datetime.now(ZONA).replace(tzinfo=None) if ZONA else datetime.now()

st.set_page_config(page_title="SuperManager Basket", page_icon="🏀", layout="centered")


# ---------- conexion ----------
@st.cache_resource(show_spinner="Preparando la base de datos…")
def preparar_bd(_con):
    """Crea las tablas si faltan. Solo se ejecuta una vez por arranque de la app."""
    crear_db.asegurar_esquema(_con)
    return True


try:
    CON = db.conectar()  # una conexion por cada recarga de la pagina
    preparar_bd(CON)
except Exception as e:
    st.error(f"No se pudo conectar con la base de datos ({db.descripcion()}): {e}")
    st.stop()


# ---------- utilidades ----------
def query(sql, params=()):
    return db.consultar(CON, sql, params)


def eur(n):
    return f"{int(n):,}".replace(",", ".") + " €"


def jornada_abierta():
    df = query("SELECT * FROM jornadas WHERE estado = 'abierta' ORDER BY numero DESC LIMIT 1")
    return None if df.empty else df.iloc[0]


def mercado_cerrado(j):
    if j is None or j["estado"] != "abierta":
        return True
    cierre = j["cierre_mercado"]
    if isinstance(cierre, str) and cierre:
        try:
            return ahora() >= datetime.fromisoformat(cierre)
        except ValueError:
            return False
    return False


SQL_JORNADA = """
SELECT m.nombre AS Mánager,
       GROUP_CONCAT(j.nombre, ', ') AS Quinteto,
       SUM(COALESCE(e.valoracion, 0) * CASE WHEN e.game_winner = 1 THEN 2 ELSE 1 END
           - COALESCE(e.airballs, 0) * 2)
       + COALESCE((SELECT SUM(x.puntos) FROM puntos_extra x
                   WHERE x.manager_id = m.id AND x.jornada_id = ?), 0) AS Puntos
FROM plantillas p
JOIN managers m ON m.id = p.manager_id
JOIN jugadores j ON j.id = p.jugador_id
LEFT JOIN estadisticas e ON e.jornada_id = p.jornada_id AND e.jugador_id = p.jugador_id
WHERE p.jornada_id = ?
GROUP BY m.id
ORDER BY Puntos DESC
"""

st.title("🏀 SuperManager Basket")
tab_clas, tab_quinteto, tab_pista, tab_jug, tab_admin = st.tabs(
    ["Clasificación", "Mi quinteto", "Pista", "Jugadores", "Panel de admin"])


# ---------- 1. CLASIFICACIÓN ----------
with tab_clas:
    st.subheader("Clasificación general")
    df = query("SELECT nombre, puntos_totales, dinero_restante FROM clasificacion")
    df.insert(0, "Puesto", range(1, len(df) + 1))
    df["dinero_restante"] = df["dinero_restante"].map(eur)
    df.columns = ["Puesto", "Mánager", "Puntos", "Presupuesto restante"]
    st.dataframe(df, hide_index=True, width="stretch")
    if len(df) and df["Puntos"].max() > 0:
        st.caption(f"🔴 Farolillo rojo ahora mismo: **{df.iloc[-1]['Mánager']}**")

    st.subheader("Por jornada")
    jornadas = query("SELECT id, numero, estado, cierre_mercado FROM jornadas ORDER BY numero DESC")
    if jornadas.empty:
        st.info("Todavía no hay jornadas.")
    else:
        numero = st.selectbox("Jornada", jornadas["numero"].tolist(), key="sel_jornada_clas")
        fila = jornadas[jornadas["numero"] == numero].iloc[0]
        if mercado_cerrado(fila):
            jid_sel = int(fila["id"])
            det = query(SQL_JORNADA, (jid_sel, jid_sel))
            if det.empty:
                st.info("Nadie guardó quinteto en esta jornada.")
            else:
                st.dataframe(det, hide_index=True, width="stretch")
                if fila["estado"] == "puntuada":
                    st.caption(f"👕 Último de la jornada (camiseta graciosa): **{det.iloc[-1]['Mánager']}**")
        else:
            st.info("Los quintetos se verán cuando se cierre el mercado.")


# ---------- 2. MI QUINTETO ----------
with tab_quinteto:
    st.subheader("Elige tus 5 titulares")
    j = jornada_abierta()
    if j is None:
        st.info("No hay ninguna jornada abierta ahora mismo.")
    else:
        jid = int(j["id"])
        cierre = j["cierre_mercado"] if isinstance(j["cierre_mercado"], str) else None
        st.write(f"**Jornada {int(j['numero'])}**" + (f" · cierre del mercado: {cierre}" if cierre else ""))

        if mercado_cerrado(j):
            st.warning("El mercado está cerrado. No se pueden hacer cambios (Ley 5: −15 pts).")
        else:
            managers = query("SELECT id, nombre, presupuesto FROM managers ORDER BY nombre")
            nombre_m = st.selectbox("¿Quién eres?", managers["nombre"].tolist())
            m = managers[managers["nombre"] == nombre_m].iloc[0]

            jug = query("SELECT id, nombre, precio_actual FROM jugadores ORDER BY precio_actual DESC, nombre")
            precios = dict(zip(jug["id"], jug["precio_actual"]))
            nombres = dict(zip(jug["id"], jug["nombre"]))

            actual = query("SELECT jugador_id FROM plantillas WHERE jornada_id = ? AND manager_id = ?",
                           (jid, int(m["id"])))["jugador_id"].tolist()

            elegidos = st.multiselect(
                "Titulares (máximo 5)", jug["id"].tolist(), default=actual, max_selections=5,
                format_func=lambda i: f"{nombres[i]} — {eur(precios[i])}",
                key=f"q_{jid}_{int(m['id'])}")

            coste = sum(precios[i] for i in elegidos)
            restante = int(m["presupuesto"]) - coste
            c1, c2, c3 = st.columns(3)
            c1.metric("Elegidos", f"{len(elegidos)}/5")
            c2.metric("Coste", eur(coste))
            c3.metric("Te queda", eur(restante))
            extras.pista_en_vivo(query, elegidos)

            if st.button("Guardar quinteto", type="primary"):
                if len(elegidos) != 5:
                    st.error("Tienes que elegir exactamente 5 jugadores.")
                elif restante < 0:
                    st.error(f"Te pasas del presupuesto por {eur(-restante)}.")
                else:
                    with db.transaccion(CON):
                        CON.execute("DELETE FROM plantillas WHERE jornada_id = ? AND manager_id = ?",
                                    (jid, int(m["id"])))
                        CON.executemany(
                            "INSERT INTO plantillas (jornada_id, manager_id, jugador_id, precio_pagado) VALUES (?, ?, ?, ?)",
                            [(jid, int(m["id"]), int(i), int(precios[i])) for i in elegidos])
                    st.success("Quinteto guardado ✅")

    with st.expander("Mercado: precios actuales"):
        mercado = query("SELECT nombre AS Jugador, precio_actual AS Precio FROM jugadores ORDER BY Precio DESC")
        mercado["Precio"] = mercado["Precio"].map(eur)
        st.dataframe(mercado, hide_index=True, width="stretch")


# ---------- PISTA Y JUGADORES ----------
with tab_pista:
    extras.render_pista(query, eur, mercado_cerrado)

with tab_jug:
    extras.render_jugadores(query, eur)


# ---------- 3. PANEL DE ADMIN ----------
with tab_admin:
    st.subheader("Panel de admin")
    clave = st.text_input("Contraseña de admin", type="password")
    if clave != ADMIN_PASSWORD:
        if clave:
            st.error("Contraseña incorrecta.")
        st.stop()
    if ADMIN_PASSWORD == "cambiame":
        st.warning("Estás usando la contraseña por defecto. Pon SM_ADMIN_PASSWORD en los secretos de la app.")
    st.caption(f"Base de datos en uso: {db.descripcion()}")

    st.session_state.setdefault("ver", 0)

    # --- A. Jornadas ---
    with st.expander("1. Abrir / cerrar jornadas", expanded=True):
        todas = query("SELECT numero, fecha, cierre_mercado, estado FROM jornadas ORDER BY numero DESC")
        siguiente = int(todas["numero"].max()) + 1 if not todas.empty else 1
        with st.form("nueva_jornada"):
            c1, c2, c3 = st.columns(3)
            n = c1.number_input("Nº jornada", min_value=1, value=siguiente, step=1)
            f = c2.date_input("Fecha del partido", value=ahora().date())
            h = c3.time_input("Hora del salto inicial", value=time(20, 0))
            if st.form_submit_button("Abrir jornada"):
                if db.filas(CON, "SELECT 1 FROM jornadas WHERE numero = ?", (int(n),)):
                    st.error("Esa jornada ya existe.")
                else:
                    with db.transaccion(CON):
                        CON.execute(
                            "INSERT INTO jornadas (numero, fecha, cierre_mercado, estado) VALUES (?, ?, ?, 'abierta')",
                            (int(n), f.isoformat(), datetime.combine(f, h).isoformat(timespec="minutes")))
                    st.rerun()
        if not todas.empty:
            st.dataframe(todas, hide_index=True, width="stretch")
            cA, cB = st.columns(2)
            num_sel = cA.selectbox("Jornada", todas["numero"].tolist(), key="adm_sel_jornada")
            nuevo_estado = cB.selectbox("Estado", ["abierta", "cerrada"], key="adm_estado")
            if st.button("Cambiar estado"):
                with db.transaccion(CON):
                    CON.execute("UPDATE jornadas SET estado = ? WHERE numero = ?", (nuevo_estado, int(num_sel)))
                st.rerun()

    # --- B. Resultados del partido ---
    with st.expander("2. Meter estadísticas y cerrar jornada", expanded=True):
        if todas.empty:
            st.info("Abre una jornada primero.")
        else:
            num = st.selectbox("Jornada a puntuar", todas["numero"].tolist(), key="adm_puntuar")
            jid = int(query("SELECT id FROM jornadas WHERE numero = ?", (int(num),)).iloc[0]["id"])

            base = query(f"""
                SELECT j.nombre AS Jugador, (e.id IS NOT NULL) AS Jugó,
                       {', '.join(f'COALESCE(e.{c}, 0) AS {c.upper()}' for c in CAMPOS)}
                FROM jugadores j
                LEFT JOIN estadisticas e ON e.jugador_id = j.id AND e.jornada_id = ?
                ORDER BY j.nombre""", (jid,))
            base["Jugó"] = base["Jugó"].astype(bool)
            base["GAME_WINNER"] = base["GAME_WINNER"].astype(bool)

            cfg_cols = {"Jugó": st.column_config.CheckboxColumn("Jugó", help="Marca solo a quien jugó")}
            for c in CAMPOS:
                if c == "game_winner":
                    cfg_cols["GAME_WINNER"] = st.column_config.CheckboxColumn("Canasta del gane")
                else:
                    cfg_cols[c.upper()] = st.column_config.NumberColumn(c.upper(), min_value=0, step=1)

            ed = st.data_editor(base, hide_index=True, width="stretch", disabled=["Jugador"],
                                column_config=cfg_cols, key=f"stats_{jid}_{st.session_state['ver']}")
            st.caption("PTS REB AST ROB TAP FR suman · T3F TLF T2F (tiros fallados) PER FC restan · "
                       "AIRBALLS resta 2 al mánager · GAME_WINNER duplica la valoración.")

            jugaron = ed[ed["Jugó"]]
            if not jugaron.empty:
                pos = ["PTS", "REB", "AST", "ROB", "TAP", "FR"]
                neg = ["T3F", "TLF", "T2F", "PER", "FC"]
                prev = pd.DataFrame({"Jugador": jugaron["Jugador"],
                                     "Valoración": (jugaron[pos].fillna(0).sum(axis=1)
                                                    - jugaron[neg].fillna(0).sum(axis=1)).astype(int)})
                st.dataframe(prev, hide_index=True, width="stretch")

            st.markdown("**Sanciones y bonus de mánager**")
            st.caption("Cambio tarde: −15 · Sin camiseta/pijama: −5. El Autotopillo (−3) se aplica solo.")
            pen_prev = query("""SELECT m.nombre AS Mánager, x.motivo AS Motivo, x.puntos AS Puntos
                                FROM puntos_extra x JOIN managers m ON m.id = x.manager_id
                                WHERE x.jornada_id = ? AND x.motivo NOT LIKE ?""",
                             (jid, MOTIVO_AUTOTOPILLO + "%"))
            nombres_m = query("SELECT nombre FROM managers ORDER BY nombre")["nombre"].tolist()
            pen = st.data_editor(
                pen_prev, num_rows="dynamic", hide_index=True, width="stretch",
                column_config={"Mánager": st.column_config.SelectboxColumn("Mánager", options=nombres_m, required=True),
                               "Motivo": st.column_config.TextColumn("Motivo", required=True),
                               "Puntos": st.column_config.NumberColumn("Puntos", step=1, required=True)},
                key=f"pen_{jid}_{st.session_state['ver']}")

            if st.button("✅ Procesar jornada", type="primary"):
                stats = {}
                for _, r in jugaron.iterrows():
                    d = {c: int(pd.to_numeric(r[c.upper()], errors="coerce") or 0) for c in CAMPOS}
                    d["game_winner"] = int(bool(r["GAME_WINNER"]))
                    stats[r["Jugador"]] = d
                sanciones = [{"manager": r["Mánager"], "motivo": r["Motivo"], "puntos": r["Puntos"]}
                             for _, r in pen.dropna(subset=["Mánager", "Motivo", "Puntos"]).iterrows()]
                if not stats:
                    st.error("Marca al menos un jugador como 'Jugó'.")
                else:
                    with st.spinner("Procesando jornada…"):
                        st.session_state["log"] = procesar_cierre_jornada(int(num), stats, sanciones, con=CON)
                    st.session_state["ver"] += 1
                    st.rerun()

            if "log" in st.session_state:
                st.success("Jornada procesada")
                st.code("\n".join(st.session_state.pop("log")))

    # --- C. Configuración ---
    with st.expander("3. Reglas del mercado (editable)"):
        cfg = leer_config(CON)
        etiquetas = {
            "precio_base": "Precio base (€)",
            "factor_precio": "€ por punto de valoración",
            "peso_precio_anterior": "Peso del precio anterior (0 a 1)",
            "suelo": "Precio mínimo (€)",
            "techo": "Precio máximo (€)",
            "pen_autotopillo": "Penalización autotopillo (pts)",
        }
        nuevos = {}
        for k in CONFIG_DEFECTO:
            paso = 0.05 if k == "peso_precio_anterior" else (1.0 if k == "pen_autotopillo" else 1000.0)
            nuevos[k] = st.number_input(etiquetas[k], value=float(cfg[k]), step=paso, key=f"cfg_{k}")
        if st.button("Guardar reglas"):
            with db.transaccion(CON):
                guardar_config(CON, nuevos)
            st.success("Reglas guardadas. Se aplican desde la próxima jornada que proceses.")

    # --- D. Copias de seguridad ---
    with st.expander("4. Copia de seguridad"):
        st.caption("Descarga todos los datos en un archivo .db, o sube uno para sustituir los actuales "
                   "(por ejemplo, el supermanager.db que tenías en tu PC).")
        if st.button("Preparar copia para descargar"):
            with st.spinner("Copiando datos…"):
                st.session_state["copia"] = copias.exportar(CON)
        if "copia" in st.session_state:
            st.download_button("⬇️ Descargar copia", st.session_state["copia"],
                               file_name=f"supermanager_{ahora().date().isoformat()}.db",
                               mime="application/octet-stream")

        st.divider()
        subida = st.file_uploader("Restaurar desde un archivo .db", type=["db", "sqlite", "sqlite3"])
        confirmar = st.checkbox("Entiendo que se borran TODOS los datos actuales y se sustituyen por los del archivo")
        if st.button("Restaurar", disabled=not (subida and confirmar)):
            try:
                with st.spinner("Restaurando…"):
                    resumen = copias.importar(CON, subida.getvalue())
            except Exception as e:
                st.error(f"No se pudo restaurar: {e}")
            else:
                st.session_state["ver"] += 1
                st.success("Datos restaurados: " + ", ".join(f"{t} {n}" for t, n in resumen.items()))
