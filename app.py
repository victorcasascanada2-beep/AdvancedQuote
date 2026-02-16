import streamlit as st
import os
import base64
from PIL import Image
import ia_engine
import html_generator
import google_drive_manager
import location_manager
from streamlit_js_eval import get_geolocation

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Tasador Agrícola Noroeste", layout="centered", page_icon="🚜")

# --- MANEJO DE SECRETOS HÍBRIDO (El parche para Cloud Run) ---
creds_drive = None
try:
    # Si estamos en Streamlit Cloud o local con secrets.toml
    if "google" in st.secrets:
        creds_drive = dict(st.secrets["google"])
except Exception:
    # En Cloud Run (Docker) esto fallará silenciosamente y creds_drive será None
    pass

# --- UI STYLE ---
def ocultar_chrome():
    st.markdown("<style>header {visibility: hidden;} footer {visibility: hidden;}</style>", unsafe_allow_html=True)

# --- VISTA DE ACCESO ---
def vista_acceso():
    if os.path.exists("agricolanoroestelogo.jpg"):
        st.image("agricolanoroestelogo.jpg", width=300)
    else:
        st.title("🚜 Agrícola Noroeste")
    
    st.subheader("Acceso de Tasadores")

    if "vendedores_lista" not in st.session_state:
        with st.spinner("Conectando con Drive..."):
            res = google_drive_manager.leer_vendedores(creds_drive)
            st.session_state["vendedores_lista"] = [str(v) for v in res] if res else []

    vendedores = st.session_state["vendedores_lista"]
    t1, t2 = st.tabs(["Seleccionar", "Nuevo Registro"])

    with t1:
        with st.form("f_login"):
            v_sel = st.selectbox("Nombre:", [""] + vendedores)
            if st.form_submit_button("Entrar", use_container_width=True) and v_sel:
                st.session_state.logged_in = True
                st.session_state.vendedor = v_sel
                st.rerun()

    with t2:
        with st.form("f_reg"):
            n_nom = st.text_input("Nuevo Tasador:")
            if st.form_submit_button("Registrar", use_container_width=True) and n_nom.strip():
                nombre = n_nom.strip()
                if nombre not in vendedores:
                    vendedores.append(nombre)
                    if google_drive_manager.actualizar_vendedores(creds_drive, vendedores):
                        st.session_state.vendedores_lista = vendedores
                        st.session_state.logged_in = True
                        st.session_state.vendedor = nombre
                        st.rerun()

# --- LÓGICA SESIÓN ---
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if not st.session_state.logged_in:
    vista_acceso()
    st.stop()

ocultar_chrome()

# --- APP PRINCIPAL ---
col_logo, col_logout = st.columns([6, 1])
with col_logo:
    st.markdown(f"### 🚜 Hola, {st.session_state.vendedor}")
with col_logout:
    if st.button("Salir"):
        st.session_state.clear()
        st.rerun()

st.divider()

# Carga de IA
if "vertex_client" not in st.session_state:
    st.session_state.vertex_client = ia_engine.conectar_vertex(creds_drive)

# Ubicación
loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = location_manager.codificar_coordenadas(loc["coords"]["latitude"], loc["coords"]["longitude"]) if loc else "N/D"

# Formulario
if "informe_final" not in st.session_state:
    with st.form("tasa"):
        fotos = st.file_uploader("Fotos", accept_multiple_files=True, type=["jpg","png","jpeg"])
        marca = st.text_input("Marca", value="Valtra")
        modelo = st.text_input("Modelo", value="G125")
        if st.form_submit_button("🚀 INICIAR TASACIÓN") and fotos:
            with st.spinner("Procesando..."):
                inf = ia_engine.realizar_peritaje(st.session_state.vertex_client, marca, modelo, "2025", "2500", "", fotos)
                html = html_generator.generar_informe_html(marca, modelo, inf, [Image.open(f) for f in fotos], "REF")
                google_drive_manager.subir_informe(creds_drive, f"T_{marca}.html", html, st.session_state.vendedor)
                st.session_state.informe_final = inf
                st.session_state.html = html
                st.rerun()

if "informe_final" in st.session_state:
    st.markdown(st.session_state.informe_final)
    if st.button("🔄 NUEVA"):
        del st.session_state.informe_final
        st.rerun()
