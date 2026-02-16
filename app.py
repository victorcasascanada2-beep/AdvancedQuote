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

# --- MANEJO DE SECRETOS (Arreglo 'google') ---
try:
    # Convertimos st.secrets["google"] en un dict puro para evitar errores de tipos con las APIs de Google
    creds_drive = dict(st.secrets["google"])
except Exception:
    st.error("❌ No se encontraron las credenciales en 'Secrets'. Asegúrate de tener la sección [google] configurada en el panel de Streamlit.")
    st.stop()

# -------------------------------------------------------------------
# ESTILO: Ocultar interfaz de Streamlit
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
# VISTA DE ACCESO (VENDEDORES DINÁMICOS)
# -------------------------------------------------------------------
def vista_acceso():
    if os.path.exists("agricolanoroestelogo.jpg"):
        st.image("agricolanoroestelogo.jpg", width=300)
    else:
        st.title("🚜 Agrícola Noroeste")
        
    st.subheader("Acceso de Tasadores")

    # Leer lista de Drive (Caché de sesión para no saturar la API)
    if "vendedores_lista" not in st.session_state:
        with st.spinner("Cargando lista de tasadores desde Drive..."):
            res = google_drive_manager.leer_vendedores(creds_drive)
            # Aseguramos que solo guardamos strings simples
            st.session_state["vendedores_lista"] = [str(v) for v in res] if res else []

    vendedores = st.session_state["vendedores_lista"]

    tab1, tab2 = st.tabs(["Seleccionar mi nombre", "Registrar nuevo"])

    with tab1:
        with st.form("form_login"):
            vendedor_sel = st.selectbox("Selecciona tu nombre:", [""] + vendedores)
            entrar = st.form_submit_button("Entrar", use_container_width=True)
            if entrar:
                if vendedor_sel and vendedor_sel != "":
                    st.session_state["logged_in"] = True
                    st.session_state["vendedor"] = vendedor_sel
                    st.rerun()
                else:
                    st.warning("Por favor, selecciona un nombre de la lista.")

    with tab2:
        with st.form("form_registro"):
            nuevo_nombre = st.text_input("Nombre y Apellido del nuevo tasador:")
            registrar = st.form_submit_button("Registrar y Entrar", use_container_width=True)
            if registrar:
                nombre_limpio = nuevo_nombre.strip()
                if not nombre_limpio:
                    st.error("El nombre no puede estar vacío.")
                elif nombre_limpio in vendedores:
                    st.warning("Este nombre ya existe en la lista.")
                else:
                    # Actualizar lista local y en Drive
                    vendedores.append(nombre_limpio)
                    if google_drive_manager.actualizar_vendedores(creds_drive, vendedores):
                        st.session_state["vendedores_lista"] = vendedores
                        st.session_state["logged_in"] = True
                        st.session_state["vendedor"] = nombre_limpio
                        st.rerun()
                    else:
                        st.error("Error al guardar el nuevo vendedor en Drive.")

# --- CONTROL DE SESIÓN ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    vista_acceso()
    st.stop()

# --- A PARTIR DE AQUÍ: APP PRINCIPAL (Logueado) ---
ocultar_chrome_streamlit()

# Header App
col_logo, col_logout = st.columns([6, 1])
with col_logo:
    if os.path.exists("agricolanoroestelogo.jpg"):
        st.image("agricolanoroestelogo.jpg", width=280)
    else:
        st.markdown(f"### Hola, {st.session_state['vendedor']}")

with col_logout:
    if st.button("Salir", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.divider()

# --- 2. CONEXIÓN AL MOTOR DE IA ---
if "vertex_client" not in st.session_state:
    try:
        # Usamos el mismo arreglo de secretos para Vertex
        st.session_state.vertex_client = ia_engine.conectar_vertex(creds_drive)
    except Exception as e:
        st.error(f"Error inicializando Vertex AI: {e}")

# --- 3. GESTIÓN DE UBICACIÓN ---
loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = (
    location_manager.codificar_coordenadas(
        loc["coords"]["latitude"],
        loc["coords"]["longitude"],
    )
    if loc and "coords" in loc
    else "UBICACIÓN NO DETECTADA"
)

# --- 4. FORMULARIO DE PERITAJE ---
if "informe_final" not in st.session_state:
    with st.form("form_tasacion"):
        st.subheader(f"Nuevo Peritaje: {st.session_state['vendedor']}")

        fotos = st.file_uploader(
            "Subir fotos del tractor",
            accept_multiple_files=True,
            type=["jpg", "jpeg", "png"],
        )

        col_m1, col_m2 = st.columns(2)
        with col_m1:
            marca = st.text_input("Marca", value="Valtra")
            modelo = st.text_input("Modelo", value="G125")
        with col_m2:
            anio = st.text_input("Año", value="2025")
            horas = st.text_input("Horas", value="2500")

        obs = st.text_area("Observaciones adicionales del perito")
        submit = st.form_submit_button("🚀 INICIAR TASACIÓN Y GUARDAR", use_container_width=True)

    if submit and fotos:
        if "vertex_client" not in st.session_state:
            st.error("IA no conectada. Revisa las credenciales.")
        else:
            status_placeholder = st.empty()
            with st.spinner("Procesando tasación..."):
                try:
                    # A. Inteligencia Artificial
                    status_placeholder.info("📡 Analizando fotos con Gemini 2.0...")
                    informe_texto = ia_engine.realizar_peritaje(
                        st.session_state.vertex_client, marca, modelo, anio, horas, obs, fotos
                    )

                    # B. Generación de HTML
                    status_placeholder.info("📑 Generando informe técnico...")
                    ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")
                    fotos_pil = [Image.open(f) for f in fotos]
                    html_res = html_generator.generar_informe_html(
                        marca, modelo, informe_texto, fotos_pil, ref_b64
                    )

                    # C. Guardado en Drive
                    status_placeholder.warning(f"📤 Guardando en carpeta de {st.session_state['vendedor']}...")
                    id_archivo = google_drive_manager.subir_informe(
                        creds_drive,
                        f"Tasacion_{marca}_{modelo}.html",
                        html_res,
                        folder_name=st.session_state["vendedor"],
                    )

                    if id_archivo:
                        st.session_state.informe_final = informe_texto
                        st.session_state.html = html_res
                        st.session_state.nombre_archivo = f"Tasacion_{marca}_{modelo}.html"
                        st.rerun()
                    else:
                        st.error("Error al subir el archivo a Google Drive.")

                except Exception as e:
                    st.error(f"Error crítico en el proceso: {str(e)}")

# --- 5. VISTA DE RESULTADOS ---
if "informe_final" in st.session_state:
    st.success(f"✅ Peritaje archivado correctamente para {st.session_state['vendedor']}.")
    
    st.markdown("### Resumen del Análisis")
    st.markdown(st.session_state.informe_final)

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        st.download_button(
            label="📄 DESCARGAR COPIA HTML",
            data=st.session_state.html,
            file_name=st.session_state.nombre_archivo,
            mime="text/html",
            use_container_width=True,
        )
    with col_btn2:
        if st.button("🔄 NUEVA TASACIÓN", use_container_width=True):
            for k in ["informe_final", "html", "nombre_archivo"]:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()
