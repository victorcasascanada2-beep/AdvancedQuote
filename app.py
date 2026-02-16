import streamlit as st
import os
import base64
from PIL import Image
import ia_engine
import html_generator
import google_drive_manager
import location_manager
from streamlit_js_eval import get_geolocation

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Tasador Agrícola Noroeste", layout="centered", page_icon="🚜")

# Detector de entorno Cloud Run / Local
ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE") or os.environ.get("K_REVISION"))

# --- MANEJO DE SECRETOS INTELIGENTE ---
# Solo intentamos cargar el dict de secretos si NO estamos en Cloud Run
# O si estamos en Cloud Run pero hemos decidido proveer secretos manualmente
creds_drive = None
if "google" in st.secrets:
    creds_drive = dict(st.secrets["google"])
elif not ES_CLOUD_RUN:
    # Si estamos en local y no hay secretos, esto sí es un problema
    st.error("❌ No se encontró el arreglo [google] en Secrets y no estás en Cloud Run.")
    st.stop()
# Si ES_CLOUD_RUN es True y no hay secretos, creds_drive se queda como None
# y los managers usarán las credenciales por defecto del sistema (ADC).

# -------------------------------------------------------------------
# ESTILO Y VISTA DE ACCESO
# -------------------------------------------------------------------
def ocultar_chrome_streamlit():
    st.markdown("<style>header {visibility: hidden;} footer {visibility: hidden;}</style>", unsafe_allow_html=True)

def vista_acceso():
    # Evitamos el error _repr_html_ con un bloque sólido
    if os.path.exists("agricolanoroestelogo.jpg"):
        st.image("agricolanoroestelogo.jpg", width=300)
    else:
        st.title("🚜 Agrícola Noroeste")
        
    st.subheader("Acceso de Tasadores")

    if "vendedores_lista" not in st.session_state:
        with st.spinner("Cargando tasadores..."):
            # Pasamos creds_drive (que puede ser None en Cloud Run)
            res = google_drive_manager.leer_vendedores(creds_drive)
            st.session_state["vendedores_lista"] = [str(v) for v in res] if res else []

    vendedores = st.session_state["vendedores_lista"]
    tab1, tab2 = st.tabs(["Seleccionar mi nombre", "Registrar nuevo"])

    with tab1:
        with st.form("form_login"):
            vendedor_sel = st.selectbox("Selecciona tu nombre:", [""] + vendedores)
            if st.form_submit_button("Entrar", use_container_width=True) and vendedor_sel:
                st.session_state["logged_in"] = True
                st.session_state["vendedor"] = vendedor_sel
                st.rerun()

    with tab2:
        with st.form("form_registro"):
            nuevo_nombre = st.text_input("Nombre y Apellido:")
            if st.form_submit_button("Registrar y Entrar", use_container_width=True) and nuevo_nombre.strip():
                nombre = nuevo_nombre.strip()
                if nombre not in vendedores:
                    vendedores.append(nombre)
                    if google_drive_manager.actualizar_vendedores(creds_drive, vendedores):
                        st.session_state["vendedores_lista"] = vendedores
                        st.session_state["logged_in"] = True
                        st.session_state["vendedor"] = nombre
                        st.rerun()

# --- LÓGICA DE SESIÓN ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    vista_acceso()
    st.stop()

ocultar_chrome_streamlit()

# --- HEADER Y RESTO DE LA APP ---
col_logo, col_logout = st.columns([6, 1])
with col_logo:
    st.markdown(f"### Hola, {st.session_state['vendedor']}")

with col_logout:
    if st.button("Salir"):
        st.session_state.clear()
        st.rerun()

st.divider()

# --- CONEXIÓN IA ---
if "vertex_client" not in st.session_state:
    # ia_engine ya sabe manejar creds_dict=None para usar ADC en Cloud Run
    st.session_state.vertex_client = ia_engine.conectar_vertex(creds_drive)

# --- UBICACIÓN ---
loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = location_manager.codificar_coordenadas(loc["coords"]["latitude"], loc["coords"]["longitude"]) if loc else "UBICACIÓN NO DETECTADA"

# --- FORMULARIO DE TASACIÓN ---
with st.form("form_tasacion"):
    fotos = st.file_uploader("Fotos del tractor", accept_multiple_files=True, type=["jpg", "jpeg", "png"])
    marca = st.text_input("Marca", value="Valtra")
    modelo = st.text_input("Modelo", value="G125")
    submit = st.form_submit_button("🚀 INICIAR TASACIÓN")

if submit and fotos:
    with st.spinner("Procesando..."):
        try:
            informe = ia_engine.realizar_peritaje(st.session_state.vertex_client, marca, modelo, "2025", "2500", "", fotos)
            html = html_generator.generar_informe_html(marca, modelo, informe, [Image.open(f) for f in fotos], "REF123")
            
            # Guardar en Drive
            google_drive_manager.subir_informe(creds_drive, f"Tasacion_{marca}.html", html, st.session_state["vendedor"])
            
            st.session_state.informe_final = informe
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")

if "informe_final" in st.session_state:
    st.markdown(st.session_state.informe_final)
