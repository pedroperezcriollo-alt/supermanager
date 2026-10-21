"""Pestañas visuales: pista de baloncesto, estadísticas de jugadores y comparador.

Fotos: pon en la carpeta `fotos/` del repositorio un archivo por jugador con su
nombre exacto (Pedro.jpg, Koke.png...). Se recortan solas a cuadrado y se
reducen; si falta la foto, sale un circulo de color con las iniciales.
"""
import base64
import hashlib
import html
import io
from pathlib import Path

import pandas as pd
import streamlit as st

FOTOS = Path(__file__).resolve().parent / "fotos"
EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp"}

# Posiciones en la pista (% izquierda, % arriba). La canasta esta arriba.
POSICIONES = [(50, 22), (24, 45), (76, 45), (28, 74), (72, 74)]

CSS = """<style>
.pista{position:relative;width:100%;max-width:440px;aspect-ratio:5/6;margin:0 auto;border-radius:14px;overflow:hidden;
background:repeating-linear-gradient(90deg,#c98d4e 0,#c98d4e 9%,#bf8244 9%,#bf8244 18%);border:3px solid rgba(255,255,255,.55);}
.pista .ln{position:absolute;border:2px solid rgba(255,255,255,.8);box-sizing:border-box;}
.sp{position:absolute;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;}
.av{width:min(15vw,76px);aspect-ratio:1;border-radius:50%;overflow:hidden;display:flex;flex-shrink:0;}
.av img{width:100%;height:100%;object-fit:cover;}
.av-ini{width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:clamp(14px,4vw,22px);}
.sp .av{border:3px solid #fff;box-shadow:0 3px 8px rgba(0,0,0,.45);}
.sp .nm{margin-top:4px;background:rgba(15,18,30,.88);color:#fff;border-radius:8px;padding:1px 7px;font-size:clamp(10px,2.8vw,13px);font-weight:700;white-space:nowrap;}
.sp .sb{color:#fff;font-size:clamp(9px,2.4vw,11px);font-weight:600;text-shadow:0 1px 3px #000;white-space:nowrap;}
.sp.vacio .av{border-style:dashed;background:rgba(255,255,255,.2);}
.lid-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.lid{display:flex;align-items:center;gap:10px;padding:10px;border-radius:12px;background:rgba(128,128,128,.15);}
.lid .av{width:46px;}
.lid small{display:block;opacity:.7;font-size:12px;}
.lid b{display:block;font-size:15px;}
.lid span{font-size:13px;opacity:.85;}
.vs{display:flex;justify-content:space-around;align-items:center;text-align:center;gap:8px;margin:6px 0 10px;}
.vs .av{width:72px;margin:0 auto 4px;}
</style>"""


def mostrar(contenido):
    """Pinta HTML (sin saltos de linea para que Markdown no lo trocee)."""
    contenido = "".join(linea.strip() for linea in contenido.splitlines())
    if hasattr(st, "html"):
        st.html(contenido)
    else:
        st.markdown(contenido, unsafe_allow_html=True)


# ---------- fotos y avatares ----------
@st.cache_data(show_spinner=False)
def foto_uri(nombre):
    if not FOTOS.is_dir():
        return None
    for f in FOTOS.iterdir():
        if f.suffix.lower() in EXTENSIONES and f.stem.lower() == nombre.lower():
            try:
                from PIL import Image, ImageOps
                img = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
                img = ImageOps.fit(img, (160, 160))
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=82)
                return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            except Exception:
                return None
    return None


def avatar(nombre):
    """Contenido de un circulo: la foto o las iniciales sobre un color propio."""
    uri = foto_uri(nombre)
    if uri:
        return f'<img src="{uri}" alt="{html.escape(nombre)}">'
    tono = int(hashlib.md5(nombre.encode()).hexdigest(), 16) % 360
    return f'<span class="av-ini" style="background:hsl({tono},55%,42%)">{html.escape(nombre[:2].upper())}</span>'


