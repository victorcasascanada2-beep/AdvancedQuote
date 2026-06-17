# app.py — Tasador Agrícola Noroeste (VERSIÓN INTEGRAL COMPROBADA CON SHEETS)
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
    coefs = google_drive_manager.leer_coeficientes(creds) or {}
    merged = dict(DEFAULT_COEFS)
    for k, v in coefs.items():
        if k == "neumaticos" and isinstance(v, dict):
            merged_neu = dict(DEFAULT_COEFS["neumaticos"])
            merged_neu.update(v)
            merged["neumaticos"] = merged_neu
        else:
            merged[k] = v
    return merged

def invalidate_coef_cache():
    try:
        get_coeficientes_cached.clear()
    except:
        pass

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
    except:
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
        # Redimensionamos AL VUELO usando la lógica de ia_engine
        # max_side=800 y quality=60 para máxima ligereza
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
# VALIDACIÓN / PARSEO
# ------------------------------------------------------------
def _is_blank(s: Any) -> bool:
    return s is None or str(s).strip() == ""

def _parse_float(value: Any) -> float:
    return float(str(value).replace(",", ".").strip())

def validar_datos(draft: Dict[str, Any]) -> List[str]:
    errores = []
    for campo in ["marca", "modelo", "anio", "horas", "cv"]:
        if _is_blank(draft.get(campo, "")):
            errores.append(f"El campo **{campo}** es obligatorio.")
    anio = str(draft.get("anio", "")).strip()
    if anio and (not anio.isdigit() or len(anio) != 4):
        errores.append("El campo **año** debe ser un número de 4 dígitos (ej: 2022).")
    if len(draft.get("fotos_state") or []) < 4:
        errores.append("Debes subir **mínimo 4 fotos** para tasar.")
    if _is_blank(draft.get("vida_neum_grandes", "")):
        errores.append("Selecciona la **vida útil neumáticos grandes (%)**.")
    if _is_blank(draft.get("vida_neum_pequenos", "")):
        errores.append("Selecciona la **vida útil neumáticos pequeños (%)**.")
    return errores

