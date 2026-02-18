# app.py — Tasador Agrícola Noroeste (COMPLETO, de cabo a rabo)
# - Mantiene tu lógica (IA/Drive/GPS/HTML)
# - Arregla la función de branding (indentación correcta)
# - Asegura que TODAS las funciones están definidas antes de usarse

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
# UI GLOBAL (OCULTAR CHROME + BRANDING)
# ------------------------------------------------------------
def ocultar_chrome_streamlit():
    st.markdown(
        """
<div class="hero">
  <h1>🌱 Tasación de maquinaria</h1>
  <p>Agrícola Noroeste · Valoración orientativa basada en estado, horas y mercado</p>
</div>

<style>
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
.hero h1 {
  margin: 0;
  color: #1F3D2B;
}
.hero p {
  margin: 0;
  color: #4F6F5B;
}

/* Cards */
.card {
  background: #F3F8F3;
  border: 1px solid rgba(47,111,62,.18);
  border-radius: 18px;
  padding: 16px;
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

/* Pills / badges */
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
""",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------
# CREDS
# ------------------------------------------------------------
def get_creds():
    """
    Cloud Run: None (ADC) y NO toca st.secrets nunca.
    Local: dict(st.secrets["google"]) (service account).
    """
    if ES_CLOUD_RUN:
        return None
    try:
        return dict(st.secrets["google"])
    except Exception:
        st.error("Faltan secrets locales: st.secrets['google'] (service account).")
        st.stop()


CREDS = get_creds()


# ------------------------------------------------------------
# COEFICIENTES (Drive)
# ------------------------------------------------------------
DEFAULT_COEFS = {
    "pala_eur_por_cv": 41.6,
    "anclajes_eur_por_cv": 16.6,
    "tripuntal_eur_por_cv": 20.8,
    "tripuntal_tdf_eur_por_cv": 25.0,
    "compresor_eur_fijo": 1000.0,
    "contrapesos_eur_por_kg": 1.0,
    "neumaticos": {
        "max_grandes_eur_por_cv": 50.0,
        "max_pequenos_eur_por_cv": 20.0,
    },
    "autoguiado_eur_por_cv": 0.0,
    "autoguiado_eur_fijo": 0.0,
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
    except Exception:
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
    except Exception:
        pass


# ------------------------------------------------------------
# HELPERS FOTOS (persistentes en session_state)
# ------------------------------------------------------------
def _fotos_to_state(uploaded_files) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for f in uploaded_files or []:
        out.append(
            {
                "name": getattr(f, "name", "foto.jpg"),
                "type": getattr(f, "type", "image/jpeg"),
                "data": f.getvalue(),  # bytes
            }
        )
    return out


def _state_to_pil_images(fotos_state) -> List[Image.Image]:
    fotos_pil: List[Image.Image] = []
    for item in fotos_state or []:
        fotos_pil.append(Image.open(io.BytesIO(item["data"])))
    return fotos_pil


class InMemoryUpload(io.BytesIO):
    """Wrapper mínimo para simular UploadedFile en ia_engine (name/type + stream)."""

    def __init__(self, data: bytes, name: str = "foto.jpg", mime: str = "image/jpeg"):
        super().__init__(data)
        self.name = name
        self.type = mime


def _state_to_uploadlike(fotos_state) -> List[InMemoryUpload]:
    return [
        InMemoryUpload(x["data"], x.get("name", "foto.jpg"), x.get("type", "image/jpeg"))
        for x in (fotos_state or [])
    ]


# ------------------------------------------------------------
# VALIDACIÓN / PARSEO RESULTADO FINAL
# ------------------------------------------------------------
def _is_blank(s: Any) -> bool:
    return s is None or str(s).strip() == ""


def _parse_float(value: Any) -> float:
    return float(str(value).replace(",", ".").strip())


def validar_datos(draft: Dict[str, Any]) -> List[str]:
    errores: List[str] = []

    for campo in ["marca", "modelo", "anio", "horas", "cv"]:
        if _is_blank(draft.get(campo, "")):
            errores.append(f"El campo **{campo}** es obligatorio.")

    anio = str(draft.get("anio", "")).strip()
    if anio and (not anio.isdigit() or len(anio) != 4):
        errores.append("El campo **año** debe ser un número de 4 dígitos (ej: 2022).")

    for campo_num in ["horas", "cv", "kg_contrapesos"]:
        val = str(draft.get(campo_num, "")).strip()
        if val == "":
            continue
        try:
            x = _parse_float(val)
            if x < 0:
                errores.append(f"El campo **{campo_num}** no puede ser negativo.")
        except Exception:
            errores.append(f"El campo **{campo_num}** debe ser numérico.")

    fotos_state = draft.get("fotos_state") or []
    if len(fotos_state) < 4:
        errores.append("Debes subir **mínimo 4 fotos** para tasar.")

    if _is_blank(draft.get("vida_neum_grandes", "")):
        errores.append("Selecciona la **vida útil neumáticos grandes (%)**.")
    if _is_blank(draft.get("vida_neum_pequenos", "")):
        errores.append("Selecciona la **vida útil neumáticos pequeños (%)**.")

    return errores


def _find_block_resultado_final(text: str) -> str:
    """
    Extrae el bloque BLOQUE: RESULTADO_FINAL hasta el siguiente BLOQUE: o fin.
    """
    if not text:
        return ""
    m = re.search(r"(?is)BLOQUE\s*:\s*RESULTADO_FINAL\s*(.*)", text)
    if not m:
        return ""
    tail = m.group(1)
    m2 = re.search(r"(?is)\n\s*BLOQUE\s*:\s*", tail)
    return tail[: m2.start()] if m2 else tail


def _extract_int_line(block: str, key: str) -> Optional[float]:
    """
    Captura líneas tipo:
      VALOR_BASE: 78000
      - VALOR_BASE: 78000
    (sin separadores de miles según prompt)
    """
    if not block:
        return None
    m = re.search(rf"(?im)^\s*-?\s*{re.escape(key)}\s*:\s*([\-]?\d+)\s*$", block)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def parse_resultado_final(text: str) -> Dict[str, float]:
    """
    Nunca deja vacíos:
    - Intenta leer RESULTADO_FINAL.
    - Si falta algún campo, lo calcula con las fórmulas del prompt.
    """
    out: Dict[str, float] = {}
    block = _find_block_resultado_final(text)

    keys = ["VALOR_BASE", "AJUSTE_HORAS_%", "AJUSTE_ESTADO_%", "VALOR_MERCADO", "PRECIO_VENTA", "PRECIO_COMPRA"]
    for k in keys:
        v = _extract_int_line(block, k)
        if v is not None:
            out[k] = v

    # Fallbacks calculados (evita "—")
    vb = out.get("VALOR_BASE")
    ah = out.get("AJUSTE_HORAS_%", 0.0)
    ae = out.get("AJUSTE_ESTADO_%", 0.0)

    if out.get("VALOR_MERCADO") is None and vb is not None:
        vm = vb * (1.0 + ah / 100.0) * (1.0 + ae / 100.0)
        out["VALOR_MERCADO"] = float(round(vm))

    vm = out.get("VALOR_MERCADO")

    if out.get("PRECIO_VENTA") is None and vm is not None:
        out["PRECIO_VENTA"] = float(round(vm * 0.92))

    if out.get("PRECIO_COMPRA") is None and vm is not None:
        out["PRECIO_COMPRA"] = float(round(vm * 0.85))

    return out


# ------------------------------------------------------------
# MOTOR AJUSTES (EXTRAS/APARTADOS)
# ------------------------------------------------------------
def calcular_ajustes_extras(draft: Dict[str, Any], coefs: Dict[str, Any]) -> Tuple[float, List[Tuple[str, float]]]:
    cv = _parse_float(draft["cv"])
    kg = _parse_float(draft.get("kg_contrapesos", 0) or 0)

    vida_g = float(draft["vida_neum_grandes"])
    vida_p = float(draft["vida_neum_pequenos"])

    desglose: List[Tuple[str, float]] = []
    total = 0.0

    pala = bool(draft.get("extra_pala", False))
    anclajes = bool(draft.get("extra_anclajes_pala", False))
    trip = bool(draft.get("extra_tripuntal_del", False))
    tdf = bool(draft.get("extra_tdf_del", False))
    comp = bool(draft.get("extra_compresor", False))
    autog = bool(draft.get("extra_autoguiado", False))

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
        v_cv = float(coefs.get("autoguiado_eur_por_cv", 0.0)) * cv
        v_fx = float(coefs.get("autoguiado_eur_fijo", 0.0))
        v = v_cv + v_fx
        if v != 0:
            desglose.append(("Autoguiado", v))
            total += v

    if kg > 0:
        v = float(coefs.get("contrapesos_eur_por_kg", 0.0)) * kg
        desglose.append((f"Contrapesos ({kg:.0f} kg)", v))
        total += v

    neu = coefs.get("neumaticos", {}) if isinstance(coefs.get("neumaticos", {}), dict) else {}
    max_g = float(neu.get("max_grandes_eur_por_cv", 50.0))
    max_p = float(neu.get("max_pequenos_eur_por_cv", 20.0))

    penal_g = (1.0 - (vida_g / 100.0)) * max_g * cv
    penal_p = (1.0 - (vida_p / 100.0)) * max_p * cv

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
    lines = []
    lines.append("[EXTRAS / AJUSTES (APARTE)]")
    for concepto, importe in items:
        sign = "+" if importe >= 0 else "-"
        lines.append(f"- {concepto}: {sign}{fmt_eur(abs(importe))}")
    lines.append(f"- TOTAL EXTRAS/APARTADOS: {fmt_eur(total_ajustes)}")
    return "\n".join(lines)


# ------------------------------------------------------------
# VISTA ACCESO (tasadores)
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

    with st.spinner("Cargando tasadores..."):
        vendedores = get_vendedores_cached(ENV_KEY)

    t1, t2 = st.tabs(["Seleccionar", "Registrar nuevo"])

    with t1:
        with st.form("form_sel"):
            v_sel = st.selectbox("Selecciona tu nombre:", [""] + vendedores, index=0)
            entrar = st.form_submit_button("Entrar", use_container_width=True)
        if entrar:
            if not v_sel:
                st.error("Selecciona un nombre.")
            else:
                st.session_state["logged_in"] = True
                st.session_state["vendedor"] = v_sel
                st.rerun()

    with t2:
        with st.form("form_reg", clear_on_submit=True):
            nuevo = st.text_input("Nombre y Apellido del nuevo tasador:")
            registrar = st.form_submit_button("Registrar y Entrar", use_container_width=True)

        if registrar:
            nombre = (nuevo or "").strip()
            if len(nombre) < 2:
                st.error("Introduce un nombre válido.")
                return

            if nombre in vendedores:
                st.session_state["logged_in"] = True
                st.session_state["vendedor"] = nombre
                st.rerun()

            creds = None if ES_CLOUD_RUN else CREDS
            ok = google_drive_manager.actualizar_vendedores(creds, vendedores + [nombre])
            if ok:
                invalidate_vendedores_cache()
                st.session_state["logged_in"] = True
                st.session_state["vendedor"] = nombre
                st.rerun()
            else:
                st.error("No se pudo escribir en vendedores.txt (permisos o archivo no encontrado).")


# ------------------------------------------------------------
# LOGIN
# ------------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    vista_acceso()
    st.stop()

# Branding + css (solo una vez logado)
ocultar_chrome_streamlit()

# ------------------------------------------------------------
# HEADER (logo también en resultados)
# ------------------------------------------------------------
col_logo, col_controls = st.columns([6, 2])
with col_logo:
    if os.path.exists("Transparente.png"):
        st.image("Transparente.png", width=220)
    else:
        st.markdown("### Agrícola Noroeste")
    st.markdown(f"### 🚜 {st.session_state.get('vendedor','')}")

with col_controls:
    if st.button("♻️ Recargar coeficientes", use_container_width=True):
        invalidate_coef_cache()
        st.rerun()
    if st.button("Salir", use_container_width=True):
        for k in ["logged_in", "vendedor", "draft", "result", "uploader_fotos", "vertex_client"]:
            st.session_state.pop(k, None)
        st.rerun()

st.divider()

COEFS = get_coeficientes_cached(ENV_KEY)

# ------------------------------------------------------------
# CONEXIÓN IA
# ------------------------------------------------------------
if "vertex_client" not in st.session_state:
    try:
        creds_vertex = None if ES_CLOUD_RUN else CREDS
        st.session_state.vertex_client = ia_engine.conectar_vertex(creds_vertex)
    except Exception as e:
        st.error(f"Error inicializando Vertex AI: {e}")

# ------------------------------------------------------------
# GPS
# ------------------------------------------------------------
loc = get_geolocation(component_key="gps_v1")
texto_ubicacion = (
    location_manager.codificar_coordenadas(loc["coords"]["latitude"], loc["coords"]["longitude"])
    if loc and "coords" in loc
    else "UBICACIÓN NO DETECTADA"
)

# ------------------------------------------------------------
# BORRADOR
# ------------------------------------------------------------
st.session_state.setdefault(
    "draft",
    {
        "marca": "Valtra",
        "modelo": "G125",
        "anio": "2025",
        "horas": "2500",
        "cv": "",
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
        "extra_autoguiado": False,
    },
)

OPC_VIDA = [""] + [str(x) for x in range(0, 101, 20)]

# ------------------------------------------------------------
# FORMULARIO / RESULTADOS
# ------------------------------------------------------------
if "result" not in st.session_state:
    st.subheader("Datos del Peritaje")

    fotos_up = st.file_uploader(
        "Subir fotos del tractor (mínimo 4)",
        accept_multiple_files=True,
        type=["jpg", "jpeg", "png"],
        key="uploader_fotos",
    )
    if fotos_up:
        st.session_state["draft"]["fotos_state"] = _fotos_to_state(fotos_up)

    fotos_guardadas = st.session_state["draft"]["fotos_state"] or []
    if fotos_guardadas:
        st.success(f"✅ Fotos guardadas en memoria: {len(fotos_guardadas)} (mínimo 4)")
        if st.button("🗑️ Vaciar fotos guardadas", use_container_width=True):
            st.session_state["draft"]["fotos_state"] = []
            st.session_state.pop("uploader_fotos", None)
            st.rerun()
    else:
        st.warning("⚠️ No hay fotos guardadas todavía. Súbelas para iniciar la tasación.")

    with st.form("form_peritaje", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            marca = st.text_input("Marca *", value=st.session_state["draft"]["marca"])
            modelo = st.text_input("Modelo *", value=st.session_state["draft"]["modelo"])
        with col2:
            anio = st.text_input("Año *", value=st.session_state["draft"]["anio"])
            horas = st.text_input("Horas *", value=st.session_state["draft"]["horas"])

        colp1, colp2 = st.columns(2)
        with colp1:
            cv = st.text_input("CV *", value=st.session_state["draft"]["cv"])
        with colp2:
            kg_contrapesos = st.text_input("Kg contrapesos", value=st.session_state["draft"]["kg_contrapesos"])

        obs = st.text_area("Observaciones adicionales del perito", value=st.session_state["draft"]["obs"])

        st.markdown("#### Extras del tractor")
        e1, e2, e3 = st.columns(3)
        with e1:
            extra_pala = st.checkbox("Pala", value=st.session_state["draft"]["extra_pala"])
            extra_anclajes_pala = st.checkbox("Anclajes de pala", value=st.session_state["draft"]["extra_anclajes_pala"])
        with e2:
            extra_tripuntal_del = st.checkbox("Tripuntal del.", value=st.session_state["draft"]["extra_tripuntal_del"])
            extra_tdf_del = st.checkbox("TDF del.", value=st.session_state["draft"]["extra_tdf_del"])
        with e3:
            extra_compresor = st.checkbox("Compresor", value=st.session_state["draft"]["extra_compresor"])
            extra_autoguiado = st.checkbox("Autoguiado", value=st.session_state["draft"]["extra_autoguiado"])

        st.markdown("#### Vida útil neumáticos")
        n1, n2 = st.columns(2)
        with n1:
            vida_neum_grandes = st.selectbox(
                "Vida útil neumáticos grandes (%) *",
                options=OPC_VIDA,
                index=OPC_VIDA.index(str(st.session_state["draft"]["vida_neum_grandes"]))
                if str(st.session_state["draft"]["vida_neum_grandes"]) in OPC_VIDA
                else 0,
            )
        with n2:
            vida_neum_pequenos = st.selectbox(
                "Vida útil neumáticos pequeños (%) *",
                options=OPC_VIDA,
                index=OPC_VIDA.index(str(st.session_state["draft"]["vida_neum_pequenos"]))
                if str(st.session_state["draft"]["vida_neum_pequenos"]) in OPC_VIDA
                else 0,
            )

        submit = st.form_submit_button("🚀 INICIAR TASACIÓN Y GUARDAR", use_container_width=True)

    if submit:
        d = st.session_state["draft"]
        d["marca"] = marca
        d["modelo"] = modelo
        d["anio"] = anio
        d["horas"] = horas
        d["cv"] = cv
        d["kg_contrapesos"] = kg_contrapesos
        d["obs"] = obs
        d["extra_pala"] = extra_pala
        d["extra_anclajes_pala"] = extra_anclajes_pala
        d["extra_tripuntal_del"] = extra_tripuntal_del
        d["extra_tdf_del"] = extra_tdf_del
        d["extra_compresor"] = extra_compresor
        d["extra_autoguiado"] = extra_autoguiado
        d["vida_neum_grandes"] = vida_neum_grandes
        d["vida_neum_pequenos"] = vida_neum_pequenos

        errores = validar_datos(d)
        if errores:
            st.error("No se puede iniciar la tasación. Revisa:")
            for e in errores:
                st.markdown(f"- {e}")
        elif "vertex_client" not in st.session_state:
            st.error("El cliente de IA no está conectado.")
        else:
            with st.spinner("Procesando tasación..."):
                try:
                    total_ajustes, desglose_items = calcular_ajustes_extras(d, COEFS)
                    bloque_extras = bloque_extras_texto(total_ajustes, desglose_items)

                    fotos_pil = _state_to_pil_images(d["fotos_state"])
                    fotos_for_ai = fotos_up if fotos_up else _state_to_uploadlike(d["fotos_state"])

                    informe = ia_engine.realizar_peritaje(
                        st.session_state.vertex_client,
                        d["marca"],
                        d["modelo"],
                        d["anio"],
                        d["horas"],
                        (d["obs"] or "").strip(),
                        fotos_for_ai,
                    )

                    base_dict = parse_resultado_final(informe)

                    ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")
                    html = html_generator.generar_informe_html(
                        d["marca"],
                        d["modelo"],
                        informe,
                        fotos_pil,
                        ref_b64,
                    )

                    nombre_fichero = f"Tasacion_{d['marca']}_{d['modelo']}.html"
                    carpeta = st.session_state.get("vendedor", "General")
                    creds_drive = None if ES_CLOUD_RUN else CREDS

                    id_archivo = google_drive_manager.subir_informe(
                        creds_drive,
                        nombre_fichero,
                        html,
                        folder_name=carpeta,
                    )

                    st.session_state["result"] = {
                        "informe_final": informe,
                        "html": html,
                        "nombre_archivo": nombre_fichero,
                        "id_archivo_drive": id_archivo,
                        "base_dict": base_dict,
                        "extras_total": total_ajustes,
                        "extras_items": desglose_items,
                        "bloque_extras": bloque_extras,
                    }
                    st.rerun()

                except Exception as e:
                    st.error(f"Error en el proceso: {e}")

# ---------------- RESULTADOS ----------------
if "result" in st.session_state:
    res = st.session_state["result"]
    base = res.get("base_dict", {}) or {}
    extras_total = float(res.get("extras_total", 0.0))
    bloque_extras = res.get("bloque_extras", "")

    if res.get("id_archivo_drive"):
        st.success("✅ Peritaje finalizado y archivado en Drive.")
    else:
        st.success("✅ Peritaje finalizado.")
        st.warning("⚠️ No se recibió ID de Drive (permisos/archivo).")

    st.markdown("### 🤖 Resultado del Análisis (IA)")
    
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(res["informe_final"])
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("### Precios base del tasador (RESULTADO_FINAL)")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("VALOR_MERCADO", fmt_eur(base.get("VALOR_MERCADO")))
    with c2:
        st.metric("PRECIO_VENTA", fmt_eur(base.get("PRECIO_VENTA")))
    with c3:
        st.metric("PRECIO_COMPRA", fmt_eur(base.get("PRECIO_COMPRA")))

    st.markdown("### Extras / Ajustes (APARTE)")
    st.code(bloque_extras)

    if base.get("VALOR_MERCADO") is not None:
        st.markdown("### Referencia (base + extras) — solo orientativo")
        r1, r2, r3 = st.columns(3)
        with r1:
            st.metric("Mercado + Extras", fmt_eur(float(base["VALOR_MERCADO"]) + extras_total))
        with r2:
            st.metric(
                "Venta + Extras",
                fmt_eur(float(base["PRECIO_VENTA"]) + extras_total) if base.get("PRECIO_VENTA") is not None else "—",
            )
        with r3:
            st.metric(
                "Compra + Extras",
                fmt_eur(float(base["PRECIO_COMPRA"]) + extras_total) if base.get("PRECIO_COMPRA") is not None else "—",
            )

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        st.download_button(
            label="📄 DESCARGAR HTML",
            data=res["html"],
            file_name=res["nombre_archivo"],
            mime="text/html",
            use_container_width=True,
        )
    with col_btn2:
        if st.button("↩️ VOLVER A TASAR (mantener datos y fotos)", use_container_width=True):
            st.session_state.pop("result", None)
            st.rerun()
