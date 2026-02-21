import streamlit as st
import os
import io
import re
import base64
import requests  # <-- Añadido para Sheets
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
# UI GLOBAL (OCULTAR CHROME + BRANDING)
# ------------------------------------------------------------
def ocultar_chrome_streamlit():
    st.markdown(
        """
<style>
/* Fuente general para toda la app */
html, body, [class*="css"] {
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
}

.block-container {
    max-width: 1100px;
    padding-top: 1.8rem;
    padding-bottom: 2.2rem;
}

/* Ocultar cromos Streamlit */
#MainMenu, footer, header {visibility: hidden;}

/* Hero / cabecera */
.hero {
  background: linear-gradient(
    135deg,
    rgba(63,163,77,.18),
    rgba(125,186,58,.18)
  );
  border: 1px solid rgba(47,111,62,.25);
  border-radius: 22px;
  padding: 18px;
  margin-bottom: 18px;
}
.hero h1 { margin: 0; color: #1F3D2B; }
.hero p { margin: 0; color: #4F6F5B; }

/* Cards */
.card {
  background: #F3F8F3;
  border: 1px solid rgba(47,111,62,.18);
  border-radius: 18px;
  padding: 16px;
}

/* EL AJUSTE DE TIPOGRAFÍA: Caja de extras limpia */
.extras-container {
    background-color: #ffffff;
    border: 1px solid rgba(47,111,62,.25);
    border-radius: 14px;
    padding: 18px;
    color: #1F3D2B;
    line-height: 1.6;
    white-space: pre-wrap;
    font-size: 0.95rem;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

/* Inputs */
div[data-baseweb="input"] input,
div[data-baseweb="textarea"] textarea {
  border-radius: 14px !important;
  border: 1px solid rgba(47,111,62,.25) !important;
}

/* Botón principal */
.stButton > button {
  background: linear-gradient(135deg, #3FA34D, #7DBA3A) !important;
  color: #ffffff !important;
  border-radius: 14px !important;
  border: none !important;
  font-weight: 700 !important;
  padding: 0.7rem 1.1rem !important;
}
.stButton > button:hover {
  filter: brightness(1.05);
  transform: translateY(-1px);
}

.pill {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(63,163,77,.15);
  border: 1px solid rgba(47,111,62,.25);
  font-size: .85rem;
  color: #1F3D2B;
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
# CREDS
# ------------------------------------------------------------
def get_creds():
    if ES_CLOUD_RUN: 
        return None
    try:
        return dict(st.secrets["google"])
    except Exception:
        st.error("Faltan secrets locales: st.secrets['google'].")
        st.stop()


CREDS = get_creds()

# ------------------------------------------------------------
# COEFICIENTES (Drive)
# ------------------------------------------------------------
DEFAULT_COEFS = {
    "pala_eur_por_cv": 41.6, "anclajes_eur_por_cv": 16.6,
    "tripuntal_eur_por_cv": 20.8, "tripuntal_tdf_eur_por_cv": 25.0,
    "compresor_eur_fijo": 1000.0, "contrapesos_eur_por_kg": 1.0,
    "neumaticos": {"max_grandes_eur_por_cv": 50.0, "max_pequenos_eur_por_cv": 20.0},
    "autoguiado_eur_por_cv": 0.0, "autoguiado_eur_fijo": 0.0,
}

@st.cache_data(ttl=60, show_spinner=False)
def get_coeficientes_cached(env_key: str) -> Dict[str, Any]:
    creds = None if env_key == "cloud" else CREDS
    try:
        coefs = google_drive_manager.leer_coeficientes(creds)
        if not coefs:
            return DEFAULT_COEFS
        # merge tolerante
        merged = dict(DEFAULT_COEFS)
        for k, v in coefs.items():
            if k == "neumaticos" and isinstance(v, dict):
                merged_neu = dict(merged.get("neumaticos", {}))
                merged_neu.update(v)
                merged["neumaticos"] = merged_neu
            else:
                merged[k] = v
        return merged
    except Exception:
        return DEFAULT_COEFS

def invalidate_coef_cache():
    try:
        get_coeficientes_cached.clear()
    except Exception:
        pass

COEFS = get_coeficientes_cached(ENV_KEY)

# ------------------------------------------------------------
# VENDEDORES (Drive)
# ------------------------------------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def get_vendedores_cached(env_key: str) -> List[str]:
    creds = None if env_key == "cloud" else CREDS
    return google_drive_manager.leer_vendedores(creds) or []

def invalidate_vendedores_cache():
    try:
        get_vendedores_cached.clear()
    except Exception:
        pass


# ------------------------------------------------------------
# HELPERS FOTOS
# ------------------------------------------------------------
def _fotos_to_state(uploaded_files) -> List[Dict[str, Any]]:
    """
    Procesa las fotos NADA MÁS ELEGIRLAS para que 
    la RAM de Cloud Run no sufra.
    """
    state = []
    for f in uploaded_files or []:
        data_optimizada = ia_engine._normalizar_imagen_a_jpeg_bytes(
            f,
            max_side=800,
            quality=60
        )
        state.append({
            "name": getattr(f, "name", "foto.jpg"),
            "type": "image/jpeg",
            "data": data_optimizada
        })
    return state


def _state_to_pil_images(fotos_state) -> List[Image.Image]:
    return [Image.open(io.BytesIO(item["data"])) for item in fotos_state or []]


class InMemoryUpload(io.BytesIO):
    def __init__(self, data: bytes, name: str = "foto.jpg", mime: str = "image/jpeg"):
        super().__init__(data)
        self.name, self.type = name, mime


def _state_to_uploadlike(fotos_state) -> List[InMemoryUpload]:
    return [InMemoryUpload(x["data"], x.get("name", "foto.jpg"), x.get("type", "image/jpeg")) for x in (fotos_state or [])]


# ------------------------------------------------------------
# FORMATO / PARSEO
# ------------------------------------------------------------
def _parse_float(x: str) -> float:
    return float(str(x).replace(",", ".").strip())

def fmt_eur(x: Optional[int]) -> str:
    if x is None:
        return "N/D"
    try:
        return f"{int(x):,} €".replace(",", ".")
    except Exception:
        return "N/D"

def validar_datos(d: Dict[str, Any]) -> List[str]:
    errores = []
    for k in ["marca", "modelo", "anio", "horas", "cv", "vida_neum_grandes", "vida_neum_pequenos"]:
        if not str(d.get(k, "")).strip():
            errores.append(f"Falta el campo obligatorio: {k}")

    try:
        _ = _parse_float(d.get("horas", "0"))
    except Exception:
        errores.append("Horas inválidas.")
    try:
        _ = _parse_float(d.get("cv", "0"))
    except Exception:
        errores.append("CV inválido.")

    # Fotos mínimo 4 (como el UI)
    fotos = d.get("fotos_state") or []
    if len(fotos) < 4:
        errores.append("Mínimo 4 fotos.")
    return errores


def parse_resultado_final(texto: str) -> Dict[str, Any]:
    """
    Extrae (si existe) el bloque RESULTADO_FINAL y devuelve dict con keys:
    VALOR_MERCADO, PRECIO_VENTA, PRECIO_COMPRA
    """
    if not texto:
        return {}
    m = re.search(r"BLOQUE:\s*RESULTADO_FINAL(.*?)(?:BLOQUE:|$)", texto, flags=re.S | re.I)
    if not m:
        return {}
    block = m.group(1).strip()

    def get_int(key):
        mm = re.search(rf"{re.escape(key)}\s*:\s*([0-9\.\,]+)", block)
        if not mm:
            return None
        return int(float(mm.group(1).replace(".", "").replace(",", ".")))

    return {
        "VALOR_MERCADO": get_int("VALOR_MERCADO"),
        "PRECIO_VENTA": get_int("PRECIO_VENTA"),
        "PRECIO_COMPRA": get_int("PRECIO_COMPRA"),
    }


# ------------------------------------------------------------
# EXTRAS / AJUSTES
# ------------------------------------------------------------
def calcular_ajustes_extras(d: Dict[str, Any], coefs: Dict[str, Any]) -> Tuple[float, List[Tuple[str, float]]]:
    items = []
    cv = _parse_float(d.get("cv", "0") or "0")
    kg = _parse_float(d.get("kg_contrapesos", "0") or "0")

    if d.get("extra_pala"):
        items.append(("Pala", cv * float(coefs.get("pala_eur_por_cv", 0))))
    if d.get("extra_anclajes_pala"):
        items.append(("Anclajes pala", cv * float(coefs.get("anclajes_eur_por_cv", 0))))
    if d.get("extra_tripuntal_del"):
        items.append(("Tripuntal del.", cv * float(coefs.get("tripuntal_eur_por_cv", 0))))
    if d.get("extra_tdf_del"):
        items.append(("Tripuntal+TDF del.", cv * float(coefs.get("tripuntal_tdf_eur_por_cv", 0))))
    if d.get("extra_compresor"):
        items.append(("Compresor", float(coefs.get("compresor_eur_fijo", 0))))
    if d.get("extra_autoguiado"):
        items.append(("Autoguiado", float(coefs.get("autoguiado_eur_fijo", 0))))

    if kg > 0:
        items.append(("Contrapesos", kg * float(coefs.get("contrapesos_eur_por_kg", 0))))

    # Neumáticos (vida %)
    vg = int(str(d.get("vida_neum_grandes", "0") or "0"))
    vp = int(str(d.get("vida_neum_pequenos", "0") or "0"))

    neu = coefs.get("neumaticos", {}) if isinstance(coefs.get("neumaticos", {}), dict) else {}
    max_gr = float(neu.get("max_grandes_eur_por_cv", 0))
    max_pe = float(neu.get("max_pequenos_eur_por_cv", 0))

    # Penaliza en función de la vida que falta (100% -> 0 penalización, 0% -> -max)
    items.append(("Neumáticos grandes (vida)", -cv * max_gr * (1 - vg / 100.0)))
    items.append(("Neumáticos pequeños (vida)", -cv * max_pe * (1 - vp / 100.0)))

    total = sum(x[1] for x in items)
    return total, items


def bloque_extras_texto(total: float, items: List[Tuple[str, float]]) -> str:
    lines = []
    lines.append("[EXTRAS / AJUSTES (APARTE)]")
    for name, val in items:
        s = f"{val:,.0f} €".replace(",", ".")
        sign = "+" if val >= 0 else ""
        lines.append(f"- {name}: {sign}{s}")
    lines.append(f"- TOTAL EXTRAS/APARTADOS: {total:,.0f} €".replace(",", "."))
    return "\n".join(lines)


# ------------------------------------------------------------
# INIT STATE
# ------------------------------------------------------------
ocultar_chrome_streamlit()

if "draft" not in st.session_state:
    st.session_state["draft"] = {
        "marca": "", "modelo": "", "anio": "", "horas": "", "cv": "",
        "kg_contrapesos": "", "obs": "",
        "extra_pala": False, "extra_anclajes_pala": False,
        "extra_tripuntal_del": False, "extra_tdf_del": False,
        "extra_compresor": False, "extra_autoguiado": False,
        "vida_neum_grandes": "", "vida_neum_pequenos": "",
        "fotos_state": [],
    }

if "vertex_client" not in st.session_state:
    st.session_state["vertex_client"] = ia_engine.conectar_vertex(CREDS)

# Ubicación
texto_ubicacion = ""
try:
    # Si tienes geolocalización en front
    geo = get_geolocation()
    if geo and isinstance(geo, dict):
        texto_ubicacion = location_manager.ubicacion_a_texto(geo)
    else:
        texto_ubicacion = location_manager.obtener_texto_ubicacion()
except Exception:
    texto_ubicacion = ""


# Vendedor (selector)
vendedores = get_vendedores_cached(ENV_KEY)
if "vendedor" not in st.session_state:
    st.session_state["vendedor"] = vendedores[0] if vendedores else ""

st.markdown("### 👤 Vendedor")
st.session_state["vendedor"] = st.selectbox(
    "Selecciona vendedor",
    options=vendedores if vendedores else ["(sin vendedores)"],
    index=(vendedores.index(st.session_state["vendedor"]) if (vendedores and st.session_state["vendedor"] in vendedores) else 0),
)

OPC_VIDA = [""] + [str(x) for x in range(0, 101, 20)]

# ------------------------------------------------------------
# FORMULARIO / RESULTADOS
# ------------------------------------------------------------
if "result" not in st.session_state:
    st.subheader("Datos del Peritaje")
    
    fotos_up = st.file_uploader(
        "Subir fotos tractor (mínimo 4)", 
        accept_multiple_files=True, 
        key="uploader_fotos"
    )
    
    if fotos_up:
        valid_types = ["image/jpeg", "image/png", "image/jpg"]
        fotos_validas = [f for f in fotos_up if f.type in valid_types]
        
        if len(fotos_validas) < len(fotos_up):
            st.warning("⚠️ Algunos archivos no son imágenes válidas y han sido omitidos.")
            
        st.session_state["draft"]["fotos_state"] = _fotos_to_state(fotos_validas)
    
    with st.form("form_peritaje"):
        c1, c2 = st.columns(2)
        marca = c1.text_input("Marca *", st.session_state["draft"]["marca"])
        modelo = c2.text_input("Modelo *", st.session_state["draft"]["modelo"])
        anio = c1.text_input("Año *", st.session_state["draft"]["anio"])
        horas = c2.text_input("Horas *", st.session_state["draft"]["horas"])
        cv = c1.text_input("CV *", st.session_state["draft"]["cv"])
        kg = c2.text_input("Kg contrapesos", st.session_state["draft"]["kg_contrapesos"])
        obs = st.text_area("Observaciones adicionales", st.session_state["draft"]["obs"])
        
        st.markdown("#### Extras del tractor")
        e1, e2, e3 = st.columns(3)
        pala = e1.checkbox("Pala", st.session_state["draft"]["extra_pala"])
        anclajes = e1.checkbox("Anclajes pala", st.session_state["draft"]["extra_anclajes_pala"])
        trip = e2.checkbox("Tripuntal del.", st.session_state["draft"]["extra_tripuntal_del"])
        tdf = e2.checkbox("TDF del.", st.session_state["draft"]["extra_tdf_del"])
        comp = e3.checkbox("Compresor", st.session_state["draft"]["extra_compresor"])
        auto = e3.checkbox("Autoguiado", st.session_state["draft"]["extra_autoguiado"])

        n1, n2 = st.columns(2)
        vg = n1.selectbox("Vida Neum. Grandes % *", OPC_VIDA, index=OPC_VIDA.index(str(st.session_state["draft"]["vida_neum_grandes"])) if str(st.session_state["draft"]["vida_neum_grandes"]) in OPC_VIDA else 0)
        vp = n2.selectbox("Vida Neum. Pequeños % *", OPC_VIDA, index=OPC_VIDA.index(str(st.session_state["draft"]["vida_neum_pequenos"])) if str(st.session_state["draft"]["vida_neum_pequenos"]) in OPC_VIDA else 0)

        if st.form_submit_button("🚀 INICIAR TASACIÓN Y GUARDAR", use_container_width=True):
            d = st.session_state["draft"]
            d.update({"marca":marca,"modelo":modelo,"anio":anio,"horas":horas,"cv":cv,"kg_contrapesos":kg,"obs":obs,"extra_pala":pala,"extra_anclajes_pala":anclajes,"extra_tripuntal_del":trip,"extra_tdf_del":tdf,"extra_compresor":comp,"extra_autoguiado":auto,"vida_neum_grandes":vg,"vida_neum_pequenos":vp})
            err = validar_datos(d)
            if err: 
                for e in err: st.error(e)
            else:
                with st.spinner("Procesando..."):
                    try:
                        total_aj, items_aj = calcular_ajustes_extras(d, COEFS)
                        bloque_extras = bloque_extras_texto(total_aj, items_aj)
                        inf = ia_engine.realizar_peritaje(st.session_state.vertex_client, marca, modelo, anio, horas, obs, _state_to_uploadlike(d["fotos_state"]))
                        base_dict = parse_resultado_final(inf)
                        ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")
                        html = html_generator.generar_informe_html(marca, modelo, inf, d["fotos_state"], ref_b64,vendedor=st.session_state.get("vendedor", ""))
                        
                        # Guardar en Drive
                        id_drive = google_drive_manager.subir_informe(None if ES_CLOUD_RUN else CREDS, f"Tasacion_{marca}_{modelo}.html", html, folder_name=st.session_state["vendedor"])
                        
                        # --- NUEVO: GUARDAR EN GOOGLE SHEETS ---
                        try:
                            url_sheets = "https://script.google.com/macros/s/AKfycbw9hur2xbWaEetwNyl0U0_QaPSiFcZsbXITDJ-mYoswp5HzPxr1LFAwPfdNqSyAVl3h/exec"
                            requests.post(url_sheets, json={
                                "vendedor": st.session_state["vendedor"],
                                "marca": marca, "modelo": modelo, "horas": horas, "caballos": cv,
                                "precioMercado": int((base_dict.get("VALOR_MERCADO") or 0) + total_aj),
                                "precioVenta": int((base_dict.get("PRECIO_VENTA") or 0) + total_aj),
                                "precioCompra": int((base_dict.get("PRECIO_COMPRA") or 0) + total_aj)
                            })
                            st.toast("✅ Registro en Excel OK")
                        except Exception as e_sheet:
                            st.warning(f"Error al actualizar Excel: {e_sheet}")

                        st.session_state["result"] = {"informe_final": inf, "html": html, "nombre_archivo": f"Tasacion_{marca}_{modelo}.html", "id_archivo_drive": id_drive, "base_dict": base_dict, "extras_total": total_aj, "bloque_extras": bloque_extras}
                        st.rerun()
                    except Exception as e: 
                        st.error(f"Error en el proceso: {e}")

# --- PÁGINA DE RESULTADOS ---
else:
    res = st.session_state["result"]
    base = res.get("base_dict", {})
    
    if res.get("id_archivo_drive"): 
        st.success("✅ Peritaje archivado en Drive.")
    else: 
        st.warning("⚠️ No se pudo archivar en Drive (revisar permisos).")

    st.markdown("### 🤖 Resultado del Análisis (IA)")
    st.markdown(f'<div class="card">{res["informe_final"]}</div>', unsafe_allow_html=True)
    
    st.markdown("### Precios base del tasador (RESULTADO_FINAL)")
    c1, c2, c3 = st.columns(3)
    c1.metric("VALOR_MERCADO", fmt_eur(base.get("VALOR_MERCADO")))
    c2.metric("PRECIO_VENTA", fmt_eur(base.get("PRECIO_VENTA")))
    c3.metric("PRECIO_COMPRA", fmt_eur(base.get("PRECIO_COMPRA")))

    st.markdown("### Extras / Ajustes (APARTE)")
    st.markdown(f'<div class="extras-container">{res["bloque_extras"]}</div>', unsafe_allow_html=True)

    if base.get("VALOR_MERCADO"):
        st.markdown("### Referencia (base + extras) — solo orientativo")
        r1, r2, r3 = st.columns(3)
        r1.metric("Mercado + Extras", fmt_eur(base["VALOR_MERCADO"] + res["extras_total"]))
        r2.metric("Venta + Extras", fmt_eur(base["PRECIO_VENTA"] + res["extras_total"]))
        r3.metric("Compra + Extras", fmt_eur(base["PRECIO_COMPRA"] + res["extras_total"]))

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        st.download_button(label="📄 DESCARGAR HTML", data=res["html"], file_name=res["nombre_archivo"], mime="text/html", use_container_width=True)
    with col_btn2:
        if st.button("↩️ VOLVER A TASAR (mantener datos y fotos)", use_container_width=True):
            st.session_state.pop("result", None); st.rerun()