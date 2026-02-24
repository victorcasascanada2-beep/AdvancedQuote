# app.py — Tasador Agrícola Noroeste (VERSIÓN INTEGRAL REPARADA)
import streamlit as st
import os
import io
import re
import base64
import requests
from typing import List, Dict, Any, Tuple, Optional
from PIL import Image

import ia_engine
import html_generator
import google_drive_manager
import location_manager
from streamlit_js_eval import get_geolocation

# ------------------------------------------------------------
# 1. CONFIG PÁGINA Y ESTILOS (SINTAXIS CORREGIDA)
# ------------------------------------------------------------
st.set_page_config(page_title="Tasador Pro - Agrícola Noroeste", layout="centered", page_icon="🚜")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"], .stMarkdown {
    font-family: 'Inter', sans-serif !important;
}

#MainMenu, footer, header, [data-testid="stHeader"] {visibility: hidden;}

.hero {
    background-color: #367C2B;
    border-radius: 4px;
    padding: 2rem;
    margin-bottom: 2rem;
    border-bottom: 6px solid #FFDE00;
}

.hero h1 {
    color: #FFFFFF !important;
    font-weight: 700;
    margin: 0;
}

.hero p {
    color: #F0F0F0 !important;
    margin-top: 5px;
}

[data-testid="stForm"], .card {
    background-color: #F9F9F9 !important;
    border: 1px solid #E0E0E0 !important;
    border-radius: 8px !important;
    padding: 1.5rem !important;
}

.ia-report, .extras-container {
    background-color: #FFFFFF;
    border-left: 5px solid #367C2B;
    border: 1px solid #E0E0E0;
    padding: 20px;
    border-radius: 4px;
    color: #1A1A1A;
    line-height: 1.6;
}

.stButton > button {
    background-color: #367C2B !important;
    color: #FFFFFF !important;
    border-radius: 4px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
}

