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

# Detector de entorno Cloud Run
ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE") or os.environ.get("K_REVISION"))

# -------------------------------------------------------------------
# ESTILO: ocultar chrome Streamlit (solo tras login)
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
# LOGIN (5 vendedores definidos en código)
# -------------------------------------------------------------------
VENDEDORES = {
    "vendedor1": "clave1",
    "vendedor2": "clave2",
    "vendedor3": "clave3",
    "vendedor4": "clave4",
    "vendedor5": "clave5",
}

def vista_login():
    st.title("🔐 Acceso de vendedor")
    with st.form("login_form", clear_on_submit=False):
        vendedor = st.selectbox("Vendedor", list(VENDEDORES.keys()))
        clave = st.text_input("Clave", type="password")
        ok = st.form_submit_button("Entrar", use_container_width=True)

    if ok:
        if VENDEDORES.get(vendedor) == clave:
            st.session_state["logged_in"] = True
            st.session_state["vendedor"] = vendedor
            st.rerun()
        else:
            st.error("Usuario o clave incorrectos.")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    vista_login()
    st.stop()

# A partir de aquí: UI limpia (sin chrome Streamlit)
ocultar_chrome_streamlit()

# -------------------------------------------------------------------
# HEADER APP: Logo izquierda + botón salir derecha (sin mostrar vendedor)
# -------------------------------------------------------------------
col_logo, col_logout = st.columns([6, 1])

with col_logo:
    if os.path.exists("agricolanoroestelogo.jpg"):
        st.image("agricolanoroestelogo.jpg", width=320)
    else:
        st.markdown("## 🚜 Agrícola Noroeste")

with col_logout:
    if st.button("Salir", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.divider()

# --- 2. CONEXIÓN AL MOTOR DE IA (CONSOLA DEBUG) ---
if "vertex_client" not in st.session_state:
    try:
        creds = None
        if not ES_CLOUD_RUN and "google" in st.secrets:
            creds = dict(st.secrets["google"])
        st.session_state.vertex_client = ia_engine.conectar_vertex(creds)
    except Exception as e:
        st.error(f"Error inicializando Vertex AI: {e}")

# --- 3. GESTIÓN DE UBICACIÓN (GPS) ---
loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = (
    location_manager.codificar_coordenadas(
        loc["coords"]["latitude"],
        loc["coords"]["longitude"],
    )
    if loc and "coords" in loc
    else "UBICACIÓN NO DETECTADA"
)

# --- 5. FORMULARIO DE ENTRADA ---
# Solo mostramos el formulario si no hay un informe generado
if "informe_final" not in st.session_state:
    with st.form("form_tasacion"):
        st.subheader("Datos del Peritaje")

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

    # --- 6. LÓGICA DE PROCESAMIENTO Y SUBIDA ---
    if submit and fotos:
        if "vertex_client" not in st.session_state:
            st.error("El cliente de IA no está conectado.")
        else:
            # Contenedor para mensajes de rastreo (Debug)
            status_placeholder = st.empty()

            with st.spinner("Procesando peritaje..."):
                try:
                    # PASO A: Llamada a la IA
                    status_placeholder.info("📡 Paso 1: Enviando datos a Gemini 2.0...")
                    informe_texto = ia_engine.realizar_peritaje(
                        st.session_state.vertex_client, marca, modelo, anio, horas, obs, fotos
                    )

                    # PASO B: Preparar referencia oculta y HTML
                    status_placeholder.info("📑 Paso 2: Generando documento de tasación...")
                    ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")
                    fotos_pil = [Image.open(f) for f in fotos]
                    html_res = html_generator.generar_informe_html(
                        marca, modelo, informe_texto, fotos_pil, ref_b64
                    )

                    # PASO C: PUNTO DE CONTROL DE DRIVE
                    status_placeholder.warning(
                        f"📤 Paso 3: Solicitando 'save to Drive' para {marca}_{modelo}..."
                    )

                    creds_drive = None if ES_CLOUD_RUN else dict(st.secrets["google"])

                    # Carpeta destino = vendedor logueado
                    carpeta_vendedor = st.session_state.get("vendedor", "General")

                    # Llamada a la función de subida
                    id_archivo = google_drive_manager.subir_informe(
                        creds_drive,
                        f"Tasacion_{marca}_{modelo}.html",
                        html_res,
                        folder_name=carpeta_vendedor,
                    )

                    if id_archivo:
                        status_placeholder.success(f"✅ ¡ÉXITO! Guardado en Drive (ID: {id_archivo})")
                    else:
                        status_placeholder.error(
                            "❌ El proceso de Drive terminó pero NO devolvió un ID de archivo."
                        )

                    # Guardar resultados en sesión
                    st.session_state.informe_final = informe_texto
                    st.session_state.html = html_res
                    st.session_state.nombre_archivo = f"Tasacion_{marca}_{modelo}.html"

                    # Pequeña pausa para que veas el mensaje de éxito antes de recargar
                    import time
                    time.sleep(2)
                    st.rerun()

                except Exception as e:
                    st.error(f"💥 Error crítico en el flujo: {str(e)}")

# --- 7. VISTA DE RESULTADOS (POST-PROCESADO) ---
if "informe_final" in st.session_state:
    st.success("✅ Peritaje completado y archivado.")

    st.markdown("### Resultado del Análisis")
    st.markdown(st.session_state.informe_final)

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        st.download_button(
            label="📄 VER/DESCARGAR HTML",
            data=st.session_state.html,
            file_name=st.session_state.nombre_archivo,
            mime="text/html",
            use_container_width=True,
        )
    with col_btn2:
        if st.button("🔄 NUEVA TASACIÓN", use_container_width=True):
            # No borres login/sesión vendedor
            for k in ["informe_final", "html", "nombre_archivo"]:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()
