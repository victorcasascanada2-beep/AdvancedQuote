# app.py — Tasador Agrícola Noroeste (CORREGIDO Y ESTILIZADO)
import streamlit as st
import os
import io
import re
import base64
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
# UI GLOBAL (ESTILOS Y BRANDING)
# ------------------------------------------------------------
def ocultar_chrome_streamlit():
    st.markdown(
        """
<style>
/* Reset de fuente general */
html, body, [class*="css"] {
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
}

.block-container {
    max-width: 1100px;
    padding-top: 1.8rem;
    padding-bottom: 2.2rem;
}

#MainMenu, footer, header {visibility: hidden;}

.hero {
  background: linear-gradient(135deg, rgba(63,163,77,.18), rgba(125,186,58,.18));
  border: 1px solid rgba(47,111,62,.25);
  border-radius: 22px;
  padding: 18px;
  margin-bottom: 18px;
}
.hero h1 { margin: 0; color: #1F3D2B; font-size: 1.8rem; }
.hero p { margin: 0; color: #4F6F5B; }

.card {
  background: #F3F8F3;
  border: 1px solid rgba(47,111,62,.18);
  border-radius: 18px;
  padding: 16px;
}

/* Nuevo estilo para el bloque de EXTRAS */
.extras-container {
    background-color: #ffffff;
    border: 1px solid rgba(47,111,62,.2);
    border-radius: 14px;
    padding: 18px;
    color: #1F3D2B;
    line-height: 1.6;
    white-space: pre-wrap;
    box-shadow: 0 2px 5px rgba(0,0,0,0.03);
    font-size: 0.95rem;
    margin-bottom: 1rem;
}

div[data-baseweb="input"] input,
div[data-baseweb="textarea"] textarea {
  border-radius: 14px !important;
  border: 1px solid rgba(47,111,62,.25) !important;
}

.stButton > button {
  background: linear-gradient(135deg, #3FA34D, #7DBA3A) !important;
  color: #ffffff !important;
  border-radius: 14px !important;
  border: none !important;
  font-weight: 700 !important;
  padding: 0.7rem 1.1rem !important;
}
</style>

<div class="hero">
  <h1>🌱 Tasación de maquinaria</h1>
  <p>Agrícola Noroeste · Valoración profesional</p>
</div>
""",
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------
# FUNCIONES DE APOYO (Helpers)
# ------------------------------------------------------------
def get_creds():
    if ES_CLOUD_RUN: return None
    try:
        return dict(st.secrets["google"])
    except Exception:
        st.error("Faltan secrets locales: st.secrets['google'].")
        st.stop()

CREDS = get_creds()

def _parse_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", ".").strip())
    except:
        return 0.0

def fmt_eur(x: Optional[float]) -> str:
    if x is None: return "—"
    return f"{x:,.0f} €".replace(",", "X").replace(".", ",").replace("X", ".")

# ------------------------------------------------------------
# LÓGICA DE NEGOCIO (COEFICIENTES / EXTRAS)
# ------------------------------------------------------------
DEFAULT_COEFS = {
    "pala_eur_por_cv": 41.6,
    "anclajes_eur_por_cv": 16.6,
    "tripuntal_eur_por_cv": 20.8,
    "tripuntal_tdf_eur_por_cv": 25.0,
    "compresor_eur_fijo": 1000.0,
    "contrapesos_eur_por_kg": 1.0,
    "neumaticos": {"max_grandes_eur_por_cv": 50.0, "max_pequenos_eur_por_cv": 20.0},
    "autoguiado_eur_por_cv": 0.0, "autoguiado_eur_fijo": 0.0,
}

@st.cache_data(ttl=60)
def get_coeficientes_cached(env_key: str):
    creds = None if env_key == "cloud" else CREDS
    coefs = google_drive_manager.leer_coeficientes(creds) or {}
    merged = dict(DEFAULT_COEFS)
    merged.update(coefs)
    return merged

def calcular_ajustes_extras(draft: Dict[str, Any], coefs: Dict[str, Any]) -> Tuple[float, List[Tuple[str, float]]]:
    cv = _parse_float(draft["cv"])
    kg = _parse_float(draft.get("kg_contrapesos", 0))
    vida_g = float(draft.get("vida_neum_grandes", 100) or 100)
    vida_p = float(draft.get("vida_neum_pequenos", 100) or 100)

    desglose = []
    total = 0.0

    if draft.get("extra_pala"):
        v = float(coefs.get("pala_eur_por_cv", 0)) * cv
        desglose.append(("Pala usada", v)); total += v
    elif draft.get("extra_anclajes_pala"):
        v = float(coefs.get("anclajes_eur_por_cv", 0)) * cv
        desglose.append(("Anclajes de pala", v)); total += v

    if draft.get("extra_tdf_del"):
        v = float(coefs.get("tripuntal_tdf_eur_por_cv", 0)) * cv
        desglose.append(("Tripuntal + TDF del.", v)); total += v
    elif draft.get("extra_tripuntal_del"):
        v = float(coefs.get("tripuntal_eur_por_cv", 0)) * cv
        desglose.append(("Tripuntal del.", v)); total += v

    if draft.get("extra_compresor"):
        v = float(coefs.get("compresor_eur_fijo", 0))
        desglose.append(("Compresor aire", v)); total += v

    if draft.get("extra_autoguiado"):
        v = (float(coefs.get("autoguiado_eur_por_cv", 0)) * cv) + float(coefs.get("autoguiado_eur_fijo", 0))
        if v > 0: desglose.append(("Autoguiado", v)); total += v

    if kg > 0:
        v = float(coefs.get("contrapesos_eur_por_kg", 0)) * kg
        desglose.append((f"Contrapesos ({kg:.0f} kg)", v)); total += v

    neu = coefs.get("neumaticos", {})
    penal_g = (1.0 - (vida_g / 100.0)) * float(neu.get("max_grandes_eur_por_cv", 50)) * cv
    penal_p = (1.0 - (vida_p / 100.0)) * float(neu.get("max_pequenos_eur_por_cv", 20)) * cv

    if penal_g > 0: desglose.append((f"Neumáticos grandes (vida {vida_g:.0f}%)", -penal_g)); total -= penal_g
    if penal_p > 0: desglose.append((f"Neumáticos pequeños (vida {vida_p:.0f}%)", -penal_p)); total -= penal_p

    return total, desglose

def bloque_extras_texto(total_ajustes: float, items: List[Tuple[str, float]]) -> str:
    lines = ["**[EXTRAS / AJUSTES (APARTE)]**"]
    for concepto, importe in items:
        sign = "+" if importe >= 0 else "-"
        lines.append(f"• {concepto}: {sign}{fmt_eur(abs(importe))}")
    lines.append(f"\n**TOTAL EXTRAS/APARTADOS: {fmt_eur(total_ajustes)}**")
    return "\n".join(lines)

# ------------------------------------------------------------
# PARSEO IA Y VALIDACIÓN
# ------------------------------------------------------------
def parse_resultado_final(text: str) -> Dict[str, float]:
    out = {}
    m = re.search(r"(?is)BLOQUE\s*:\s*RESULTADO_FINAL\s*(.*?)(?:\n\s*BLOQUE|$)", text)
    block = m.group(1) if m else ""
    
    keys = ["VALOR_BASE", "AJUSTE_HORAS_%", "AJUSTE_ESTADO_%", "VALOR_MERCADO", "PRECIO_VENTA", "PRECIO_COMPRA"]
    for k in keys:
        found = re.search(rf"(?im)^\s*-?\s*{re.escape(k)}\s*:\s*([\-]?\d+)", block)
        if found: out[k] = float(found.group(1))

    vb = out.get("VALOR_BASE")
    if vb and "VALOR_MERCADO" not in out:
        ah = out.get("AJUSTE_HORAS_%", 0); ae = out.get("AJUSTE_ESTADO_%", 0)
        out["VALOR_MERCADO"] = round(vb * (1 + ah/100) * (1 + ae/100))
    
    vm = out.get("VALOR_MERCADO")
    if vm:
        if "PRECIO_VENTA" not in out: out["PRECIO_VENTA"] = round(vm * 0.92)
        if "PRECIO_COMPRA" not in out: out["PRECIO_COMPRA"] = round(vm * 0.85)
    return out

def validar_datos(draft: Dict[str, Any]) -> List[str]:
    err = []
    for c in ["marca", "modelo", "anio", "horas", "cv"]:
        if not str(draft.get(c, "")).strip(): err.append(f"El campo **{c}** es obligatorio.")
    if len(draft.get("fotos_state", [])) < 4: err.append("Sube al menos **4 fotos**.")
    return err

# ------------------------------------------------------------
# VISTAS STREAMLIT
# ------------------------------------------------------------
def vista_acceso():
    if os.path.exists("Transparente.png"): st.image("Transparente.png", width=320)
    st.subheader("Acceso de Tasadores")
    vendedores = google_drive_manager.leer_vendedores(CREDS) or []
    v_sel = st.selectbox("Tu nombre:", [""] + vendedores)
    if st.button("Entrar", use_container_width=True) and v_sel:
        st.session_state["logged_in"] = True
        st.session_state["vendedor"] = v_sel
        st.rerun()

# --- MAIN ---
if not st.session_state.get("logged_in"):
    vista_acceso()
    st.stop()

ocultar_chrome_streamlit()
COEFS = get_coeficientes_cached(ENV_KEY)

# Conexión IA
if "vertex_client" not in st.session_state:
    st.session_state.vertex_client = ia_engine.conectar_vertex(None if ES_CLOUD_RUN else CREDS)

# GPS
loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = location_manager.codificar_coordenadas(loc["coords"]["latitude"], loc["coords"]["longitude"]) if loc else "UBICACIÓN NO DETECTADA"

# State inicial
if "draft" not in st.session_state:
    st.session_state.draft = {"marca": "Valtra", "modelo": "", "anio": "", "horas": "", "cv": "", "kg_contrapesos": "0", "fotos_state": []}

# FORMULARIO
if "result" not in st.session_state:
    with st.form("peritaje"):
        c1, c2 = st.columns(2)
        marca = c1.text_input("Marca", st.session_state.draft["marca"])
        modelo = c2.text_input("Modelo", st.session_state.draft["modelo"])
        anio = c1.text_input("Año", st.session_state.draft["anio"])
        horas = c2.text_input("Horas", st.session_state.draft["horas"])
        cv = c1.text_input("CV", st.session_state.draft["cv"])
        kg = c2.text_input("Kg contrapesos", "0")
        
        st.markdown("#### Extras y Neumáticos")
        e1, e2 = st.columns(2)
        pala = e1.checkbox("Pala")
        trip = e1.checkbox("Tripuntal del.")
        v_g = e2.selectbox("Vida Neum. Grandes %", [100, 80, 60, 40, 20, 0])
        v_p = e2.selectbox("Vida Neum. Pequeños %", [100, 80, 60, 40, 20, 0])
        
        fotos_up = st.file_uploader("Fotos (mín. 4)", accept_multiple_files=True, type=["jpg", "png"])
        
        if st.form_submit_button("🚀 TASAR"):
            d = st.session_state.draft
            d.update({"marca": marca, "modelo": modelo, "anio": anio, "horas": horas, "cv": cv, "kg_contrapesos": kg,
                      "extra_pala": pala, "extra_tripuntal_del": trip, "vida_neum_grandes": v_g, "vida_neum_pequenos": v_p})
            if fotos_up: 
                d["fotos_state"] = [{"data": f.getvalue(), "name": f.name, "type": f.type} for f in fotos_up]
            
            err = validar_datos(d)
            if err: 
                for e in err: st.error(e)
            else:
                with st.spinner("Analizando..."):
                    total_aj, items_aj = calcular_ajustes_extras(d, COEFS)
                    inf = ia_engine.realizar_peritaje(st.session_state.vertex_client, d["marca"], d["modelo"], d["anio"], d["horas"], "", fotos_up)
                    st.session_state.result = {
                        "informe_final": inf,
                        "base_dict": parse_resultado_final(inf),
                        "extras_total": total_aj,
                        "bloque_extras": bloque_extras_texto(total_aj, items_aj),
                        "nombre_archivo": f"Tasacion_{marca}.html"
                    }
                    st.rerun()

# RESULTADOS
else:
    res = st.session_state.result
    base = res["base_dict"]
    
    st.markdown("### 🤖 Informe de IA")
    st.markdown(f'<div class="card">{res["informe_final"]}</div>', unsafe_allow_html=True)
    
    st.markdown("### 💰 Valores de Mercado")
    c1, c2, c3 = st.columns(3)
    c1.metric("MERCADO", fmt_eur(base.get("VALOR_MERCADO")))
    c2.metric("VENTA", fmt_eur(base.get("PRECIO_VENTA")))
    c3.metric("COMPRA", fmt_eur(base.get("PRECIO_COMPRA")))

    st.markdown("### 🛠️ Extras y Ajustes")
    # AQUÍ ESTÁ EL CAMBIO DE TIPOGRAFÍA Y ESTILO:
    st.markdown(f'<div class="extras-container">{res["bloque_extras"]}</div>', unsafe_allow_html=True)

    if st.button("↩️ Nueva Tasación"):
        st.session_state.pop("result")
        st.rerun()
