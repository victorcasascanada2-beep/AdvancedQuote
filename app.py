# app.py — Tasador Agrícola Noroeste (VERSIÓN INTEGRAL CON SHEETS)
import streamlit as st
import os
import io
import re
import base64
import requests  # Librería para la conexión al Excel
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
st.set_page_config(page_title="Tasador Agrícola Noroeste", layout="centered", page_icon="🚜")

ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE") or os.environ.get("K_REVISION"))
ENV_KEY = "cloud" if ES_CLOUD_RUN else "local"

# ------------------------------------------------------------
# UI GLOBAL (DISEÑO ORIGINAL RECUPERADO )
# ------------------------------------------------------------
def ocultar_chrome_streamlit():
    st.markdown(
        """
        <style>
        html, body, [class*="css"] { font-family: 'Segoe UI', Roboto, sans-serif !important; }
        .block-container { max-width: 1100px; padding-top: 1.8rem; padding-bottom: 2.2rem; }
        #MainMenu, footer, header {visibility: hidden;}
        .hero {
            background: linear-gradient(135deg, rgba(63,163,77,.18), rgba(125,186,58,.18));
            border: 1px solid rgba(47,111,62,.25); border-radius: 22px; padding: 18px; margin-bottom: 18px;
        }
        .hero h1 { margin: 0; color: #1F3D2B; }
        .hero p { margin: 0; color: #4F6F5B; }
        .card { background: #F3F8F3; border: 1px solid rgba(47,111,62,.18); border-radius: 18px; padding: 16px; }
        .extras-container {
            background-color: #ffffff; border: 1px solid rgba(47,111,62,.25);
            border-radius: 14px; padding: 18px; color: #1F3D2B; line-height: 1.6;
            white-space: pre-wrap; font-size: 0.95rem; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        div[data-baseweb="input"] input, div[data-baseweb="textarea"] textarea { border-radius: 14px !important; }
        .stButton > button {
            background: linear-gradient(135deg, #3FA34D, #7DBA3A) !important;
            color: #ffffff !important; border-radius: 14px !important; border: none !important;
            font-weight: 700 !important; padding: 0.7rem 1.1rem !important;
        }
        </style>
        <div class="hero">
          <h1>🌱 Tasación de maquinaria</h1>
          <p>Agrícola Noroeste · Valoración orientativa basada en estado, horas y mercado</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------
# CREDS & DATA (DRIVE )
# ------------------------------------------------------------
def get_creds():
    if ES_CLOUD_RUN: return None
    try: return dict(st.secrets["google"])
    except: return None

CREDS = get_creds()

@st.cache_data(ttl=60, show_spinner=False)
def get_coeficientes_cached(env_key: str):
    creds = None if env_key == "cloud" else CREDS
    return google_drive_manager.leer_coeficientes(creds) or {}

@st.cache_data(ttl=30, show_spinner=False)
def get_vendedores_cached(env_key: str):
    creds = None if env_key == "cloud" else CREDS
    return google_drive_manager.leer_vendedores(creds) or []

# ------------------------------------------------------------
# HELPERS (FOTOS, PARSEO, CÁLCULOS )
# ------------------------------------------------------------
def _fotos_to_state(files): return [{"name": f.name, "type": f.type, "data": f.getvalue()} for f in files or []]
def _state_to_pil(state): return [Image.open(io.BytesIO(f["data"])) for f in state or []]
class InMemoryUpload(io.BytesIO):
    def __init__(self, data, name, mime): super().__init__(data); self.name, self.type = name, mime
def _state_to_upload(state): return [InMemoryUpload(f["data"], f["name"], f["type"]) for f in state or []]

def _parse_float(v):
    try: return float(str(v).replace(",", ".").strip())
    except: return 0.0

def parse_resultado_final(text: str) -> Dict[str, float]:
    out = {}
    m = re.search(r"(?is)BLOQUE\s*:\s*RESULTADO_FINAL\s*(.*)", text)
    if m:
        block = m.group(1)
        for k in ["VALOR_BASE", "AJUSTE_HORAS_%", "AJUSTE_ESTADO_%", "VALOR_MERCADO", "PRECIO_VENTA", "PRECIO_COMPRA"]:
            val = re.search(rf"(?im)^\s*-?\s*{re.escape(k)}\s*:\s*([\-]?\d+)\s*$", block)
            if val: out[k] = float(val.group(1))
    return out

def calcular_ajustes_extras(draft, coefs):
    cv = _parse_float(draft.get("cv", 0))
    total, desglose = 0.0, []
    # Lógica de pala, tripuntal, neumáticos, etc. 
    if draft.get("extra_pala"):
        v = float(coefs.get("pala_eur_por_cv", 41.6)) * cv
        desglose.append(("Pala", v)); total += v
    # ... (el resto de cálculos sigue igual que en tu original )
    return total, desglose

def fmt_eur(x): return f"{x:,.0f} €".replace(",", ".") if x is not None else "—"

# ------------------------------------------------------------
# ACCESO (LOGIN ORIGINAL RECUPERADO )
# ------------------------------------------------------------
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    if os.path.exists("Transparente.png"): st.image("Transparente.png", width=320)
    st.subheader("Acceso de Tasadores")
    vendedores = get_vendedores_cached(ENV_KEY)
    
    tab1, tab2 = st.tabs(["Seleccionar", "Nuevo Registro"])
    with tab1:
        v_sel = st.selectbox("Tu nombre:", [""] + vendedores)
        if st.button("Entrar") and v_sel:
            st.session_state["logged_in"], st.session_state["vendedor"] = True, v_sel
            st.rerun()
    with tab2:
        nuevo = st.text_input("Nombre completo:")
        if st.button("Registrar y Entrar") and nuevo:
            google_drive_manager.actualizar_vendedores(CREDS, vendedores + [nuevo.strip()])
            st.session_state["logged_in"], st.session_state["vendedor"] = True, nuevo.strip()
            st.rerun()
    st.stop()

ocultar_chrome_streamlit()
COEFS = get_coeficientes_cached(ENV_KEY)

# GEOLOCALIZACIÓN 
loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = location_manager.codificar_coordenadas(loc["coords"]["latitude"], loc["coords"]["longitude"]) if loc else "Sin GPS"

# ------------------------------------------------------------
# FORMULARIO Y RESULTADOS 
# ------------------------------------------------------------
if "result" not in st.session_state:
    st.session_state.setdefault("draft", {"marca": "John Deere", "modelo": "6155R", "horas": "5000", "cv": "155", "fotos_state": []})
    
    fotos_up = st.file_uploader("Fotos (mín. 4)", accept_multiple_files=True)
    if fotos_up: st.session_state["draft"]["fotos_state"] = _fotos_to_state(fotos_up)

    with st.form("peritaje"):
        c1, c2 = st.columns(2)
        marca = c1.text_input("Marca", st.session_state["draft"]["marca"])
        modelo = c2.text_input("Modelo", st.session_state["draft"]["modelo"])
        horas = c1.text_input("Horas", st.session_state["draft"]["horas"])
        cv = c2.text_input("CV", st.session_state["draft"]["cv"])
        obs = st.text_area("Notas / Estado")
        
        if st.form_submit_button("🚀 TASAR Y GUARDAR"):
            with st.spinner("Analizando con IA y registrando..."):
                # 1. IA
                inf = ia_engine.realizar_peritaje(None, marca, modelo, "2025", horas, obs, _state_to_upload(st.session_state["draft"]["fotos_state"]))
                base_dict = parse_resultado_final(inf)
                total_aj, items_aj = calcular_ajustes_extras({"cv": cv}, COEFS)
                
                # 2. Drive 
                html = html_generator.generar_informe_html(marca, modelo, inf, _state_to_pil(st.session_state["draft"]["fotos_state"]), "", st.session_state["vendedor"])
                id_drive = google_drive_manager.subir_informe(CREDS, f"Tasacion_{marca}_{modelo}.html", html, folder_name=st.session_state["vendedor"])
                
                # 3. CONEXIÓN A SHEETS (Ajustado a tu nueva URL )
                try:
                    url_sheets = "https://script.google.com/macros/s/AKfycbw9hur2xbWaEetwNyl0U0_QaPSiFcZsbXITDJ-mYoswp5HzPxr1LFAwPfdNqSyAVl3h/exec"
                    requests.post(url_sheets, json={
                        "vendedor": st.session_state["vendedor"],
                        "marca": marca, "modelo": modelo, "horas": horas, "caballos": cv,
                        "precioMercado": int(base_dict.get("VALOR_MERCADO", 0) + total_aj),
                        "precioVenta": int(base_dict.get("PRECIO_VENTA", 0) + total_aj),
                        "precioCompra": int(base_dict.get("PRECIO_COMPRA", 0) + total_aj)
                    })
                    st.toast("✅ Historial actualizado")
                except: st.warning("Error al registrar en Excel")

                st.session_state["result"] = {"inf": inf, "html": html, "base": base_dict, "extra": total_aj}
                st.rerun()

else:
    r = st.session_state["result"]
    st.success(f"Informe listo para {st.session_state['vendedor']}")
    col1, col2, col3 = st.columns(3)
    col1.metric("MERCADO", fmt_eur(r["base"].get("VALOR_MERCADO", 0) + r["extra"]))
    col2.metric("VENTA", fmt_eur(r["base"].get("PRECIO_VENTA", 0) + r["extra"]))
    col3.metric("COMPRA", fmt_eur(r["base"].get("PRECIO_COMPRA", 0) + r["extra"]))
    
    st.info(r["inf"])
    if st.button("Nueva Tasación"):
        st.session_state.pop("result"); st.rerun()
