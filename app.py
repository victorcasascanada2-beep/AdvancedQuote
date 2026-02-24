import streamlit as st
import os
import io
import re
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional
from PIL import Image

import ia_engine
import html_generator
import google_drive_manager

# ------------------------------------------------------------
# 1. ESTILOS Y CONFIGURACIÓN
# ------------------------------------------------------------
st.set_page_config(page_title="Tasador Pro - Agrícola Noroeste", layout="centered", page_icon="🚜")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
html, body, [class*="css"], .stMarkdown { font-family: 'Inter', sans-serif !important; }
#MainMenu, footer, header, [data-testid="stHeader"] {visibility: hidden;}
.hero { background-color: #367C2B; border-radius: 4px; padding: 2rem; margin-bottom: 2rem; border-bottom: 6px solid #FFDE00; color: white; }
.hero h1 { font-weight: 700; margin: 0; color: white !important; }
.stButton > button { background-color: #367C2B !important; color: white !important; border-radius: 4px !important; font-weight: 600 !important; text-transform: uppercase; width: 100%; }
.stButton > button:hover { background-color: #2D6624 !important; color: #FFDE00 !important; }
.ia-report { background-color: #FFFFFF; border-left: 5px solid #367C2B; border: 1px solid #E0E0E0; padding: 20px; border-radius: 4px; color: #1A1A1A; }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# 2. LÓGICA DE ACCESO
# ------------------------------------------------------------
ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))
CREDS = dict(st.secrets["google"]) if "google" in st.secrets else None

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.markdown('<div class="hero"><h1>Tasador Pro</h1><p>Acceso Agentes</p></div>', unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["Ingresar", "Nuevo Registro"])
    with tab1:
        vendedores = google_drive_manager.leer_vendedores(CREDS) or []
        v_sel = st.selectbox("Selecciona tu nombre", [""] + vendedores)
        if st.button("ENTRAR") and v_sel:
            st.session_state.vendedor = v_sel; st.session_state.logged_in = True; st.rerun()
    with tab2:
        nuevo = st.text_input("Nombre completo")
        if st.button("REGISTRAR") and nuevo:
            vendedores.append(nuevo)
            google_drive_manager.actualizar_vendedores(CREDS, vendedores)
            st.session_state.vendedor = nuevo; st.session_state.logged_in = True; st.rerun()
    st.stop()

# ------------------------------------------------------------
# 3. FUNCIONES DE CÁLCULO
# ------------------------------------------------------------
def extraer_precio_ia(texto, clave):
    patron = rf"{clave}.*?:\s*([\d\.]+)"
    match = re.search(patron, texto, re.IGNORECASE)
    if match: return float(match.group(1).replace(".", ""))
    return None

def calcular_extras(cv, pala, trip, tdf, aire):
    # Coeficientes base (puedes leerlos de Drive si prefieres)
    total = 0.0
    cv_f = float(cv) if cv else 0.0
    if pala: total += (41.6 * cv_f)
    if tdf: total += (25.0 * cv_f)
    elif trip: total += (20.8 * cv_f)
    if aire: total += 1000.0
    return total

# ------------------------------------------------------------
# 4. FORMULARIO CON EXTRAS
# ------------------------------------------------------------
st.markdown(f'<div class="hero"><h1>Tasador Pro</h1><p>Agente: {st.session_state.vendedor}</p></div>', unsafe_allow_html=True)

if "result" not in st.session_state:
    with st.form("main_form"):
        st.subheader("📋 Datos Técnicos")
        c1, c2 = st.columns(2)
        marca = c1.text_input("Marca", "John Deere")
        modelo = c2.text_input("Modelo")
        anio = c1.text_input("Año")
        horas = c2.text_input("Horas")
        cv = c1.text_input("CV")
        obs = st.text_area("Notas de estado")

        st.subheader("🛠️ Equipamiento Extra")
        e1, e2, e3 = st.columns(3)
        extra_pala = e1.checkbox("Pala Cargadora")
        extra_tripuntal = e2.checkbox("Tripuntal Del.")
        extra_tdf = e3.checkbox("TDF Delantera")
        extra_aire = e1.checkbox("Frenos de Aire")

        fotos = st.file_uploader("Fotos (mín. 4)", accept_multiple_files=True)
        
        if st.form_submit_button("🚀 REALIZAR TASACIÓN"):
            if not modelo or not cv or len(fotos or []) < 4:
                st.error("Datos incompletos o pocas fotos.")
            else:
                with st.spinner("Analizando con IA..."):
                    client = ia_engine.conectar_vertex(CREDS)
                    fotos_raw = [{"name": f.name, "data": f.getvalue(), "type": f.type} for f in fotos]
                    inf = ia_engine.realizar_peritaje(client, marca, modelo, anio, horas, obs, fotos_raw)
                    
                    vm = extraer_precio_ia(inf, "VALOR_MERCADO")
                    vv = extraer_precio_ia(inf, "PRECIO_VENTA")
                    vc = extraer_precio_ia(inf, "PRECIO_COMPRA")
                    
                    if vm:
                        ajuste_extras = calcular_extras(cv, extra_pala, extra_tripuntal, extra_tdf, extra_aire)
                        html = html_generator.generar_informe_html(marca, modelo, inf, [Image.open(io.BytesIO(f['data'])) for f in fotos_raw], "REF", vendedor=st.session_state.vendedor)
                        
                        st.session_state.result = {
                            "inf": inf, "html": html, "mod": modelo,
                            "vm": vm + ajuste_extras, "vv": vv + ajuste_extras, "vc": vc + ajuste_extras
                        }
                        st.rerun()
                    else: st.error("Error al obtener precios de la IA.")

# ------------------------------------------------------------
# 5. PÁGINA DE RESULTADOS
# ------------------------------------------------------------
else:
    res = st.session_state.result
    st.success("✅ Tasación Calculada (IA + Extras)")
    c1, c2, c3 = st.columns(3)
    c1.metric("MERCADO TOTAL", f"{res['vm']:,} €".replace(",", "."))
    c2.metric("PVP VENTA", f"{res['vv']:,} €".replace(",", "."))
    c3.metric("COMPRA OFERTA", f"{res['vc']:,} €".replace(",", "."))

    st.markdown(f'<div class="ia-report">{res["inf"]}</div>', unsafe_allow_html=True)
    st.download_button("📥 Descargar Informe", res["html"], f"Tasacion_{res['mod']}.html", "text/html")
    if st.button("🔄 Nueva Tasación"):
        del st.session_state.result; st.rerun()
