# app.py — Tasador Agrícola Noroeste (COMPLETO Y RESTAURADO)
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
/* Fuente general limpia para toda la app */
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
.hero h1 { margin: 0; color: #1F3D2B; }
.hero p { margin: 0; color: #4F6F5B; }

.card {
  background: #F3F8F3;
  border: 1px solid rgba(47,111,62,.18);
  border-radius: 18px;
  padding: 16px;
}

/* Estilo para el bloque de EXTRAS (reemplaza al st.code) */
.extras-container {
    background-color: #ffffff;
    border: 1px solid rgba(47,111,62,.25);
    border-radius: 14px;
    padding: 20px;
    color: #1F3D2B;
    line-height: 1.6;
    white-space: pre-wrap;
    font-size: 0.95rem;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    margin-top: 10px;
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
  <p>Agrícola Noroeste · Valoración profesional basada en estado, horas y mercado</p>
</div>
""",
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------
# CREDS Y COEFICIENTES
# ------------------------------------------------------------
def get_creds():
    if ES_CLOUD_RUN: return None
    try: return dict(st.secrets["google"])
    except: return None

CREDS = get_creds()

DEFAULT_COEFS = {
    "pala_eur_por_cv": 41.6, "anclajes_eur_por_cv": 16.6,
    "tripuntal_eur_por_cv": 20.8, "tripuntal_tdf_eur_por_cv": 25.0,
    "compresor_eur_fijo": 1000.0, "contrapesos_eur_por_kg": 1.0,
    "neumaticos": {"max_grandes_eur_por_cv": 50.0, "max_pequenos_eur_por_cv": 20.0},
    "autoguiado_eur_por_cv": 0.0, "autoguiado_eur_fijo": 0.0,
}

@st.cache_data(ttl=60)
def get_coeficientes_cached(env_key: str):
    creds = None if env_key == "cloud" else CREDS
    coefs = google_drive_manager.leer_coeficientes(creds) or {}
    merged = dict(DEFAULT_COEFS)
    for k, v in coefs.items():
        if k == "neumaticos" and isinstance(v, dict):
            merged["neumaticos"].update(v)
        else: merged[k] = v
    return merged

# ------------------------------------------------------------
# HELPERS FOTOS (Tus originales)
# ------------------------------------------------------------
def _fotos_to_state(uploaded_files):
    return [{"name": f.name, "type": f.type, "data": f.getvalue()} for f in uploaded_files]

def _state_to_pil_images(fotos_state):
    return [Image.open(io.BytesIO(item["data"])) for item in fotos_state]

class InMemoryUpload(io.BytesIO):
    def __init__(self, data, name="foto.jpg", mime="image/jpeg"):
        super().__init__(data)
        self.name, self.type = name, mime

def _state_to_uploadlike(fotos_state):
    return [InMemoryUpload(x["data"], x["name"], x["type"]) for x in fotos_state]

# ------------------------------------------------------------
# LÓGICA DE TASACIÓN (Restaurada 100%)
# ------------------------------------------------------------
def _parse_float(value: Any) -> float:
    try: return float(str(value).replace(",", ".").strip())
    except: return 0.0

def fmt_eur(x: Optional[float]) -> str:
    if x is None: return "—"
    return f"{x:,.0f} €".replace(",", "X").replace(".", ",").replace("X", ".")

def calcular_ajustes_extras(draft: Dict[str, Any], coefs: Dict[str, Any]) -> Tuple[float, List[Tuple[str, float]]]:
    cv = _parse_float(draft["cv"])
    kg = _parse_float(draft.get("kg_contrapesos", 0))
    vida_g = _parse_float(draft["vida_neum_grandes"])
    vida_p = _parse_float(draft["vida_neum_pequenos"])

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
        if v != 0: desglose.append(("Autoguiado", v)); total += v

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
    lines = ["[EXTRAS / AJUSTES (APARTE)]"]
    for concepto, importe in items:
        sign = "+" if importe >= 0 else "-"
        lines.append(f"- {concepto}: {sign}{fmt_eur(abs(importe))}")
    lines.append(f"- TOTAL EXTRAS/APARTADOS: {fmt_eur(total_ajustes)}")
    return "\n".join(lines)

def parse_resultado_final(text: str) -> Dict[str, float]:
    out = {}
    m = re.search(r"(?is)BLOQUE\s*:\s*RESULTADO_FINAL\s*(.*?)(?:\n\s*BLOQUE|$)", text)
    block = m.group(1) if m else ""
    keys = ["VALOR_BASE", "AJUSTE_HORAS_%", "AJUSTE_ESTADO_%", "VALOR_MERCADO", "PRECIO_VENTA", "PRECIO_COMPRA"]
    for k in keys:
        found = re.search(rf"(?im)^\s*-?\s*{re.escape(k)}\s*:\s*([\-]?\d+)", block)
        if found: out[k] = float(found.group(1))
    return out

# ------------------------------------------------------------
# MAIN APP
# ------------------------------------------------------------
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    # Vista simple de acceso
    vendedores = google_drive_manager.leer_vendedores(CREDS) or []
    v_sel = st.selectbox("Selecciona tu nombre:", [""] + vendedores)
    if st.button("Entrar") and v_sel:
        st.session_state.logged_in = True
        st.session_state.vendedor = v_sel
        st.rerun()
    st.stop()

ocultar_chrome_streamlit()
COEFS = get_coeficientes_cached(ENV_KEY)

# GPS
loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = location_manager.codificar_coordenadas(loc["coords"]["latitude"], loc["coords"]["longitude"]) if loc else "UBICACIÓN NO DETECTADA"

# Session State
if "draft" not in st.session_state:
    st.session_state.draft = {
        "marca": "Valtra", "modelo": "", "anio": "", "horas": "", "cv": "",
        "kg_contrapesos": "0", "vida_neum_grandes": "", "vida_neum_pequenos": "",
        "obs": "", "fotos_state": [], "extra_pala": False, "extra_anclajes_pala": False,
        "extra_tripuntal_del": False, "extra_tdf_del": False, "extra_compresor": False, "extra_autoguiado": False
    }

# FORMULARIO
if "result" not in st.session_state:
    st.subheader("Datos del Peritaje")
    
    fotos_up = st.file_uploader("Subir fotos (mínimo 4)", accept_multiple_files=True, type=["jpg", "jpeg", "png"])
    if fotos_up: st.session_state.draft["fotos_state"] = _fotos_to_state(fotos_up)
    
    with st.form("form_peritaje"):
        c1, c2 = st.columns(2)
        marca = c1.text_input("Marca *", st.session_state.draft["marca"])
        modelo = c2.text_input("Modelo *", st.session_state.draft["modelo"])
        anio = c1.text_input("Año *", st.session_state.draft["anio"])
        horas = c2.text_input("Horas *", st.session_state.draft["horas"])
        cv = c1.text_input("CV *", st.session_state.draft["cv"])
        kg = c2.text_input("Kg contrapesos", st.session_state.draft["kg_contrapesos"])
        
        obs = st.text_area("Observaciones", st.session_state.draft["obs"])
        
        st.markdown("#### Extras")
        e1, e2, e3 = st.columns(3)
        pala = e1.checkbox("Pala", st.session_state.draft["extra_pala"])
        anclajes = e1.checkbox("Anclajes", st.session_state.draft["extra_anclajes_pala"])
        trip = e2.checkbox("Tripuntal", st.session_state.draft["extra_tripuntal_del"])
        tdf = e2.checkbox("TDF", st.session_state.draft["extra_tdf_del"])
        comp = e3.checkbox("Compresor", st.session_state.draft["extra_compresor"])
        auto = e3.checkbox("Autoguiado", st.session_state.draft["extra_autoguiado"])

        st.markdown("#### Neumáticos")
        n1, n2 = st.columns(2)
        opc_v = [""] + [str(x) for x in range(0, 101, 20)]
        v_g = n1.selectbox("Vida Grandes % *", opc_v)
        v_p = n2.selectbox("Vida Pequeños % *", opc_v)

        if st.form_submit_button("🚀 INICIAR TASACIÓN"):
            # Guardar en draft para no perder nada
            d = st.session_state.draft
            d.update({"marca": marca, "modelo": modelo, "anio": anio, "horas": horas, "cv": cv, 
                      "kg_contrapesos": kg, "obs": obs, "extra_pala": pala, "extra_anclajes_pala": anclajes,
                      "extra_tripuntal_del": trip, "extra_tdf_del": tdf, "extra_compresor": comp, 
                      "extra_autoguiado": auto, "vida_neum_grandes": v_g, "vida_neum_pequenos": v_p})
            
            if not (marca and modelo and anio and horas and cv and v_g and v_p) or len(d["fotos_state"]) < 4:
                st.error("Faltan campos o fotos.")
            else:
                with st.spinner("Procesando..."):
                    try:
                        total_aj, items_aj = calcular_ajustes_extras(d, COEFS)
                        inf = ia_engine.realizar_peritaje(st.session_state.vertex_client, marca, modelo, anio, horas, obs, _state_to_uploadlike(d["fotos_state"]))
                        
                        st.session_state.result = {
                            "informe_final": inf,
                            "base_dict": parse_resultado_final(inf),
                            "extras_total": total_aj,
                            "bloque_extras": bloque_extras_texto(total_aj, items_aj),
                            "html": html_generator.generar_informe_html(marca, modelo, inf, _state_to_pil_images(d["fotos_state"]), ""),
                            "nombre_archivo": f"Tasacion_{marca}_{modelo}.html"
                        }
                        st.rerun()
                    except Exception as e: st.error(f"Error: {e}")

# RESULTADOS
else:
    res = st.session_state.result
    base = res["base_dict"]
    
    st.markdown("### 🤖 Análisis IA")
    st.markdown(f'<div class="card">{res["informe_final"]}</div>', unsafe_allow_html=True)
    
    st.markdown("### Precios Base")
    c1, c2, c3 = st.columns(3)
    c1.metric("MERCADO", fmt_eur(base.get("VALOR_MERCADO")))
    c2.metric("VENTA", fmt_eur(base.get("PRECIO_VENTA")))
    c3.metric("COMPRA", fmt_eur(base.get("PRECIO_COMPRA")))

    st.markdown("### Extras / Ajustes")
    # AQUI ESTÁ EL CAMBIO DE TIPOGRAFÍA:
    st.markdown(f'<div class="extras-container">{res["bloque_extras"]}</div>', unsafe_allow_html=True)

    if st.button("↩️ VOLVER"):
        st.session_state.pop("result")
        st.rerun()