# ---------- pista ----------
def pista_html(jugadores):
    """jugadores: lista de {"nombre": ..., "sub": ...} (hasta 5)."""
    lineas = (
        '<div class="ln" style="left:34%;width:32%;top:0;height:36%"></div>'
        '<div class="ln" style="left:34%;width:32%;aspect-ratio:1;top:22.7%;border-radius:50%"></div>'
        '<div class="ln" style="left:7%;width:86%;aspect-ratio:1;top:-29.8%;border-radius:50%"></div>'
        '<div class="ln" style="left:42%;width:16%;top:2%;height:0;border-width:3px 0 0 0"></div>'
        '<div class="ln" style="left:47.8%;width:4.4%;aspect-ratio:1;top:3.5%;border-radius:50%;border-color:#ff7a1a"></div>'
    )
    puestos = ""
    for i, (x, y) in enumerate(POSICIONES):
        if i < len(jugadores):
            j = jugadores[i]
            puestos += (f'<div class="sp" style="left:{x}%;top:{y}%"><div class="av">{avatar(j["nombre"])}</div>'
                        f'<div class="nm">{html.escape(j["nombre"])}</div><div class="sb">{html.escape(j["sub"])}</div></div>')
        else:
            puestos += (f'<div class="sp vacio" style="left:{x}%;top:{y}%"><div class="av">'
                        '<span class="av-ini">+</span></div></div>')
    return CSS + f'<div class="pista">{lineas}{puestos}</div>'


def pista_en_vivo(query, ids):
    """Pista con la seleccion actual de 'Mi quinteto' (aun sin guardar)."""
    df = query("""SELECT j.id, j.nombre, j.precio_actual AS precio,
                         (SELECT AVG(valoracion) FROM estadisticas WHERE jugador_id = j.id) AS vm
                  FROM jugadores j""")
    sel = df[df["id"].isin([int(i) for i in ids])].sort_values("precio", ascending=False)
    jugadores = []
    for _, r in sel.iterrows():
        sub = f"{r['precio'] / 1000:.0f}k €" + ("" if pd.isna(r["vm"]) else f" · Val {r['vm']:.0f}")
        jugadores.append({"nombre": r["nombre"], "sub": sub})
    mostrar(pista_html(jugadores))


def render_pista(query, eur, cerrado):
    st.subheader("Pista")
    jornadas = query("SELECT id, numero, estado, cierre_mercado FROM jornadas ORDER BY numero DESC")
    visibles = [r for _, r in jornadas.iterrows() if cerrado(r)]
    if not visibles:
        st.info("Los quintetos se ven aquí cuando se cierra el mercado de cada jornada.")
        return
    c1, c2 = st.columns(2)
    numero = c1.selectbox("Jornada", [int(r["numero"]) for r in visibles], key="pista_jornada")
    jid = int(jornadas[jornadas["numero"] == numero].iloc[0]["id"])
    managers = query("SELECT id, nombre FROM managers ORDER BY nombre")
    nombre = c2.selectbox("Mánager", managers["nombre"].tolist(), key="pista_manager")
    mid = int(managers[managers["nombre"] == nombre].iloc[0]["id"])

    q = query("""SELECT j.nombre, p.precio_pagado AS precio, e.valoracion AS val,
                        e.game_winner AS gw, e.airballs AS air
                 FROM plantillas p JOIN jugadores j ON j.id = p.jugador_id
                 LEFT JOIN estadisticas e ON e.jornada_id = p.jornada_id AND e.jugador_id = p.jugador_id
                 WHERE p.jornada_id = ? AND p.manager_id = ?
                 ORDER BY p.precio_pagado DESC, j.nombre""", (jid, mid))
    if q.empty:
        st.info(f"{nombre} no guardó quinteto en la jornada {numero}.")
        return
    extra = query("SELECT COALESCE(SUM(puntos), 0) AS t FROM puntos_extra WHERE jornada_id = ? AND manager_id = ?",
                  (jid, mid)).iloc[0]["t"]
    jugo = q["val"].notna()
    puntos = int((q.loc[jugo, "val"] * q.loc[jugo, "gw"].map(lambda g: 2 if g == 1 else 1)
                  - q.loc[jugo, "air"] * 2).sum() + extra)

    a, b = st.columns(2)
    a.metric("Puntos de la jornada", puntos if jugo.any() else "—")
    b.metric("Coste del quinteto", eur(q["precio"].sum()))
    mostrar(pista_html([
        {"nombre": r["nombre"],
         "sub": "No jugó" if pd.isna(r["val"]) else f"Val {int(r['val'])}" + (" ×2" if r["gw"] == 1 else "")}
        for _, r in q.iterrows()]))
    st.caption("Los jugadores se colocan por precio (el más caro, bajo canasta). Sin posiciones reales por ahora.")


# ---------- estadisticas, líderes y comparador ----------
STATS = ["PTS", "REB", "AST", "ROB", "TAP", "FR", "FALLOS", "PER", "FC", "VAL"]


