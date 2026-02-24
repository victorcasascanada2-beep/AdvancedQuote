# app.py — Versión Integral Corporativa (John Deere Style)
import streamlit as st
import os
import io
import re
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional
from PIL import Image

# Importaciones de tus módulos
import ia_engine
import html_generator
import google_drive_manager

# ==========================================
# 1. CONFIGURACIÓN Y ESTILOS (ARCHIVO FONT)
# ==========================================
st.set_page_config(page_title="Tasador Pro - Agrícola Noroeste", layout="centered", page_icon="🚜")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700;900&display=swap');
html, body, [class*="css"], .stMarkdown { font-family: 'Archivo', sans-serif !important; }
#MainMenu, footer, header, [data-testid="stHeader"] {visibility: hidden;}

.hero {
    background-color: #367C2B;
    border-left: 12px solid #FFDE00;
    padding: 1.5rem 2rem;
    margin-bottom: 2rem;
    border-radius: 2px;
}
.hero h1 { color: #FFFFFF !important; font-weight: 900; text-transform: uppercase; letter-spacing: -1px; margin: 0; }
.hero p { color: #FFDE00 !important; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; margin: 0; }

div.stButton > button {
    background-color: #367C2B !important;
    color: #FFFFFF !important;
    border-radius: 2px !important;
    border: none !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    width: 100%;
    height: 3.5rem;
}
div.stButton > button:hover { background-color: #FFDE00 !important; color: #367C2B !important; }

[data-testid="stForm"] { background-color: #F8F9FA !important; border-radius: 4px !important; padding: 2rem !important; border: 1px solid #E0E0E0 !important; }
.ia-report { background-color: #FFFFFF; border-left: 5px solid #367C2B; border: 1px solid #E0E0E0; padding: 20px; border-radius: 4px; color: #1A1A1A; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. LÓGICA DE ENTORNO Y ACCESO
# ==========================================
ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))
CREDS = dict(st.secrets["google"]) if "google" in st.secrets else None

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.markdown('<div class="hero"><h1>Tasador Pro</h1><p>Agrícola Noroeste | Acceso Agentes</p></div>', unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["Ingresar", "Registrar Nuevo Agente"])
    with tab1:
        vendedores = google_drive_manager.leer_vendedores(CREDS) or []
        v_sel = st.selectbox("Selecciona tu nombre", [""] + vendedores)
        if st.button("ENTRAR") and v_sel:
            st.session_state.vendedor = v_sel; st.session_state.logged_in = True; st.rerun()
    with tab2:
        nuevo = st.text_input("Nombre completo del agente")
        if st.button("CREAR CUENTA") and nuevo.strip():
            vendedores.append(nuevo.strip())
            google_drive_manager.actualizar_vendedores(CREDS, vendedores)
            st.session_state.vendedor = nuevo.strip(); st.session_state.logged_in = True; st.rerun()
    st.stop()

# ==========================================
# 3. FUNCIONES DE APOYO (CÁLCULOS)
# ==========================================
def extraer_precio_ia(texto, clave):
    patron = rf"{clave}.*?:\s*([\d\.]+)"
    match = re.search(patron, texto, re.IGNORECASE)
    if match: return float(match.group(1).replace(".", ""))
    return None

def calcular_extras(cv, pala, anclajes, trip, tdf, aire, v_g, v_p):
    total = 0.0
    cv_f = float(cv) if cv else 0.0
    # Extras positivos
    if pala: total += (41.6 * cv_f)
    if anclajes: total += (16.6 * cv_f)
    if tdf: total += (25.0 * cv_f)
    elif trip: total += (20.8 * cv_f)
    if aire: total += 1000.0
    
    # Desgaste Neumáticos (Penalización)
    # Se calcula la diferencia entre el 100% y la vida actual
    penal_g = (1.0 - (v_g / 100.0)) * 50.0 * cv_f
    penal_p = (1.0 - (v_p / 100.0)) * 20.0 * cv_f
    total -= (penal_g + penal_p)
    
    return total

# ==========================================
# 4. FORMULARIO PRINCIPAL
# ==========================================
st.markdown(f'<div class="hero"><h1>Tasador Pro</h1><p>Agente: {st.session_state.vendedor}</p></div>', unsafe_allow_html=True)

if "result" not in st.session_state:
    with st.form("main_form"):
        st.subheader("📋 Datos Técnicos")
        c1, c2 = st.columns(2)
        marca = c1.text_input("Marca", "John Deere")
        modelo = c2.text_input("Modelo", "6175m")
        anio = c1.text_input("Año", "2018")
        horas = c2.text_input("Horas", "9988")
        cv = c1.text_input("CV", "175")
        obs = st.text_area("Notas de estado y mantenimiento")

        st.subheader("🛠️ Equipamiento Extra")
        e1, e2, e3 = st.columns(3)
        extra_pala = e1.checkbox("Pala Cargadora")
        extra_anclajes = e1.checkbox("Anclajes de Pala")
        extra_tripuntal = e2.checkbox("Tripuntal Del.")
        extra_tdf = e2.checkbox("TDF Delantera")
        extra_aire = e3.checkbox("Frenos de Aire")

        st.subheader("🛞 Estado de Neumáticos")
        # Barra desplazable (Slider)
        vida_g = st.slider("Vida útil Neumáticos Traseros (%)", 0, 100, 80, step=10)
        vida_p = st.slider("Vida útil Neumáticos Delanteros (%)", 0, 100, 80, step=10)

        fotos = st.file_uploader("Fotos (mín. 4)", accept_multiple_files=True)
        
        enviar = st.form_submit_button("🚀 REALIZAR TASACIÓN")

    if enviar:
        if not modelo or not cv or len(fotos or []) < 4:
            st.error("⚠️ Datos insuficientes. Asegúrate de poner el modelo, CV y subir 4 fotos.")
        else:
            with st.status("Analizando tractor con IA...", expanded=True) as status:
                try:
                    client = ia_engine.conectar_vertex(CREDS)
                    # Preparación segura de fotos para evitar AttributeError
                    fotos_list = [{"name": f.name, "data": f.getvalue(), "type": f.type} for f in fotos]
                    fotos_prep = ia_engine.preparar_fotos_para_ai(fotos_list)
                    
                    status.update(label="Generando peritaje técnico...")
                    inf = ia_engine.realizar_peritaje(client, marca, modelo, anio, horas, obs, fotos_prep)
                    
                    vm = extraer_precio_ia(inf, "VALOR_MERCADO")
                    vv = extraer_precio_ia(inf, "PRECIO_VENTA")
                    vc = extraer_precio_ia(inf, "PRECIO_COMPRA")
                    
                    if vm:
                        status.update(label="Calculando ajustes y extras...")
                        ajuste_total = calcular_extras(cv, extra_pala, extra_anclajes, extra_tripuntal, extra_tdf, extra_aire, vida_g, vida_p)
                        
                        # Generación de HTML (convertimos fotos para el visor)
                        fotos_pil = [Image.open(io.BytesIO(f.data)) for f in fotos_prep]
                        html = html_generator.generar_informe_html(marca, modelo, inf, fotos_pil, "REF-GPS", vendedor=st.session_state.vendedor)
                        
                        # Guardado en Google Sheets
                        url_sh = "https://script.google.com/macros/s/AKfycbw9hur2xbWaEetwNyl0U0_QaPSiFcZsbXITDJ-mYoswp5HzPxr1LFAwPfdNqSyAVl3h/exec"
                        requests.post(url_sh, json={
                            "vendedor": st.session_state.vendedor, "marca": marca, "modelo": modelo,
                            "horas": horas, "caballos": cv, "precioMercado": int(vm + ajuste_total),
                            "precioVenta": int(vv + ajuste_total), "precioCompra": int(vc + ajuste_total)
                        })

                        # Guardar informe en Drive
                        google_drive_manager.subir_informe(CREDS, f"Tasa_{modelo}.html", html, folder_name=st.session_state.vendedor)

                        st.session_state.result = {
                            "inf": inf, "html": html, "mod": modelo,
                            "vm": vm + ajuste_total, "vv": vv + ajuste_total, "vc": vc + ajuste_total
                        }
                        status.update(label="✅ Tasación completada", state="complete")
                        st.rerun()
                    else:
                        st.error("La IA no devolvió precios. Comprueba el config_prompt.")
                except Exception as e:
                    st.error(f"Error crítico: {e}")

# ==========================================
# 5. PÁGINA DE RESULTADOS
# ==========================================
else:
    res = st.session_state.result
    st.success("Resultados de la valoración profesional")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("MERCADO (INC. EXTRAS)", f"{res['vm']:,} €".replace(",", "."))
    col2.metric("PVP VENTA SUGERIDO", f"{res['vv']:,} €".replace(",", "."))
    col3.metric("OFERTA COMPRA MAX", f"{res['vc']:,} €".replace(",", "."))

    st.markdown("### 🤖 Informe del Perito IA")
    st.markdown(f'<div class="ia-report">{res["inf"]}</div>', unsafe_allow_html=True)
    
    st.download_button("📥 DESCARGAR INFORME HTML", res["html"], f"Tasacion_{res['mod']}.html", "text/html")
    
    if st.button("🔄 REALIZAR OTRA TASACIÓN"):
        del st.session_state.result
        st.rerun()
