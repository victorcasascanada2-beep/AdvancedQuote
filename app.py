# app.py — Tasador Agrícola Noroeste (VERSIÓN CON REGISTRO DE USUARIOS)
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
# 1. CONFIG PÁGINA Y ESTILOS
# ------------------------------------------------------------
st.set_page_config(page_title="Tasador Pro - Agrícola Noroeste", layout="centered", page_icon="🚜")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown { font-family: 'Inter', sans-serif !important; }
#MainMenu, footer, header, [data-testid="stHeader"] {visibility: hidden;}

.hero {
    background-color: #367C2B;
    border-radius: 4px;
    padding: 2rem;
    margin-bottom: 2rem;
    border-bottom: 6px solid #FFDE00;
}
.hero h1 { color: #FFFFFF !important; font-weight: 700; margin: 0; }
.hero p { color: #F0F0F0 !important; margin-top: 5px; }

[data-testid="stForm"], .card {
    background-color: #F9F9F9 !important;
    border: 1px solid #E0E0E0 !important;
    border-radius: 8px !important;
    padding: 1.5rem !important;
}
.ia-report {
    background-color: #FFFFFF;
    border-left: 5px solid #367C2B;
    border: 1px solid #E0E0E0;
    padding: 20px;
    border-radius: 4px;
    color: #1A1A1A;
}
.stButton > button {
    background-color: #367C2B !important;
    color: #FFFFFF !important;
    border-radius: 4px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    width: 100%;
}
.stButton > button:hover {
    background-color: #2D6624 !important;
    color: #FFDE00 !important;
}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# 2. LÓGICA DE ENTORNO
# ------------------------------------------------------------
ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE") or os.environ.get("K_REVISION"))
ENV_KEY = "cloud" if ES_CLOUD_RUN else "local"

def get_creds():
    if ES_CLOUD_RUN: return None
    try: return dict(st.secrets["google"])
    except: return None

CREDS = get_creds()

@st.cache_data(ttl=30, show_spinner=False)
def get_vendedores_cached(env_key):
    creds = None if env_key == "cloud" else CREDS
    return google_drive_manager.leer_vendedores(creds) or []

def invalidate_vendedores_cache():
    st.cache_data.clear()

# ------------------------------------------------------------
# 3. PANTALLA DE ACCESO / REGISTRO
# ------------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.markdown('<div class="hero"><h1>Tasador Pro</h1><p>Agrícola Noroeste | Acceso Agentes</p></div>', unsafe_allow_html=True)
    
    tab1, tab2 = st.tabs(["Seleccionar Agente", "Nuevo Registro"])
    
    with tab1:
        vendedores = get_vendedores_cached(ENV_KEY)
        with st.form("login_form"):
            v_sel = st.selectbox("Tu nombre:", [""] + vendedores)
            if st.form_submit_button("ENTRAR"):
                if v_sel:
                    st.session_state["logged_in"] = True
                    st.session_state["vendedor"] = v_sel
                    st.rerun()
                else:
                    st.warning("Selecciona un nombre.")

    with tab2:
        with st.form("registro_form"):
            nuevo_nom = st.text_input("Nombre Completo:")
            if st.form_submit_button("REGISTRAR Y ENTRAR"):
                if nuevo_nom.strip():
                    vendedores_actuales = get_vendedores_cached(ENV_KEY)
                    vendedores_actuales.append(nuevo_nom.strip())
                    # Guardar en Drive/Excel
                    google_drive_manager.actualizar_vendedores(None if ES_CLOUD_RUN else CREDS, vendedores_actuales)
                    invalidate_vendedores_cache()
                    st.session_state["logged_in"] = True
                    st.session_state["vendedor"] = nuevo_nom.strip()
                    st.rerun()
                else:
                    st.error("Escribe un nombre válido.")
    st.stop()

# ------------------------------------------------------------
# 4. FORMULARIO DE TASACIÓN (Si está logueado)
# ------------------------------------------------------------
st.markdown(f'<div class="hero"><h1>Tasador Pro</h1><p>Agente: {st.session_state.vendedor}</p></div>', unsafe_allow_html=True)

if "result" not in st.session_state:
    with st.form("main_tasacion"):
        c1, c2 = st.columns(2)
        marca = c1.text_input("Marca", "John Deere")
        modelo = c2.text_input("Modelo")
        anio = c1.text_input("Año")
        horas = c2.text_input("Horas")
        cv = c1.text_input("CV")
        obs = st.text_area("Notas de estado")
        
        fotos = st.file_uploader("Fotos (mín. 4)", accept_multiple_files=True)
        
        if st.form_submit_button("🚀 REALIZAR TASACIÓN"):
            if not modelo or not cv or len(fotos or []) < 4:
                st.error("Faltan datos o fotos.")
            else:
                with st.spinner("Procesando..."):
                    try:
                        client = ia_engine.conectar_vertex(None if ES_CLOUD_RUN else CREDS)
                        fotos_raw = [{"name": f.name, "data": f.getvalue(), "type": f.type} for f in fotos]
                        
                        inf = ia_engine.realizar_peritaje(client, marca, modelo, anio, horas, obs, fotos_raw)
                        
                        # Extraer precios (Función simple)
                        def get_p(k, t):
                            m = re.search(rf"{k}:\s*(\d+)", t)
                            return int(m.group(1)) if m else 0

                        vm, vv, vc = get_p("VALOR_MERCADO", inf), get_p("PRECIO_VENTA", inf), get_p("PRECIO_COMPRA", inf)
                        
                        if vm > 0:
                            # Enviar a Sheets
                            url_sh = "https://script.google.com/macros/s/AKfycbw9hur2xbWaEetwNyl0U0_QaPSiFcZsbXITDJ-mYoswp5HzPxr1LFAwPfdNqSyAVl3h/exec"
                            requests.post(url_sh, json={
                                "vendedor": st.session_state.vendedor, "marca": marca, "modelo": modelo,
                                "horas": horas, "caballos": cv, "precioMercado": vm, "precioVenta": vv, "precioCompra": vc
                            })
                            
                            # HTML y Drive
                            html = html_generator.generar_informe_html(marca, modelo, inf, [Image.open(io.BytesIO(f['data'])) for f in fotos_raw], "REF", vendedor=st.session_state.vendedor)
                            google_drive_manager.subir_informe(None if ES_CLOUD_RUN else CREDS, f"Tasa_{modelo}.html", html, folder_name=st.session_state.vendedor)
                            
                            st.session_state["result"] = {"inf": inf, "html": html, "vm": vm, "vv": vv, "vc": vc, "mod": modelo}
                            st.rerun()
                        else:
                            st.error("IA no generó precios. Revisa el formato.")
                    except Exception as e:
                        st.error(f"Error: {e}")

# ------------------------------------------------------------
# 5. PÁGINA DE RESULTADOS
# ------------------------------------------------------------
else:
    res = st.session_state["result"]
    st.success("Tasación finalizada.")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("MERCADO", f"{res['vm']:,} €".replace(",", "."))
    col2.metric("VENTA", f"{res['vv']:,} €".replace(",", "."))
    col3.metric("COMPRA", f"{res['vc']:,} €".replace(",", "."))

    st.markdown(f'<div class="ia-report">{res["inf"]}</div>', unsafe_allow_html=True)
    
    st.download_button("📥 Descargar Informe", res["html"], f"Tasacion_{res['mod']}.html", "text/html")
    
    if st.button("🔄 Nueva Tasación"):
        del st.session_state["result"]
        st.rerun()
