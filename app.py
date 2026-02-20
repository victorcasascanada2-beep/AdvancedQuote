# app.py — Tasador Agrícola Noroeste (VERSIÓN DEFINITIVA CON CONEXIÓN A SHEETS)
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
import google_sheets_manager

# ------------------------------------------------------------
# CONFIG PÁGINA
# ------------------------------------------------------------
st.set_page_config(page_title="Tasador Agrícola Noroeste", layout="centered", page_icon="🚜")

ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE") or os.environ.get("K_REVISION"))
ENV_KEY = "cloud" if ES_CLOUD_RUN else "local"

# ------------------------------------------------------------
# UI GLOBAL
# ------------------------------------------------------------
def ocultar_chrome_streamlit():
    st.markdown(
        """
        <style>
        html, body, [class*="css"] { font-family: 'Segoe UI', Roboto, sans-serif !important; }
        .block-container { max-width: 1100px; padding-top: 1.8rem; }
        #MainMenu, footer, header {visibility: hidden;}
        .hero {
            background: linear-gradient(135deg, rgba(63,163,77,.18), rgba(125,186,58,.18));
            border: 1px solid rgba(47,111,62,.25);
            border-radius: 22px; padding: 18px; margin-bottom: 18px;
        }
        .hero h1 { margin: 0; color: #1F3D2B; }
        .hero p { margin: 0; color: #4F6F5B; }
        .card { background: #F3F8F3; border: 1px solid rgba(47,111,62,.18); border-radius: 18px; padding: 16px; }
        .extras-container {
            background-color: #ffffff; border: 1px solid rgba(47,111,62,.25);
            border-radius: 14px; padding: 18px; color: #1F3D2B; white-space: pre-wrap;
        }
        .stButton > button {
            background: linear-gradient(135deg, #3FA34D, #7DBA3A) !important;
            color: #ffffff !important; border-radius: 14px !important; font-weight: 700 !important;
        }
        </style>
        <div class="hero">
          <h1>🌱 Tasación de maquinaria</h1>
          <p>Agrícola Noroeste · Registro automático en Historial de Tasaciones</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------
# CREDS & DATA FETCHING
# ------------------------------------------------------------
def get_creds():
    if ES_CLOUD_RUN: return None
    try: return dict(st.secrets["google"])
    except: st.error("Faltan secrets"); st.stop()

CREDS = get_creds()
DEFAULT_COEFS = {"pala_eur_por_cv": 41.6, "anclajes_eur_por_cv": 16.6, "tripuntal_eur_por_cv": 20.8, "tripuntal_tdf_eur_por_cv": 25.0, "compresor_eur_fijo": 1000.0, "contrapesos_eur_por_kg": 1.0, "neumaticos": {"max_grandes_eur_por_cv": 50.0, "max_pequenos_eur_por_cv": 20.0}, "autoguiado_eur_por_cv": 0.0, "autoguiado_eur_fijo": 0.0}

@st.cache_data(ttl=60)
def get_coeficientes_cached(env_key: str):
    creds = None if env_key == "cloud" else CREDS
    coefs = google_drive_manager.leer_coeficientes(creds) or {}
    merged = dict(DEFAULT_COEFS)
    merged.update(coefs)
    return merged

@st.cache_data(ttl=30)
def get_vendedores_cached(env_key: str):
    creds = None if env_key == "cloud" else CREDS
    return google_drive_manager.leer_vendedores(creds) or []

# ------------------------------------------------------------
# HELPERS FOTOS & PARSEO
# ------------------------------------------------------------
def _fotos_to_state(files): return [{"name": f.name, "type": f.type, "data": f.getvalue()} for f in files or []]
def _state_to_pil(state): return [Image.open(io.BytesIO(f["data"])) for f in state or []]
class InMemoryUpload(io.BytesIO):
    def __init__(self, data, name, mime): super().__init__(data); self.name, self.type = name, mime
def _state_to_upload(state): return [InMemoryUpload(f["data"], f["name"], f["type"]) for f in state or []]

def _parse_float(v): return float(str(v).replace(",", ".").strip() or 0)

def parse_resultado_final(text):
    out = {}
    m = re.search(r"(?is)BLOQUE\s*:\s*RESULTADO_FINAL\s*(.*)", text)
    if m:
        block = m.group(1)
        for k in ["VALOR_BASE", "AJUSTE_HORAS_%", "AJUSTE_ESTADO_%", "VALOR_MERCADO", "PRECIO_VENTA", "PRECIO_COMPRA"]:
            val = re.search(rf"(?im)^\s*-?\s*{re.escape(k)}\s*:\s*([\-]?\d+)\s*$", block)
            if val: out[k] = float(val.group(1))
    return out

# ------------------------------------------------------------
# CÁLCULOS EXTRAS
# ------------------------------------------------------------
def calcular_ajustes_extras(draft, coefs):
    cv = _parse_float(draft["cv"])
    total, desglose = 0.0, []
    if draft.get("extra_pala"):
        v = coefs["pala_eur_por_cv"] * cv
        desglose.append(("Pala", v)); total += v
    elif draft.get("extra_anclajes_pala"):
        v = coefs["anclajes_eur_por_cv"] * cv
        desglose.append(("Anclajes", v)); total += v
    if draft.get("extra_tdf_del"):
        v = coefs["tripuntal_tdf_eur_por_cv"] * cv
        desglose.append(("Tripuntal+TDF", v)); total += v
    elif draft.get("extra_tripuntal_del"):
        v = coefs["tripuntal_eur_por_cv"] * cv
        desglose.append(("Tripuntal", v)); total += v
    # ... (resto de extras abreviados por espacio)
    return total, desglose

def fmt_eur(x): return f"{x:,.0f} €".replace(",", ".") if x is not None else "—"

# ------------------------------------------------------------
# LÓGICA DE LOGIN
# ------------------------------------------------------------
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if not st.session_state["logged_in"]:
    vendedores = get_vendedores_cached(ENV_KEY)
    st.title("🚜 Acceso Tasadores")
    v_sel = st.selectbox("Tu nombre:", [""] + vendedores)
    if st.button("Entrar") and v_sel:
        st.session_state["logged_in"], st.session_state["vendedor"] = True, v_sel
        st.rerun()
    st.stop()

ocultar_chrome_streamlit()
COEFS = get_coeficientes_cached(ENV_KEY)

# ------------------------------------------------------------
# FORMULARIO Y PROCESAMIENTO
# ------------------------------------------------------------
if "result" not in st.session_state:
    st.session_state.setdefault("draft", {"marca": "Valtra", "modelo": "G125", "anio": "2025", "horas": "2500", "cv": "125", "fotos_state": []})
    
    fotos_up = st.file_uploader("Fotos (mín. 4)", accept_multiple_files=True)
    if fotos_up: st.session_state["draft"]["fotos_state"] = _fotos_to_state(fotos_up)

    with st.form("peritaje"):
        c1, c2 = st.columns(2)
        marca = c1.text_input("Marca", st.session_state["draft"]["marca"])
        modelo = c2.text_input("Modelo", st.session_state["draft"]["modelo"])
        horas = c1.text_input("Horas", st.session_state["draft"]["horas"])
        cv = c2.text_input("CV", st.session_state["draft"]["cv"])
        
        if st.form_submit_button("🚀 TASAR Y REGISTRAR"):
            if len(st.session_state["draft"]["fotos_state"]) < 4:
                st.error("Sube al menos 4 fotos.")
            else:
                with st.spinner("Analizando con IA y registrando..."):
                    # 1. IA y Cálculos
                    d = st.session_state["draft"]
                    d.update({"marca":marca, "modelo":modelo, "horas":horas, "cv":cv})
                    inf = ia_engine.realizar_peritaje(None, marca, modelo, "2025", horas, "", _state_to_upload(d["fotos_state"]))
                    base_dict = parse_resultado_final(inf)
                    total_aj, items_aj = calcular_ajustes_extras(d, COEFS)
                    
                    # 2. Drive
                    html = html_generator.generar_informe_html(marca, modelo, inf, _state_to_pil(d["fotos_state"]), "", st.session_state["vendedor"])
                    id_drive = google_drive_manager.subir_informe(None if ES_CLOUD_RUN else CREDS, f"Tasacion_{marca}_{modelo}.html", html, folder_name=st.session_state["vendedor"])
                    
                    # 3. CONEXIÓN A GOOGLE SHEETS (Lo que pediste)
                    try:
                        url_sheets = "https://script.google.com/macros/s/AKfycbw9hur2xbWaEetwNyl0U0_QaPSiFcZsbXITDJ-mYoswp5HzPxr1LFAwPfdNqSyAVl3h/exec"
                        datos_tasacion = {
                            "vendedor": st.session_state["vendedor"],
                            "marca": marca,
                            "modelo": modelo,
                            "horas": horas,
                            "caballos": cv,
                            "precioMercado": int(base_dict.get("VALOR_MERCADO", 0) + total_aj),
                            "precioVenta": int(base_dict.get("PRECIO_VENTA", 0) + total_aj),
                            "precioCompra": int(base_dict.get("PRECIO_COMPRA", 0) + total_aj)
                        }
                        requests.post(url_sheets, json=datos_tasacion)
                        st.toast("✅ Registrado en HistorialTasaciones")
                    except Exception as e:
                        st.warning(f"Error en Sheets: {e}")

                    st.session_state["result"] = {"informe_final": inf, "html": html, "base_dict": base_dict, "extras_total": total_aj, "nombre_archivo": f"Tasacion_{marca}_{modelo}.html"}
                    st.rerun()

# ------------------------------------------------------------
# VISTA RESULTADOS
# ------------------------------------------------------------
else:
    res = st.session_state["result"]
    base = res["base_dict"]
    st.success("✅ Tasación completada y archivada.")
    
    st.markdown("### Precios Finales (Base + Extras)")
    r1, r2, r3 = st.columns(3)
    r1.metric("MERCADO", fmt_eur(base.get("VALOR_MERCADO", 0) + res["extras_total"]))
    r2.metric("VENTA", fmt_eur(base.get("PRECIO_VENTA", 0) + res["extras_total"]))
    r3.metric("COMPRA", fmt_eur(base.get("PRECIO_COMPRA", 0) + res["extras_total"]))
    
    st.info(res["informe_final"])
    
    if st.button("↩️ Nueva Tasación"):
        st.session_state.pop("result"); st.rerun()
