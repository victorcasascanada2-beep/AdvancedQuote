import streamlit as st
import os
import io
import re
import requests
from datetime import datetime
from PIL import Image

import ia_engine
import html_generator
import google_drive_manager

# 1. CONFIGURACIÓN Y ESTILOS
st.set_page_config(page_title="Tasador Pro - Agrícola Noroeste", layout="centered", page_icon="🚜")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700;900&display=swap');
html, body, [class*="css"], .stMarkdown { font-family: 'Archivo', sans-serif !important; }
#MainMenu, footer, header, [data-testid="stHeader"] {visibility: hidden;}
.hero { background-color: #367C2B; border-left: 12px solid #FFDE00; padding: 1.5rem 2rem; margin-bottom: 2rem; }
.hero h1 { color: #FFFFFF !important; font-weight: 900; text-transform: uppercase; margin: 0; }
.stButton > button { background-color: #367C2B !important; color: white !important; font-weight: 700; text-transform: uppercase; width: 100%; height: 3.5rem; }
.ia-report { background-color: #FFFFFF; border-left: 5px solid #367C2B; border: 1px solid #E0E0E0; padding: 20px; color: #1A1A1A; }
</style>
""", unsafe_allow_html=True)

# 2. LÓGICA DE ACCESO
ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))
CREDS = dict(st.secrets["google"]) if "google" in st.secrets else None

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.markdown('<div class="hero"><h1>Tasador Pro</h1><p>Acceso Agentes</p></div>', unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["Ingresar", "Registrar Nuevo"])
    with tab1:
        vendedores = google_drive_manager.leer_vendedores(CREDS) or []
        v_sel = st.selectbox("Tu nombre:", [""] + vendedores)
        if st.button("ENTRAR") and v_sel:
            st.session_state.vendedor = v_sel; st.session_state.logged_in = True; st.rerun()
    with tab2:
        nuevo = st.text_input("Nombre completo:")
        if st.button("CREAR CUENTA") and nuevo:
            vendedores.append(nuevo)
            google_drive_manager.actualizar_vendedores(CREDS, vendedores)
            st.session_state.vendedor = nuevo; st.session_state.logged_in = True; st.rerun()
    st.stop()

# 3. HELPERS
def extraer_p(texto, clave):
    match = re.search(rf"{clave}.*?:\s*([\d\.]+)", texto, re.IGNORECASE)
    return float(match.group(1).replace(".", "")) if match else None

# 4. FORMULARIO
st.markdown(f'<div class="hero"><h1>Tasador Pro</h1><p>Agente: {st.session_state.vendedor}</p></div>', unsafe_allow_html=True)

if "result" not in st.session_state:
    with st.form("main_form"):
        st.subheader("📋 Datos")
        c1, c2 = st.columns(2)
        marca, modelo = c1.text_input("Marca", "John Deere"), c2.text_input("Modelo")
        anio, horas = c1.text_input("Año"), c2.text_input("Horas")
        cv = st.text_input("CV")
        obs = st.text_area("Notas")

        st.subheader("🛠️ Extras")
        e1, e2, e3 = st.columns(3)
        pala = e1.checkbox("Pala")
        anclajes = e1.checkbox("Anclajes")
        trip = e2.checkbox("Tripuntal")
        tdf = e2.checkbox("TDF")
        aire = e3.checkbox("Frenos Aire")

        st.subheader("🛞 Neumáticos")
        v_g = st.slider("Vida Traseros (%)", 0, 100, 80, step=10)
        v_p = st.slider("Vida Delanteros (%)", 0, 100, 80, step=10)

        fotos = st.file_uploader("Fotos (mín. 4)", accept_multiple_files=True)
        if st.form_submit_button("🚀 TASAR"):
            if not modelo or len(fotos or []) < 4: st.error("Faltan datos o fotos.")
            else:
                with st.spinner("IA trabajando..."):
                    client = ia_engine.conectar_vertex(CREDS)
                    # USAMOS LA LÓGICA QUE TENÍAS ORIGINALMENTE
                    fotos_raw = [{"name": f.name, "data": f.getvalue(), "type": f.type} for f in fotos]
                    
                    # Llamada directa sin la función que dio error
                    inf = ia_engine.realizar_peritaje(client, marca, modelo, anio, horas, obs, fotos_raw)
                    
                    vm, vv, vc = extraer_p(inf, "VALOR_MERCADO"), extraer_p(inf, "PRECIO_VENTA"), extraer_p(inf, "PRECIO_COMPRA")
                    
                    if vm:
                        # Cálculo de extras manual
                        cv_f = float(cv) if cv else 0.0
                        total_ex = (41.6 * cv_f if pala else 0) + (16.6 * cv_f if anclajes else 0) + (25.0 * cv_f if tdf else 20.8 * cv_f if trip else 0) + (1000 if aire else 0)
                        total_ex -= ((1-(v_g/100))*50*cv_f + (1-(v_p/100))*20*cv_f)

                        html = html_generator.generar_informe_html(marca, modelo, inf, [Image.open(io.BytesIO(f['data'])) for f in fotos_raw], "REF", vendedor=st.session_state.vendedor)
                        
                        st.session_state.result = {"inf": inf, "html": html, "vm": vm+total_ex, "vv": vv+total_ex, "vc": vc+total_ex, "mod": modelo}
                        st.rerun()

# 5. RESULTADOS
else:
    res = st.session_state.result
    st.success("Tasación Lista")
    c1, c2, c3 = st.columns(3)
    c1.metric("MERCADO", f"{res['vm']:,} €".replace(",", "."))
    c2.metric("VENTA", f"{res['vv']:,} €".replace(",", "."))
    c3.metric("COMPRA", f"{res['vc']:,} €".replace(",", "."))
    st.markdown(f'<div class="ia-report">{res["inf"]}</div>', unsafe_allow_html=True)
    if st.button("🔄 NUEVA"): del st.session_state.result; st.rerun()
