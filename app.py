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

# --- MANEJO DE SECRETOS ULTRA-SEGURO (HÍBRIDO) ---
creds_drive = None

try:
    # Intentamos acceder a st.secrets de forma que no rompa si el archivo no existe
    if "google" in st.secrets:
        creds_drive = dict(st.secrets["google"])
except Exception:
    # Si Streamlit lanza FileNotFoundError o KeyError, no hacemos nada.
    # creds_drive se queda como None y se usarán las ADC en Cloud Run.
    pass

# Validación de seguridad: Si no estamos en Cloud Run y no logramos cargar secretos
if not ES_CLOUD_RUN and creds_drive is None:
    st.warning("⚠️ Ejecutando en local sin archivo de secretos. Las funciones de Google podrían fallar.")
    # No detenemos (st.stop) por si acaso el usuario tiene ADC configuradas en su terminal local
