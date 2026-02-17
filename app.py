import streamlit as st
import os
import io
import re
import base64
from typing import List, Dict, Any, Tuple, Optional
from PIL import Image

import ia_engine
import html_generator
import google_drive_manager
import location_manager
from streamlit_js_eval import get_geolocation

# ------------------------------------------------------------
# CONFIG PÁGINA
# ------------------------------------------------------------
st.set_page_config(
    page_title="Tasador Agrícola Noroeste",
    layout="centered",
    page_icon="🚜"
)

ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE") or os.environ.get("K_REVISION"))
ENV_KEY = "cloud" if ES_CLOUD_RUN else "local"


# ------------------------------------------------------------
# UI GLOBAL (OCULTAR CHROME + BRANDING)
# ------------------------------------------------------------
def ocultar_chrome_streamlit():
    st.markdown("""
<div class="hero">
  <h1>🌱 Tasación de maquinaria</h1>
  <p>Agrícola Noroeste · Valoración orientativa basada en estado, horas y mercado</p>
</div>

<style>
.block-container {
    max-width: 1100px;
    padding-top: 1.8rem;
    padding-bottom: 2.2rem;
}

/* Ocultar cromos Streamlit */
#MainMenu, footer, header {visibility: hidden;}

/* Hero */
.hero {
  background: linear-gradient(
    135deg,
    rgba(63,163,77,.18),
    rgba(125,186,58,.18)
  );
  border: 1px solid rgba(47,111,62,.25);
  border-radius: 22px;
  padding: 18px;
  margin-bottom: 18px;
}
.hero h1 {
  margin: 0;
  color: #1F3D2B;
}
.hero p {
  margin: 0;
  color: #4F6F5B;
}

/* Cards */
.card {
  background: #F3F8F3;
  border: 1px solid rgba(47,111,62,.18);
  border-radius: 18px;
  padding: 16px;
}

/* Inputs */
div[data-baseweb="input"] input,
div[data-baseweb="textarea"] textarea {
  border-radius: 14px !important;
  border: 1px solid rgba(47,111,62,.25) !important;
}

/* Botón principal */
.stButton > button {
  background: linear-gradient(135deg, #3FA34D, #7DBA3A) !important;
  color: #ffffff !important;
  border-radius: 14px !important;
  border: none !important;
  font-weight: 700 !important;
  padding: 0.7rem 1.1rem !important;
}
.stButton > button:hover {
  filter: brightness(1.05);
  transform: translateY(-1px);
}

/* Pills */
.pill {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(63,163,77,.15);
  border: 1px solid rgba(47,111,62,.25);
  font-size: .85rem;
  color: #1F3D2B;
}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------
# CREDS
# ------------------------------------------------------------
def get_creds():
    """
    Cloud Run: None (ADC)
    Local: st.secrets["google"]
    """
    if ES_CLOUD_RUN:
        return None
    try:
        return dict(st.secrets["google"])
    except Exception:
        st.error("Faltan secrets locales: st.secrets['google']")
        st.stop()


CREDS = get_creds()


# ------------------------------------------------------------
# LOGIN / ACCESO
# ------------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    if os.path.exists("agricolanoroestelogo.jpg"):
        st.image("agricolanoroestelogo.jpg", width=320)
    else:
        st.title("🚜 Agrícola Noroeste")

    st.subheader("Acceso de Tasadores")

    vendedores = google_drive_manager.leer_vendedores(None if ES_CLOUD_RUN else CREDS) or []

    with st.form("login"):
        v_sel = st.selectbox("Selecciona tu nombre:", [""] + vendedores)
        entrar = st.form_submit_button("Entrar", use_container_width=True)

    if entrar:
        if not v_sel:
            st.error("Selecciona un nombre.")
        else:
            st.session_state["logged_in"] = True
            st.session_state["vendedor"] = v_sel
            st.rerun()

    st.stop()


# ------------------------------------------------------------
# A PARTIR DE AQUÍ: APP REAL
# ------------------------------------------------------------
ocultar_chrome_streamlit()

col_logo, col_controls = st.columns([6, 2])
with col_logo:
    if os.path.exists("agricolanoroestelogo.jpg"):
        st.image("agricolanoroestelogo.jpg", width=220)
    else:
        st.markdown("### Agrícola Noroeste")
    st.markdown(f"### 🚜 {st.session_state.get('vendedor','')}")

with col_controls:
    if st.button("Salir", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.divider()

COEFS = get_coeficientes_cached(ENV_KEY)

# ------------------------------------------------------------
# CONEXIÓN IA
# ------------------------------------------------------------
if "vertex_client" not in st.session_state:
    try:
        creds_vertex = None if ES_CLOUD_RUN else CREDS
        st.session_state.vertex_client = ia_engine.conectar_vertex(creds_vertex)
    except Exception as e:
        st.error(f"Error inicializando Vertex AI: {e}")

# ------------------------------------------------------------
# GPS
# ------------------------------------------------------------
loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = (
    location_manager.codificar_coordenadas(loc["coords"]["latitude"], loc["coords"]["longitude"])
    if loc and "coords" in loc
    else "UBICACIÓN NO DETECTADA"
)

# ------------------------------------------------------------
# BORRADOR
# ------------------------------------------------------------
st.session_state.setdefault(
    "draft",
    {
        "marca": "Valtra",
        "modelo": "G125",
        "anio": "2025",
        "horas": "2500",
        "cv": "",
        "kg_contrapesos": "0",
        "vida_neum_grandes": "",
        "vida_neum_pequenos": "",
        "obs": "",
        "fotos_state": [],
        "extra_pala": False,
        "extra_anclajes_pala": False,
        "extra_tripuntal_del": False,
        "extra_tdf_del": False,
        "extra_compresor": False,
        "extra_autoguiado": False,
    },
)

OPC_VIDA = [""] + [str(x) for x in range(0, 101, 10)]

# ------------------------------------------------------------
# FORMULARIO / RESULTADOS
# ------------------------------------------------------------
if "result" not in st.session_state:
    st.subheader("Datos del Peritaje")

    fotos_up = st.file_uploader(
        "Subir fotos del tractor (mínimo 4)",
        accept_multiple_files=True,
        type=["jpg", "jpeg", "png"],
        key="uploader_fotos",
    )
    if fotos_up:
        st.session_state["draft"]["fotos_state"] = _fotos_to_state(fotos_up)

    fotos_guardadas = st.session_state["draft"]["fotos_state"] or []
    if fotos_guardadas:
        st.success(f"✅ Fotos guardadas en memoria: {len(fotos_guardadas)} (mínimo 4)")
        if st.button("🗑️ Vaciar fotos guardadas", use_container_width=True):
            st.session_state["draft"]["fotos_state"] = []
            st.session_state.pop("uploader_fotos", None)
            st.rerun()
    else:
        st.warning("⚠️ No hay fotos guardadas todavía. Súbelas para iniciar la tasación.")

    with st.form("form_peritaje", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            marca = st.text_input("Marca *", value=st.session_state["draft"]["marca"])
            modelo = st.text_input("Modelo *", value=st.session_state["draft"]["modelo"])
        with col2:
            anio = st.text_input("Año *", value=st.session_state["draft"]["anio"])
            horas = st.text_input("Horas *", value=st.session_state["draft"]["horas"])

        colp1, colp2 = st.columns(2)
        with colp1:
            cv = st.text_input("CV *", value=st.session_state["draft"]["cv"])
        with colp2:
            kg_contrapesos = st.text_input("Kg contrapesos", value=st.session_state["draft"]["kg_contrapesos"])

        obs = st.text_area("Observaciones adicionales del perito", value=st.session_state["draft"]["obs"])

        st.markdown("#### Extras del tractor")
        e1, e2, e3 = st.columns(3)
        with e1:
            extra_pala = st.checkbox("Pala", value=st.session_state["draft"]["extra_pala"])
            extra_anclajes_pala = st.checkbox("Anclajes de pala", value=st.session_state["draft"]["extra_anclajes_pala"])
        with e2:
            extra_tripuntal_del = st.checkbox("Tripuntal del.", value=st.session_state["draft"]["extra_tripuntal_del"])
            extra_tdf_del = st.checkbox("TDF del.", value=st.session_state["draft"]["extra_tdf_del"])
        with e3:
            extra_compresor = st.checkbox("Compresor", value=st.session_state["draft"]["extra_compresor"])
            extra_autoguiado = st.checkbox("Autoguiado", value=st.session_state["draft"]["extra_autoguiado"])

        st.markdown("#### Vida útil neumáticos")
        n1, n2 = st.columns(2)
        with n1:
            vida_neum_grandes = st.selectbox(
                "Vida útil neumáticos grandes (%) *",
                options=OPC_VIDA,
                index=OPC_VIDA.index(str(st.session_state["draft"]["vida_neum_grandes"]))
                if str(st.session_state["draft"]["vida_neum_grandes"]) in OPC_VIDA
                else 0,
            )
        with n2:
            vida_neum_pequenos = st.selectbox(
                "Vida útil neumáticos pequeños (%) *",
                options=OPC_VIDA,
                index=OPC_VIDA.index(str(st.session_state["draft"]["vida_neum_pequenos"]))
                if str(st.session_state["draft"]["vida_neum_pequenos"]) in OPC_VIDA
                else 0,
            )

        submit = st.form_submit_button("🚀 INICIAR TASACIÓN Y GUARDAR", use_container_width=True)

    if submit:
        d = st.session_state["draft"]
        d["marca"] = marca
        d["modelo"] = modelo
        d["anio"] = anio
        d["horas"] = horas
        d["cv"] = cv
        d["kg_contrapesos"] = kg_contrapesos
        d["obs"] = obs
        d["extra_pala"] = extra_pala
        d["extra_anclajes_pala"] = extra_anclajes_pala
        d["extra_tripuntal_del"] = extra_tripuntal_del
        d["extra_tdf_del"] = extra_tdf_del
        d["extra_compresor"] = extra_compresor
        d["extra_autoguiado"] = extra_autoguiado
        d["vida_neum_grandes"] = vida_neum_grandes
        d["vida_neum_pequenos"] = vida_neum_pequenos

        errores = validar_datos(d)
        if errores:
            st.error("No se puede iniciar la tasación. Revisa:")
            for e in errores:
                st.markdown(f"- {e}")
        elif "vertex_client" not in st.session_state:
            st.error("El cliente de IA no está conectado.")
        else:
            with st.spinner("Procesando tasación..."):
                try:
                    total_ajustes, desglose_items = calcular_ajustes_extras(d, COEFS)
                    bloque_extras = bloque_extras_texto(total_ajustes, desglose_items)

                    fotos_pil = _state_to_pil_images(d["fotos_state"])
                    fotos_for_ai = fotos_up if fotos_up else _state_to_uploadlike(d["fotos_state"])

                    # OJO: no metemos instrucción adicional en observaciones.
                    informe = ia_engine.realizar_peritaje(
                        st.session_state.vertex_client,
                        d["marca"],
                        d["modelo"],
                        d["anio"],
                        d["horas"],
                        (d["obs"] or "").strip(),
                        fotos_for_ai,
                    )

                    base_dict = parse_resultado_final(informe)

                    ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")
                    html = html_generator.generar_informe_html(
                        d["marca"],
                        d["modelo"],
                        informe,
                        fotos_pil,
                        ref_b64,
                    )

                    nombre_fichero = f"Tasacion_{d['marca']}_{d['modelo']}.html"
                    carpeta = st.session_state.get("vendedor", "General")
                    creds_drive = None if ES_CLOUD_RUN else CREDS

                    id_archivo = google_drive_manager.subir_informe(
                        creds_drive,
                        nombre_fichero,
                        html,
                        folder_name=carpeta,
                    )

                    st.session_state["result"] = {
                        "informe_final": informe,
                        "html": html,
                        "nombre_archivo": nombre_fichero,
                        "id_archivo_drive": id_archivo,
                        "base_dict": base_dict,
                        "extras_total": total_ajustes,
                        "extras_items": desglose_items,
                        "bloque_extras": bloque_extras,
                    }
                    st.rerun()

                except Exception as e:
                    st.error(f"Error en el proceso: {e}")

# ---------------- RESULTADOS ----------------
if "result" in st.session_state:
    res = st.session_state["result"]
    base = res.get("base_dict", {}) or {}
    extras_total = float(res.get("extras_total", 0.0))
    bloque_extras = res.get("bloque_extras", "")

    if res.get("id_archivo_drive"):
        st.success("✅ Peritaje finalizado y archivado en Drive.")
    else:
        st.success("✅ Peritaje finalizado.")
        st.warning("⚠️ No se recibió ID de Drive (permisos/archivo).")

    st.markdown("### Resultado del Análisis (IA)")
    st.markdown(res["informe_final"])

    st.markdown("### Precios base del tasador (RESULTADO_FINAL)")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("VALOR_MERCADO", fmt_eur(base.get("VALOR_MERCADO")))
    with c2:
        st.metric("PRECIO_VENTA", fmt_eur(base.get("PRECIO_VENTA")))
    with c3:
        st.metric("PRECIO_COMPRA", fmt_eur(base.get("PRECIO_COMPRA")))

    st.markdown("### Extras / Ajustes (APARTE)")
    st.code(bloque_extras)

    if base.get("VALOR_MERCADO") is not None:
        st.markdown("### Referencia (base + extras) — solo orientativo")
        r1, r2, r3 = st.columns(3)
        with r1:
            st.metric("Mercado + Extras", fmt_eur(float(base["VALOR_MERCADO"]) + extras_total))
        with r2:
            st.metric("Venta + Extras", fmt_eur(float(base["PRECIO_VENTA"]) + extras_total) if base.get("PRECIO_VENTA") is not None else "—")
        with r3:
            st.metric("Compra + Extras", fmt_eur(float(base["PRECIO_COMPRA"]) + extras_total) if base.get("PRECIO_COMPRA") is not None else "—")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        st.download_button(
            label="📄 DESCARGAR HTML",
            data=res["html"],
            file_name=res["nombre_archivo"],
            mime="text/html",
            use_container_width=True,
        )
    with col_btn2:
        if st.button("↩️ VOLVER A TASAR (mantener datos y fotos)", use_container_width=True):
            st.session_state.pop("result", None)
            st.rerun()