def _find_block_resultado_final(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(?is)BLOQUE\s*:\s*RESULTADO_FINAL\s*(.*)", text)
    if not m:
        return ""
    tail = m.group(1)
    m2 = re.search(r"(?is)\n\s*BLOQUE\s*:\s*", tail)
    return tail[: m2.start()] if m2 else tail

def _extract_int_line(block: str, key: str) -> Optional[float]:
    if not block:
        return None
    m = re.search(rf"(?im)^\s*-?\s*{re.escape(key)}\s*:\s*([\-]?\d+)\s*$", block)
    if not m:
        return None
    try:
        return float(m.group(1))
    except:
        return None

def parse_resultado_final(text: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    block = _find_block_resultado_final(text)
    keys = ["VALOR_BASE", "AJUSTE_HORAS_%", "AJUSTE_ESTADO_%", "VALOR_MERCADO", "PRECIO_VENTA", "PRECIO_COMPRA"]
    for k in keys:
        v = _extract_int_line(block, k)
        if v is not None:
            out[k] = v

    vb = out.get("VALOR_BASE")
    if out.get("VALOR_MERCADO") is None and vb is not None:
        ah = out.get("AJUSTE_HORAS_%", 0.0)
        ae = out.get("AJUSTE_ESTADO_%", 0.0)
        out["VALOR_MERCADO"] = float(round(vb * (1.0 + ah / 100.0) * (1.0 + ae / 100.0)))

    vm = out.get("VALOR_MERCADO")
    if vm:
        if out.get("PRECIO_VENTA") is None:
            out["PRECIO_VENTA"] = float(round(vm * 0.92))
        if out.get("PRECIO_COMPRA") is None:
            out["PRECIO_COMPRA"] = float(round(vm * 0.80))

    return out

# ------------------------------------------------------------
# MOTOR AJUSTES
# ------------------------------------------------------------
def calcular_ajustes_extras(draft: Dict[str, Any], coefs: Dict[str, Any]) -> Tuple[float, List[Tuple[str, float]]]:
    cv = _parse_float(draft["cv"])
    kg = _parse_float(draft.get("kg_contrapesos", 0) or 0)
    vida_g, vida_p = float(draft["vida_neum_grandes"]), float(draft["vida_neum_pequenos"])
    desglose, total = [], 0.0

    pala, anclajes = bool(draft.get("extra_pala")), bool(draft.get("extra_anclajes_pala"))
    trip, tdf = bool(draft.get("extra_tripuntal_del")), bool(draft.get("extra_tdf_del"))
    comp, autog = bool(draft.get("extra_compresor")), bool(draft.get("extra_autoguiado"))

    if pala:
        v = float(coefs.get("pala_eur_por_cv", 0.0)) * cv
        desglose.append(("Pala usada", v))
        total += v
        anclajes = False
    if anclajes:
        v = float(coefs.get("anclajes_eur_por_cv", 0.0)) * cv
        desglose.append(("Anclajes de pala", v))
        total += v
    if tdf:
        trip = True
        v = float(coefs.get("tripuntal_tdf_eur_por_cv", 0.0)) * cv
        desglose.append(("Tripuntal + TDF del.", v))
        total += v
    elif trip:
        v = float(coefs.get("tripuntal_eur_por_cv", 0.0)) * cv
        desglose.append(("Tripuntal del.", v))
        total += v
    if comp:
        v = float(coefs.get("compresor_eur_fijo", 0.0))
        desglose.append(("Compresor aire", v))
        total += v
    if autog:
        v = (float(coefs.get("autoguiado_eur_por_cv", 0.0)) * cv) + float(coefs.get("autoguiado_eur_fijo", 0.0))
        if v != 0:
            desglose.append(("Autoguiado", v))
            total += v
    if kg > 0:
        v = float(coefs.get("contrapesos_eur_por_kg", 0.0)) * kg
        desglose.append((f"Contrapesos ({kg:.0f} kg)", v))
        total += v

    neu = coefs.get("neumaticos", {})
    penal_g = (1.0 - (vida_g / 100.0)) * float(neu.get("max_grandes_eur_por_cv", 50.0)) * cv
    penal_p = (1.0 - (vida_p / 100.0)) * float(neu.get("max_pequenos_eur_por_cv", 20.0)) * cv
    if penal_g > 0:
        desglose.append((f"Neumáticos grandes (vida {vida_g:.0f}%)", -penal_g))
        total -= penal_g
    if penal_p > 0:
        desglose.append((f"Neumáticos pequeños (vida {vida_p:.0f}%)", -penal_p))
        total -= penal_p

    return total, desglose

def fmt_eur(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{x:,.0f} €".replace(",", "X").replace(".", ",").replace("X", ".")

def bloque_extras_texto(total_ajustes: float, items: List[Tuple[str, float]]) -> str:
    lines = ["[EXTRAS / AJUSTES (APARTE)]"]
    for concepto, importe in items:
        sign = "+" if importe >= 0 else "-"
        lines.append(f"- {concepto}: {sign}{fmt_eur(abs(importe))}")
    lines.append(f"- TOTAL EXTRAS/APARTADOS: {fmt_eur(total_ajustes)}")
    return "\n".join(lines)

# ------------------------------------------------------------
# VISTA ACCESO
# ------------------------------------------------------------
def vista_acceso():
    if os.path.exists("Transparente.png"):
        st.image("Transparente.png", width=320)
    else:
        st.title("🚜 Agrícola Noroeste")
    st.subheader("Acceso de Tasadores")

    c1, c2 = st.columns([3, 1])
    with c2:
        if st.button("🔄 Refrescar", use_container_width=True):
            invalidate_vendedores_cache()
            st.rerun()

    vendedores = get_vendedores_cached(ENV_KEY)
    t1, t2 = st.tabs(["Seleccionar", "Registrar nuevo"])
    with t1:
        with st.form("form_sel"):
            v_sel = st.selectbox("Selecciona tu nombre:", [""] + vendedores)
            if st.form_submit_button("Entrar", use_container_width=True) and v_sel:
                st.session_state["logged_in"] = True
                st.session_state["vendedor"] = v_sel
                st.rerun()
    with t2:
        with st.form("form_reg", clear_on_submit=True):
            nuevo = st.text_input("Nombre y Apellido del nuevo tasador:")
            if st.form_submit_button("Registrar y Entrar", use_container_width=True) and nuevo.strip():
                google_drive_manager.actualizar_vendedores(None if ES_CLOUD_RUN else CREDS, vendedores + [nuevo.strip()])
                invalidate_vendedores_cache()
                st.session_state["logged_in"] = True
                st.session_state["vendedor"] = nuevo.strip()
                st.rerun()

# ------------------------------------------------------------
# MAIN LOGIN
# ------------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    vista_acceso()
    st.stop()

ocultar_chrome_streamlit()

# ------------------------------------------------------------
# HEADER (Logo + Controles)
# ------------------------------------------------------------
col_logo, col_controls = st.columns([6, 2])
with col_logo:
    if os.path.exists("Transparente.png"):
        st.image("Transparente.png", width=220)
    else:
        st.markdown("### Agrícola Noroeste")
    st.markdown(f"### 🤝🚜 {st.session_state.get('vendedor','')}")
with col_controls:
    if st.button("♻️ Recargar coeficientes", use_container_width=True):
        invalidate_coef_cache()
        st.rerun()
    if st.button("Salir", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.divider()
COEFS = get_coeficientes_cached(ENV_KEY)

# Vertex AI
if "vertex_client" not in st.session_state:
    st.session_state.vertex_client = ia_engine.conectar_vertex(None if ES_CLOUD_RUN else CREDS)

# GPS
loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = location_manager.codificar_coordenadas(loc["coords"]["latitude"], loc["coords"]["longitude"]) if loc and "coords" in loc else "UBICACIÓN NO DETECTADA"

# DRAFT SETUP
st.session_state.setdefault(
    "draft",
    {
        "marca": "John Deere",
        "modelo": "6175M",
        "anio": "2018",
        "horas": "9988",
        "cv": "175",
        "kg_contrapesos": "0",
        "vida_neum_grandes": "",
        "vida_neum_pequenos": "",
        "obs": "",
        "fotos_state": [],
        "extra_pala": False,
        "extra_anclajes_pala": False,
        "extra_tripuntal_del": False,
        "extra_tdf_del": False,
        "extra_compresor": False,
        "extra_autoguiado": False
    }
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
        vg = n1.selectbox(
            "Vida Neum. Grandes % *",
            OPC_VIDA,
            index=OPC_VIDA.index(str(st.session_state["draft"]["vida_neum_grandes"])) if str(st.session_state["draft"]["vida_neum_grandes"]) in OPC_VIDA else 0
        )
        vp = n2.selectbox(
            "Vida Neum. Pequeños % *",
            OPC_VIDA,
            index=OPC_VIDA.index(str(st.session_state["draft"]["vida_neum_pequenos"])) if str(st.session_state["draft"]["vida_neum_pequenos"]) in OPC_VIDA else 0
        )

        if st.form_submit_button("🚀 INICIAR TASACIÓN Y GUARDAR", use_container_width=True):
            d = st.session_state["draft"]
            d.update({
                "marca": marca,
                "modelo": modelo,
                "anio": anio,
                "horas": horas,
                "cv": cv,
                "kg_contrapesos": kg,
                "obs": obs,
                "extra_pala": pala,
                "extra_anclajes_pala": anclajes,
                "extra_tripuntal_del": trip,
                "extra_tdf_del": tdf,
                "extra_compresor": comp,
                "extra_autoguiado": auto,
                "vida_neum_grandes": vg,
                "vida_neum_pequenos": vp
            })
            err = validar_datos(d)
            if err:
                for e in err:
                    st.error(e)
            else:
                with st.spinner("Procesando..."):
                    try:
                        total_aj, items_aj = calcular_ajustes_extras(d, COEFS)
                        bloque_extras = bloque_extras_texto(total_aj, items_aj)
                        inf = ia_engine.realizar_peritaje(
                            st.session_state.vertex_client,
                            marca,
                            modelo,
                            anio,
                            horas,
                            obs,
                            _state_to_uploadlike(d["fotos_state"])
                        )
                        base_dict = parse_resultado_final(inf)
                        ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")

                        html = html_generator.generar_informe_html(
                            marca,
                            modelo,
                            inf,
                            _state_to_pil_images(d["fotos_state"]),
                            ref_b64,
                            vendedor=st.session_state.get("vendedor", ""),
                            base_dict=base_dict,
                            extras_total=total_aj,
                            bloque_extras=bloque_extras,
                        )

                        # Guardar en Drive
                        id_drive = google_drive_manager.subir_informe(
                            None if ES_CLOUD_RUN else CREDS,
                            f"Tasacion_{marca}_{modelo}.html",
                            html,
                            folder_name=st.session_state["vendedor"]
                        )

                        # --- NUEVO: GUARDAR EN GOOGLE SHEETS ---
                        try:
                            url_sheets = "https://script.google.com/macros/s/AKfycbw9hur2xbWaEetwNyl0U0_QaPSiFcZsbXITDJ-mYoswp5HzPxr1LFAwPfdNqSyAVl3h/exec"
                            requests.post(url_sheets, json={
                                "vendedor": st.session_state["vendedor"],
                                "marca": marca,
                                "modelo": modelo,
                                "horas": horas,
                                "caballos": cv,
                                "precioMercado": int(base_dict.get("VALOR_MERCADO", 0) + total_aj),
                                "precioVenta": int(base_dict.get("PRECIO_VENTA", 0) + total_aj),
                                "precioCompra": int(base_dict.get("PRECIO_COMPRA", 0) + total_aj)
                            })
                            st.toast("✅ Registro en Excel OK")
                        except Exception as e_sheet:
                            st.warning(f"Error al actualizar Excel: {e_sheet}")

                        st.session_state["result"] = {
                            "informe_final": inf,
                            "html": html,
                            "nombre_archivo": f"Tasacion_{marca}_{modelo}.html",
                            "id_archivo_drive": id_drive,
                            "base_dict": base_dict,
                            "extras_total": total_aj,
                            "bloque_extras": bloque_extras
                        }
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
        st.download_button(
            label="📄 DESCARGAR HTML",
            data=res["html"],
            file_name=res["nombre_archivo"],
            mime="text/html",
            use_container_width=True
        )
    with col_btn2:
        if st.button("↩️ VOLVER A TASAR (mantener datos y fotos)", use_container_width=True):
            st.session_state.pop("result", None)
            st.rerun()
