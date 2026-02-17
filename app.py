import streamlit as st
import os
import base64
from PIL import Image

import ia_engine
import html_generator
import google_drive_manager
import location_manager
from streamlit_js_eval import get_geolocation

st.set_page_config(page_title="Tasador Agrícola Noroeste", layout="centered", page_icon="🚜")

ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE") or os.environ.get("K_REVISION"))
ENV_KEY = "cloud" if ES_CLOUD_RUN else "local"


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


def get_creds():
    """
    Cloud Run: None (ADC) y NO toca st.secrets.
    Local: dict(st.secrets["google"]) (service account).
    """
    if ES_CLOUD_RUN:
        return None

    # Local: aquí sí usamos secrets y SI NO EXISTE, error claro.
    try:
        return dict(st.secrets["google"])
    except Exception:
        st.error("Faltan secrets locales: st.secrets['google'] (service account).")
        st.stop()


CREDS = get_creds()


@st.cache_data(ttl=30, show_spinner=False)
def get_vendedores_cached(env_key: str):
    # env_key separa cache cloud/local sin pasar dicts
    creds = None if env_key == "cloud" else CREDS
    return google_drive_manager.leer_vendedores(creds)


def invalidate_vendedores_cache():
    try:
        get_vendedores_cached.clear()
    except Exception:
        pass


def vista_acceso():
    if os.path.exists("agricolanoroestelogo.jpg"):
        st.image("agricolanoroestelogo.jpg", width=320)
    else:
        st.title("🚜 Agrícola Noroeste")

    st.subheader("Acceso de Tasadores")

    c1, c2 = st.columns([3, 1])
    with c2:
        if st.button("🔄 Refrescar", use_container_width=True):
            invalidate_vendedores_cache()
            st.rerun()

    with st.spinner("Cargando tasadores..."):
        vendedores = get_vendedores_cached(ENV_KEY) or []

    t1, t2 = st.tabs(["Seleccionar", "Registrar nuevo"])

    with t1:
        with st.form("form_sel"):
            v_sel = st.selectbox("Selecciona tu nombre:", [""] + vendedores, index=0)
            entrar = st.form_submit_button("Entrar", use_container_width=True)
        if entrar:
            if not v_sel:
                st.error("Selecciona un nombre.")
            else:
                st.session_state["logged_in"] = True
                st.session_state["vendedor"] = v_sel
                st.rerun()

    with t2:
        with st.form("form_reg", clear_on_submit=True):
            nuevo = st.text_input("Nombre y Apellido del nuevo tasador:")
            registrar = st.form_submit_button("Registrar y Entrar", use_container_width=True)

        if registrar:
            nombre = (nuevo or "").strip()
            if len(nombre) < 2:
                st.error("Introduce un nombre válido.")
                return

            if nombre in vendedores:
                st.session_state["logged_in"] = True
                st.session_state["vendedor"] = nombre
                st.rerun()

            creds = None if ES_CLOUD_RUN else CREDS
            ok = google_drive_manager.actualizar_vendedores(creds, vendedores + [nombre])

            if ok:
                invalidate_vendedores_cache()
                st.session_state["logged_in"] = True
                st.session_state["vendedor"] = nombre
                st.rerun()
            else:
                st.error("No se pudo escribir en vendedores.txt (permisos o archivo no encontrado).")


if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    vista_acceso()
    st.stop()

ocultar_chrome_streamlit()

col_logo, col_logout = st.columns([6, 1])
with col_logo:
    st.markdown(f"### 🚜 {st.session_state.get('vendedor','')}")
with col_logout:
    if st.button("Salir", use_container_width=True):
        for k in ["logged_in", "vendedor", "informe_final", "html", "nombre_archivo", "id_archivo_drive"]:
            st.session_state.pop(k, None)
        st.rerun()

st.divider()

# Vertex: Cloud Run => None (ADC), Local => dict secrets
if "vertex_client" not in st.session_state:
    try:
        creds_vertex = None if ES_CLOUD_RUN else CREDS
        st.session_state.vertex_client = ia_engine.conectar_vertex(creds_vertex)
    except Exception as e:
        st.error(f"Error inicializando Vertex AI: {e}")

loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = (
    location_manager.codificar_coordenadas(loc["coords"]["latitude"], loc["coords"]["longitude"])
    if loc and "coords" in loc
    else "UBICACIÓN NO DETECTADA"
)

if "informe_final" not in st.session_state:
    with st.form("form_peritaje"):
        st.subheader("Datos del Peritaje")

        fotos = st.file_uploader(
            "Subir fotos del tractor",
            accept_multiple_files=True,
            type=["jpg", "jpeg", "png"],
        )

        col1, col2 = st.columns(2)
        with col1:
            marca = st.text_input("Marca", value="Valtra")
            modelo = st.text_input("Modelo", value="G125")
        with col2:
            anio = st.text_input("Año", value="2025")
            horas = st.text_input("Horas", value="2500")

        obs = st.text_area("Observaciones adicionales del perito")
        submit = st.form_submit_button("🚀 INICIAR TASACIÓN Y GUARDAR", use_container_width=True)

    if submit:
        if not fotos:
            st.error("Sube al menos una foto.")
        elif "vertex_client" not in st.session_state:
            st.error("El cliente de IA no está conectado.")
        else:
            with st.spinner("Procesando tasación..."):
                try:
                    inf = ia_engine.realizar_peritaje(
                        st.session_state.vertex_client, marca, modelo, anio, horas, obs, fotos
                    )

                    ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")
                    fotos_pil = [Image.open(f) for f in fotos]
                    html = html_generator.generar_informe_html(marca, modelo, inf, fotos_pil, ref_b64)

                    nombre_fichero = f"Tasacion_{marca}_{modelo}.html"
                    carpeta = st.session_state.get("vendedor", "General")

                    creds_drive = None if ES_CLOUD_RUN else CREDS
                    id_archivo = google_drive_manager.subir_informe(
                        creds_drive, nombre_fichero, html, folder_name=carpeta
                    )

                    st.session_state.informe_final = inf
                    st.session_state.html = html
                    st.session_state.nombre_archivo = nombre_fichero
                    st.session_state.id_archivo_drive = id_archivo

                    st.rerun()
                except Exception as e:
                    st.error(f"Error en el proceso: {e}")

if "informe_final" in st.session_state:
    if st.session_state.get("id_archivo_drive"):
        st.success("✅ Peritaje finalizado y archivado en Drive.")
    else:
        st.success("✅ Peritaje finalizado.")
        st.warning("⚠️ No se recibió ID de Drive (permisos/archivo).")

    st.markdown("### Resultado del Análisis")
    st.markdown(st.session_state.informe_final)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            label="📄 DESCARGAR HTML",
            data=st.session_state.html,
            file_name=st.session_state.nombre_archivo,
            mime="text/html",
            use_container_width=True,
        )
    with c2:
        if st.button("🔄 NUEVA TASACIÓN", use_container_width=True):
            for k in ["informe_final", "html", "nombre_archivo", "id_archivo_drive"]:
                st.session_state.pop(k, None)
            st.rerun()