.stButton > button:hover {
    background-color: #2D6624 !important;
    color: #FFDE00 !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
    <h1>Tasador Pro | Agrícola Noroeste</h1>
    <p>Sistema Inteligente de Valoración de Maquinaria de Ocasión</p>
</div>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# 2. LÓGICA DE ENTORNO Y CREDENCIALES
# ------------------------------------------------------------
ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE") or os.environ.get("K_REVISION"))
ENV_KEY = "cloud" if ES_CLOUD_RUN else "local"

def get_creds():
    if ES_CLOUD_RUN: return None
    try:
        return dict(st.secrets["google"])
    except Exception:
        st.error("Faltan secrets locales: st.secrets['google'].")
        st.stop()

CREDS = get_creds()

# ------------------------------------------------------------
# 3. HELPERS Y CACHÉ
# ------------------------------------------------------------
DEFAULT_COEFS = {
    "pala_eur_por_cv": 41.6, "anclajes_eur_por_cv": 16.6,
    "tripuntal_eur_por_cv": 20.8, "tripuntal_tdf_eur_por_cv": 25.0,
    "compresor_eur_fijo": 1000.0, "contrapesos_eur_por_kg": 1.0,
    "neumaticos": {"max_grandes_eur_por_cv": 50.0, "max_pequenos_eur_por_cv": 20.0},
}

@st.cache_data(ttl=60, show_spinner=False)
def get_coeficientes_cached(env_key):
    creds = None if env_key == "cloud" else CREDS
    coefs = google_drive_manager.leer_coeficientes(creds) or {}
    merged = dict(DEFAULT_COEFS)
    merged.update(coefs)
    return merged

@st.cache_data(ttl=30, show_spinner=False)
def get_vendedores_cached(env_key):
    creds = None if env_key == "cloud" else CREDS
    return google_drive_manager.leer_vendedores(creds) or []

def fmt_eur(x: Optional[float]) -> str:
    if x is None: return "—"
    return f"{x:,.0f} €".replace(",", "X").replace(".", ",").replace("X", ".")

def extraer_precio_ia(texto: str, clave: str):
    import re
    match = re.search(fr"(?im)^\s*-?\s*{re.escape(clave)}\s*:\s*([\-]?\d+)\s*$", texto)
    return float(match.group(1)) if match else None

# ------------------------------------------------------------
# 4. ACCESO Y LOGIN
# ------------------------------------------------------------
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.subheader("Acceso de Tasadores")
    vendedores = get_vendedores_cached(ENV_KEY)
    v_sel = st.selectbox("Selecciona tu nombre:", [""] + vendedores)
    if st.button("Entrar") and v_sel:
        st.session_state["logged_in"] = True
        st.session_state["vendedor"] = v_sel
        st.rerun()
    st.stop()

# ------------------------------------------------------------
# 5. FORMULARIO PRINCIPAL
# ------------------------------------------------------------
COEFS = get_coeficientes_cached(ENV_KEY)

if "result" not in st.session_state:
    st.subheader(f"Agente: {st.session_state.vendedor}")
    
    with st.form("form_peritaje"):
        c1, c2 = st.columns(2)
        marca = c1.text_input("Marca *", "John Deere")
        modelo = c2.text_input("Modelo *")
        anio = c1.text_input("Año *")
        horas = c2.text_input("Horas *")
        cv = c1.text_input("CV *")
        obs = st.text_area("Observaciones adicionales")
        
        fotos_up = st.file_uploader("Subir fotos (mín. 4)", accept_multiple_files=True)
        
        if st.form_submit_button("🚀 INICIAR TASACIÓN"):
            if not modelo or not cv or len(fotos_up or []) < 4:
                st.error("Completa los datos y sube 4 fotos.")
            else:
                with st.spinner("Procesando con IA..."):
                    try:
                        # 1. Conectar y Peritar
                        client = ia_engine.conectar_vertex(None if ES_CLOUD_RUN else CREDS)
                        # Procesamos fotos (uso simplificado para evitar errores de RAM)
                        fotos_raw = [{"name": f.name, "data": f.getvalue(), "type": f.type} for f in fotos_up]
                        
                        inf = ia_engine.realizar_peritaje(client, marca, modelo, anio, horas, obs, fotos_raw)
                        
                        # 2. Parseo de Precios
                        v_mercado = extraer_precio_ia(inf, "VALOR_MERCADO")
                        v_venta = extraer_precio_ia(inf, "PRECIO_VENTA")
                        v_compra = extraer_precio_ia(inf, "PRECIO_COMPRA")
                        
                        if v_mercado:
                            # 3. Guardar en Sheets
                            url_sheets = "https://script.google.com/macros/s/AKfycbw9hur2xbWaEetwNyl0U0_QaPSiFcZsbXITDJ-mYoswp5HzPxr1LFAwPfdNqSyAVl3h/exec"
                            requests.post(url_sheets, json={
                                "vendedor": st.session_state["vendedor"],
                                "marca": marca, "modelo": modelo, "horas": horas, "caballos": cv,
                                "precioMercado": int(v_mercado),
                                "precioVenta": int(v_venta),
                                "precioCompra": int(v_compra)
                            })
                            
                            # 4. Generar HTML y Guardar en Drive
                            html = html_generator.generar_informe_html(marca, modelo, inf, [Image.open(io.BytesIO(f['data'])) for f in fotos_raw], "REF", vendedor=st.session_state.vendedor)
                            google_drive_manager.subir_informe(None if ES_CLOUD_RUN else CREDS, f"Tasacion_{modelo}.html", html, folder_name=st.session_state.vendedor)
                            
                            st.session_state["result"] = {
                                "informe": inf, "html": html, "v_m": v_mercado, "v_v": v_venta, "v_c": v_compra, "modelo": modelo
                            }
                            st.rerun()
                        else:
                            st.error("La IA no devolvió el bloque RESULTADO_FINAL correctamente.")
                    except Exception as e:
                        st.error(f"Error: {e}")

# ------------------------------------------------------------
# 6. PÁGINA DE RESULTADOS
# ------------------------------------------------------------
else:
    res = st.session_state["result"]
    st.success("✅ Tasación Completada y Archivada")
    
    c1, c2, c3 = st.columns(3)
    c1.metric("VALOR MERCADO", fmt_eur(res["v_m"]))
    c2.metric("PVP VENTA", fmt_eur(res["v_v"]))
    c3.metric("OFERTA COMPRA", fmt_eur(res["v_c"]))

    st.markdown("### 🤖 Análisis IA")
    st.markdown(f'<div class="ia-report">{res["informe"]}</div>', unsafe_allow_html=True)
    
    if st.button("↩️ NUEVA TASACIÓN"):
        del st.session_state["result"]
        st.rerun()
