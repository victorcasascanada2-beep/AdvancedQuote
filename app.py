import streamlit as st
import os
import io
import base64
from typing import List, Dict, Any
from PIL import Image

import ia_engine
import html_generator
import google_drive_manager
import location_manager
from streamlit_js_eval import get_geolocation

# ------------------------------------------------------------
# CONFIG PÁGINA
# ------------------------------------------------------------
st.set_page_config(page_title="Tasador Agrícola Noroeste", layout="centered", page_icon="🚜")

# Doble ejecución: Cloud Run (ADC sin secrets) vs Local (con secrets)
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
    Cloud Run: None (ADC) y NO toca st.secrets nunca.
    Local: dict(st.secrets["google"]) (service account).
    """
    if ES_CLOUD_RUN:
        return None
    try:
        return dict(st.secrets["google"])
    except Exception:
        st.error("Faltan secrets locales: st.secrets['google'] (service account).")
        st.stop()


CREDS = get_creds()


# ------------------------------------------------------------
# FOTOS PERSISTENTES (para volver a tasar sin perder nada)
# ------------------------------------------------------------
def _fotos_to_state(uploaded_files) -> List[Dict[str, Any]]:
    out = []
    for f in uploaded_files or []:
        out.append(
            {
                "name": getattr(f, "name", "foto.jpg"),
                "type": getattr(f, "type", "image/jpeg"),
                "data": f.getvalue(),  # bytes
            }
        )
    return out


def _state_to_pil_images(fotos_state) -> List[Image.Image]:
    fotos_pil = []
    for item in (fotos_state or []):
        fotos_pil.append(Image.open(io.BytesIO(item["data"])))
    return fotos_pil


class InMemoryUpload(io.BytesIO):
    """Wrapper tipo UploadedFile (mínimo) con .name y .type."""
    def __init__(self, data: bytes, name: str = "foto.jpg", mime: str = "image/jpeg"):
        super().__init__(data)
        self.name = name
        self.type = mime


def _state_to_uploadlike(fotos_state) -> List[InMemoryUpload]:
    out = []
    for item in (fotos_state or []):
        out.append(InMemoryUpload(item["data"], item.get("name", "foto.jpg"), item.get("type", "image/jpeg")))
    return out


# ------------------------------------------------------------
# VENDEDORES (Drive) con cache estable cloud/local
# ------------------------------------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def get_vendedores_cached(env_key: str):
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


# ------------------------------------------------------------
# SESIÓN LOGIN
# ------------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    vista_acceso()
    st.stop()

ocultar_chrome_streamlit()

# ------------------------------------------------------------
# HEADER
# ------------------------------------------------------------
col_logo, col_logout = st.columns([6, 1])
with col_logo:
    st.markdown(f"### 🚜 {st.session_state.get('vendedor','')}")
with col_logout:
    if st.button("Salir", use_container_width=True):
        # NO cambies la doble ejecución. Solo limpiamos lo de la sesión de usuario/app.
        for k in [
            "logged_in",
            "vendedor",
            "informe_final",
            "html",
            "nombre_archivo",
            "id_archivo_drive",
            "marca",
            "modelo",
            "anio",
            "horas",
            "obs",
            "fotos_state",
            "uploader_fotos",
        ]:
            st.session_state.pop(k, None)
        st.rerun()

st.divider()

# ------------------------------------------------------------
# CONEXIÓN IA (doble ejecución intacta)
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
# ESTADO PERSISTENTE DE CAMPOS
# ------------------------------------------------------------
st.session_state.setdefault("marca", "Valtra")
st.session_state.setdefault("modelo", "G125")
st.session_state.setdefault("anio", "2025")
st.session_state.setdefault("horas", "2500")
st.session_state.setdefault("obs", "")
st.session_state.setdefault("fotos_state", [])  # [{name,type,data(bytes)}]


# ------------------------------------------------------------
# FORMULARIO PERITAJE (conservar campos + fotos)
# ------------------------------------------------------------
if "informe_final" not in st.session_state:
    st.subheader("Datos del Peritaje")

    # Uploader fuera del form: más estable para estado / reruns
    fotos_up = st.file_uploader(
        "Subir fotos del tractor",
        accept_multiple_files=True,
        type=["jpg", "jpeg", "png"],
        key="uploader_fotos",
    )

    # Si hay nuevas fotos, las persistimos
    if fotos_up:
        st.session_state["fotos_state"] = _fotos_to_state(fotos_up)

    if st.session_state["fotos_state"]:
        st.caption(f"Fotos cargadas: {len(st.session_state['fotos_state'])}")

    with st.form("form_peritaje", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Marca", key="marca")
            st.text_input("Modelo", key="modelo")
        with col2:
            st.text_input("Año", key="anio")
            st.text_input("Horas", key="horas")

        st.text_area("Observaciones adicionales del perito", key="obs")

        submit = st.form_submit_button("🚀 INICIAR TASACIÓN Y GUARDAR", use_container_width=True)

    if submit:
        if not st.session_state["fotos_state"]:
            st.error("Sube al menos una foto.")
        elif "vertex_client" not in st.session_state:
            st.error("El cliente de IA no está conectado.")
        else:
            with st.spinner("Procesando tasación..."):
                try:
                    # Para HTML
                    fotos_pil = _state_to_pil_images(st.session_state["fotos_state"])

                    # Para IA: si el uploader trae objetos, úsalo; si no, recrea file-like
                    fotos_for_ai = fotos_up if fotos_up else _state_to_uploadlike(st.session_state["fotos_state"])

                    inf = ia_engine.realizar_peritaje(
                        st.session_state.vertex_client,
                        st.session_state["marca"],
                        st.session_state["modelo"],
                        st.session_state["anio"],
                        st.session_state["horas"],
                        st.session_state["obs"],
                        fotos_for_ai,
                    )

                    ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")
                    html = html_generator.generar_informe_html(
                        st.session_state["marca"],
                        st.session_state["modelo"],
                        inf,
                        fotos_pil,
                        ref_b64,
                    )

                    nombre_fichero = f"Tasacion_{st.session_state['marca']}_{st.session_state['modelo']}.html"
                    carpeta = st.session_state.get("vendedor", "General")

                    creds_drive = None if ES_CLOUD_RUN else CREDS
                    id_archivo = google_drive_manager.subir_informe(
                        creds_drive,
                        nombre_fichero,
                        html,
                        folder_name=carpeta,
                    )

                    st.session_state.informe_final = inf
                    st.session_state.html = html
                    st.session_state.nombre_archivo = nombre_fichero
                    st.session_state.id_archivo_drive = id_archivo

                    st.rerun()

                except Exception as e:
                    st.error(f"Error en el proceso: {e}")


# ------------------------------------------------------------
# RESULTADOS + VOLVER A TASAR (sin perder fotos ni datos)
# ------------------------------------------------------------
if "informe_final" in st.session_state:
    if st.session_state.get("id_archivo_drive"):
        st.success("✅ Peritaje finalizado y archivado en Drive.")
    else:
        st.success("✅ Peritaje finalizado.")
        st.warning("⚠️ No se recibió ID de Drive (permisos/archivo).")

    st.markdown("### Resultado del Análisis")
    st.markdown(st.session_state.informe_final)

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        st.download_button(
            label="📄 DESCARGAR HTML",
            data=st.session_state.html,
            file_name=st.session_state.nombre_archivo,
            mime="text/html",
            use_container_width=True,
        )
    with col_btn2:
        if st.button("↩️ VOLVER A TASAR (mantener datos y fotos)", use_container_width=True):
            # Solo borramos salida; mantenemos marca/modelo/año/horas/obs/fotos_state/uploader
            for k in ["informe_final", "html", "nombre_archivo", "id_archivo_drive"]:
                st.session_state.pop(k, None)
            st.rerun()
