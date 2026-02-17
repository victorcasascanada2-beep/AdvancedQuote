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

# Doble ejecución (NO cambiar):
# - Cloud Run: ADC (sin secrets)
# - Local/Streamlit: st.secrets["google"]
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
# VALIDACIÓN
# ------------------------------------------------------------
def _is_blank(s: str) -> bool:
    return (s is None) or (str(s).strip() == "")


def validar_datos(draft: Dict[str, Any]) -> List[str]:
    errores: List[str] = []

    # Campos obligatorios
    for campo in ["marca", "modelo", "anio", "horas"]:
        if _is_blank(draft.get(campo, "")):
            errores.append(f"El campo **{campo}** es obligatorio.")

    # Validación mínima razonable
    anio = str(draft.get("anio", "")).strip()
    horas = str(draft.get("horas", "")).strip()

    if anio and (not anio.isdigit() or len(anio) != 4):
        errores.append("El campo **año** debe ser un número de 4 dígitos (ej: 2022).")

    if horas:
        try:
            h = float(horas.replace(",", "."))
            if h < 0:
                errores.append("El campo **horas** no puede ser negativo.")
        except Exception:
            errores.append("El campo **horas** debe ser numérico.")

    # Fotos obligatorias (mínimo 4)
    fotos_state = draft.get("fotos_state") or []
    if len(fotos_state) < 4:
        errores.append("Debes subir **mínimo 4 fotos** para tasar.")

    return errores


# ------------------------------------------------------------
# FOTOS PERSISTENTES (borrador)
# ------------------------------------------------------------
def _fotos_to_state(uploaded_files) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
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
    fotos_pil: List[Image.Image] = []
    for item in fotos_state or []:
        fotos_pil.append(Image.open(io.BytesIO(item["data"])))
    return fotos_pil


class InMemoryUpload(io.BytesIO):
    """Wrapper mínimo para simular UploadedFile en ia_engine (name/type + stream)."""

    def __init__(self, data: bytes, name: str = "foto.jpg", mime: str = "image/jpeg"):
        super().__init__(data)
        self.name = name
        self.type = mime


def _state_to_uploadlike(fotos_state) -> List[InMemoryUpload]:
    return [
        InMemoryUpload(x["data"], x.get("name", "foto.jpg"), x.get("type", "image/jpeg"))
        for x in (fotos_state or [])
    ]


# ------------------------------------------------------------
# VENDEDORES (Drive) cacheado por entorno (cloud/local)
# ------------------------------------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def get_vendedores_cached(env_key: str) -> List[str]:
    creds = None if env_key == "cloud" else CREDS
    return google_drive_manager.leer_vendedores(creds) or []


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
        vendedores = get_vendedores_cached(ENV_KEY)

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
# LOGIN
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
        for k in ["logged_in", "vendedor", "draft", "result", "uploader_fotos", "vertex_client"]:
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
# BORRADOR PERSISTENTE
# ------------------------------------------------------------
st.session_state.setdefault(
    "draft",
    {
        "marca": "Valtra",
        "modelo": "G125",
        "anio": "2025",
        "horas": "2500",
        "obs": "",
        "fotos_state": [],  # mínimo 4 para tasar
    },
)

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

        cols = st.columns(min(4, len(fotos_guardadas)))
        for i, item in enumerate(fotos_guardadas[:4]):
            try:
                img = Image.open(io.BytesIO(item["data"]))
                cols[i].image(img, use_container_width=True)
            except Exception:
                pass
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

        obs = st.text_area("Observaciones adicionales del perito", value=st.session_state["draft"]["obs"])
        submit = st.form_submit_button("🚀 INICIAR TASACIÓN Y GUARDAR", use_container_width=True)

    if submit:
        # Persistir borrador
        st.session_state["draft"]["marca"] = marca
        st.session_state["draft"]["modelo"] = modelo
        st.session_state["draft"]["anio"] = anio
        st.session_state["draft"]["horas"] = horas
        st.session_state["draft"]["obs"] = obs

        errores = validar_datos(st.session_state["draft"])
        if errores:
            st.error("No se puede iniciar la tasación. Revisa:")
            for e in errores:
                st.markdown(f"- {e}")
        elif "vertex_client" not in st.session_state:
            st.error("El cliente de IA no está conectado.")
        else:
            with st.spinner("Procesando tasación..."):
                try:
                    fotos_pil = _state_to_pil_images(st.session_state["draft"]["fotos_state"])
                    fotos_for_ai = fotos_up if fotos_up else _state_to_uploadlike(st.session_state["draft"]["fotos_state"])

                    inf = ia_engine.realizar_peritaje(
                        st.session_state.vertex_client,
                        st.session_state["draft"]["marca"],
                        st.session_state["draft"]["modelo"],
                        st.session_state["draft"]["anio"],
                        st.session_state["draft"]["horas"],
                        st.session_state["draft"]["obs"],
                        fotos_for_ai,
                    )

                    ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")
                    html = html_generator.generar_informe_html(
                        st.session_state["draft"]["marca"],
                        st.session_state["draft"]["modelo"],
                        inf,
                        fotos_pil,
                        ref_b64,
                    )

                    nombre_fichero = f"Tasacion_{st.session_state['draft']['marca']}_{st.session_state['draft']['modelo']}.html"
                    carpeta = st.session_state.get("vendedor", "General")
                    creds_drive = None if ES_CLOUD_RUN else CREDS

                    id_archivo = google_drive_manager.subir_informe(
                        creds_drive,
                        nombre_fichero,
                        html,
                        folder_name=carpeta,
                    )

                    st.session_state["result"] = {
                        "informe_final": inf,
                        "html": html,
                        "nombre_archivo": nombre_fichero,
                        "id_archivo_drive": id_archivo,
                    }
                    st.rerun()

                except Exception as e:
                    st.error(f"Error en el proceso: {e}")

# ---------------- RESULTADOS ----------------
if "result" in st.session_state:
    res = st.session_state["result"]

    if res.get("id_archivo_drive"):
        st.success("✅ Peritaje finalizado y archivado en Drive.")
    else:
        st.success("✅ Peritaje finalizado.")
        st.warning("⚠️ No se recibió ID de Drive (permisos/archivo).")

    st.markdown("### Resultado del Análisis")
    st.markdown(res["informe_final"])

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