def _totales(query):
    return query("""SELECT j.nombre AS Jugador, j.precio_actual AS Precio, COUNT(e.id) AS PJ,
        COALESCE(SUM(e.pts), 0) AS PTS, COALESCE(SUM(e.reb), 0) AS REB, COALESCE(SUM(e.ast), 0) AS AST,
        COALESCE(SUM(e.rob), 0) AS ROB, COALESCE(SUM(e.tap), 0) AS TAP, COALESCE(SUM(e.fr), 0) AS FR,
        COALESCE(SUM(e.t3f + e.tlf + e.t2f), 0) AS FALLOS, COALESCE(SUM(e.per), 0) AS PER,
        COALESCE(SUM(e.fc), 0) AS FC, COALESCE(SUM(e.valoracion), 0) AS VAL
        FROM jugadores j LEFT JOIN estadisticas e ON e.jugador_id = j.id
        GROUP BY j.id ORDER BY j.nombre""")


def _por_partido(df):
    pj = df["PJ"].where(df["PJ"] > 0)
    out = df.copy()
    for c in STATS:
        out[c] = (df[c] / pj).round(1)
    return out


def render_jugadores(query, eur):
    st.subheader("Estadísticas de los jugadores")
    tot = _totales(query)
    if tot["PJ"].sum() == 0:
        st.info("Todavía no hay jornadas puntuadas. Aquí saldrán las estadísticas cuando las haya.")
        return
    pp = _por_partido(tot)
    jugaron = pp[pp["PJ"] > 0]

    tarjetas = ""
    for col, titulo in [("PTS", "Máximo anotador"), ("REB", "Rey del rebote"),
                        ("AST", "Mejor pasador"), ("VAL", "MVP (valoración)")]:
        r = jugaron.sort_values(col, ascending=False).iloc[0]
        tarjetas += (f'<div class="lid"><div class="av">{avatar(r["Jugador"])}</div><div><small>{titulo}</small>'
                     f'<b>{html.escape(r["Jugador"])}</b><span>{r[col]:.1f} por partido</span></div></div>')
    mostrar(CSS + f'<div class="lid-grid">{tarjetas}</div>')

    st.markdown("#### Tabla completa")
    modo = st.radio("Ver", ["Por partido", "Totales"], horizontal=True, label_visibility="collapsed")
    tabla = (pp if modo == "Por partido" else tot).sort_values("VAL", ascending=False).copy()
    tabla["Precio"] = tabla["Precio"].map(eur)
    st.dataframe(tabla, hide_index=True, width="stretch")
    st.caption("FALLOS = triples + libres + tiros de 2 fallados · VAL = valoración.")

    st.markdown("#### Comparar jugadores")
    nombres = tot["Jugador"].tolist()
    c1, c2 = st.columns(2)
    ja = c1.selectbox("Jugador A", nombres, index=0, key="cmp_a")
    jb = c2.selectbox("Jugador B", nombres, index=min(1, len(nombres) - 1), key="cmp_b")
    if ja == jb:
        st.warning("Elige dos jugadores distintos para compararlos.")
        return
    fa, fb = pp[pp["Jugador"] == ja].iloc[0], pp[pp["Jugador"] == jb].iloc[0]
    mostrar(CSS + f'''<div class="vs"><div><div class="av">{avatar(ja)}</div><b>{html.escape(ja)}</b><br>
        <small>{eur(fa["Precio"])}</small></div><b>VS</b><div><div class="av">{avatar(jb)}</div>
        <b>{html.escape(jb)}</b><br><small>{eur(fb["Precio"])}</small></div></div>''')
    comp = pd.DataFrame({ja: [fa[c] for c in STATS], jb: [fb[c] for c in STATS]}, index=STATS)
    st.dataframe(comp, width="stretch")
    st.bar_chart(comp.drop(index=["VAL"]))

    hist = query("""SELECT jo.numero AS Jornada, ju.nombre AS nombre, h.precio AS precio
                    FROM historial_precios h JOIN jornadas jo ON jo.id = h.jornada_id
                    JOIN jugadores ju ON ju.id = h.jugador_id WHERE ju.nombre IN (?, ?)""", (ja, jb))
    if not hist.empty:
        st.markdown("#### Evolución del precio")
        st.line_chart(hist.pivot(index="Jornada", columns="nombre", values="precio"))
