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

# --- MANEJO DE SECRETOS SIN ERRORES (EL PARCHE DEFINITIVO) ---
def cargar_credenciales_seguras():
    """
    Intenta cargar secretos de Streamlit. 
    Si falla (como en Cloud Run), devuelve None silenciosamente 
    para evitar el FileNotFoundError en los logs.
    """
    try:
        # Usamos getattr para evitar que Streamlit dispare la validación del archivo toml
        # si solo llamamos a .secrets directamente.
        if hasattr(st, "secrets") and "google" in st.secrets:
            return dict(st.secrets["google"])
    except Exception:
        # Silenciamos cualquier error de archivo no encontrado
        pass
    return None

creds_drive = cargar_credenciales_seguras()

# -------------------------------------------------------------------
# ESTILO Y UI
# -------------------------------------------------------------------
def ocultar_chrome_streamlit():
    st.markdown(
        """
        <style>
          header {visibility: hidden;}
          footer {visibility: hidden;}
          #MainMenu {visibility: hidden;}
          [data-testid="stToolbar"] {visibility: hidden;}
          [data-testid="stHeader"] {visibility: hidden;}
          .block-container {padding-top: 1.2rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )

# -------------------------------------------------------------------
# VISTA DE ACCESO (DINÁMICA DESDE DRIVE)
# -------------------------------------------------------------------
def vista_acceso():
    if os.path.exists("agricolanoroestelogo.jpg"):
        st.image("agricolanoroestelogo.jpg", width=320)
    else:
        st.title("🚜 Agrícola Noroeste")
    
    st.subheader("Acceso de Tasadores")

    if "vendedores_lista" not in st.session_state:
        with st.spinner("Conectando con la base de datos de tasadores..."):
            # Si creds_drive es None, google_drive_manager usará ADC (Cloud Run)
            res = google_drive_manager.leer_vendedores(creds_drive)
            st.session_state["vendedores_lista"] = [str(v) for v in res] if res else []

    vendedores = st.session_state["vendedores_lista"]
    t1, t2 = st.tabs(["Seleccionar mi nombre", "Registrar nuevo"])

    with t1:
        with st.form("form_login"):
            v_sel = st.selectbox("Selecciona tu nombre:", [""] + vendedores)
            if st.form_submit_button("Entrar", use_container_width=True) and v_sel:
                st.session_state["logged_in"] = True
                st.session_state["vendedor"] = v_sel
                st.rerun()

    with t2:
        with st.form("form_registro"):
            nuevo_nombre = st.text_input("Nombre y Apellido del nuevo tasador:")
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

# --- HEADER APP ---
col_logo, col_logout = st.columns([6, 1])
with col_logo:
    st.markdown(f"### 🚜 Hola, {st.session_state['vendedor']}")
with col_logout:
    if st.button("Salir", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.divider()

# --- SERVICIOS (IA Y GPS) ---
if "vertex_client" not in st.session_state:
    st.session_state.vertex_client = ia_engine.conectar_vertex(creds_drive)

loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = (
    location_manager.codificar_coordenadas(loc["coords"]["latitude"], loc["coords"]["longitude"]) 
    if loc and "coords" in loc else "UBICACIÓN NO DETECTADA"
)

# --- FORMULARIO COMPLETO ---
if "informe_final" not in st.session_state:
    with st.form("form_peritaje"):
        st.subheader("Datos del Peritaje")
        
        fotos = st.file_uploader("Subir fotos del tractor", accept_multiple_files=True, type=["jpg","png","jpeg"])
        
        col1, col2 = st.columns(2)
        with col1:
            marca = st.text_input("Marca", value="Valtra")
            modelo = st.text_input("Modelo", value="G125")
        with col2:
            anio = st.text_input("Año", value="2025")
            horas = st.text_input("Horas", value="2500")
            
        obs = st.text_area("Observaciones adicionales del perito (daños, extras, estado)")
        
        submit = st.form_submit_button("🚀 INICIAR TASACIÓN Y GUARDAR", use_container_width=True)

    if submit and fotos:
        status = st.empty()
        with st.spinner("Procesando tasación..."):
            try:
                # 1. IA
                status.info("📡 Analizando con Gemini 2.0...")
                inf = ia_engine.realizar_peritaje(st.session_state.vertex_client, marca, modelo, anio, horas, obs, fotos)
                
                # 2. HTML
                status.info("📑 Generando documento técnico...")
                ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")
                fotos_pil = [Image.open(f) for f in fotos]
                html = html_generator.generar_informe_html(marca, modelo, inf, fotos_pil, ref_b64)
                
                # 3. GUARDAR EN DRIVE
                status.warning(f"📤 Archivando en carpeta de {st.session_state.vendedor}...")
                nombre_fichero = f"Tasacion_{marca}_{modelo}.html"
                id_archivo = google_drive_manager.subir_informe(creds_drive, nombre_fichero, html, st.session_state.vendedor)
                
                if id_archivo:
                    st.session_state.informe_final = inf
                    st.session_state.html = html
                    st.session_state.nombre_archivo = nombre_fichero
                    st.rerun()
            except Exception as e:
                st.error(f"Error en el proceso: {e}")

# --- VISTA DE RESULTADOS ---
if "informe_final" in st.session_state:
    st.success(f"✅ Peritaje finalizado.")
    st.markdown("### Resultado del Análisis")
    st.markdown(st.session_state.informe_final)
    
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            label="📄 DESCARGAR HTML",
            data=st.session_state.html,
            file_name=st.session_state.nombre_archivo,
            mime="text/html",
            use_container_width=True
        )
    with c2:
        if st.button("🔄 NUEVA TASACIÓN", use_container_width=True):
            for k in ["informe_final", "html", "nombre_archivo"]:
                if k in st.session_state: del st.session_state[k]
            st.rerun()
