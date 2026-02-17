import streamlit as st
import os
import io
import re
import json
import base64
from typing import List, Dict, Any, Tuple
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

# Doble ejecución (NO cambiar):
# - Cloud Run: ADC (sin secrets)
# - Local/Streamlit: st.secrets["google"]
ES_CLOUD_RUN = bool(os.environ.get("K_SERVICE") or os.environ.get("K_REVISION"))
ENV_KEY = "cloud" if ES_CLOUD_RUN else "local"


def ocultar_chrome_streamlit():
    st.markdown(
        """
        <style>
          header {visibility: hidden;}
          footer {visibility: hidden;}
          #MainMenu {visibility: hidden;}
          [data-testid="stToolbar"] {visibility: hidden;}
          [data-testid="stHeader"] {visibility: hidden;}
          .block-container {padding-top: 1.2rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    # opcional si algún día lo metes en el JSON
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
# PARSEOS / VALIDACIÓN / ESTIMACIÓN BASE
# ------------------------------------------------------------
def _is_blank(s: Any) -> bool:
    return s is None or str(s).strip() == ""


def _parse_float(value: Any) -> float:
    return float(str(value).replace(",", ".").strip())


def parse_first_euro_number(text: str) -> float:
    """
    Fallback: extrae el primer número tipo '12.345,67' o '12345.67' o '12345' de un texto.
    """
    if not text:
        raise ValueError("Texto vacío")

    m = re.search(r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)", text)
    if not m:
        raise ValueError("No se encontró número")

    s = m.group(1).strip().replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        if "," in s:
            s = s.replace(",", ".")
    return float(s)


def parse_precio_base_json(text: str) -> float:
    """
    Espera un JSON tipo: {"precio_base_eur": 12345}
    Busca el primer bloque {...} y parsea.
    """
    if not text:
        raise ValueError("Texto vacío")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No hay JSON")
    obj = json.loads(text[start : end + 1])
    val = obj.get("precio_base_eur", None)
    if val is None:
        raise ValueError("Falta precio_base_eur")
    return float(val)


def detectar_desajuste_base(base_manual: float, base_estimado: float) -> str:
    """
    Warning si la diferencia es grande:
      - > 15% y > 2500€
    """
    if base_manual <= 0 or base_estimado <= 0:
        return ""

    diff = abs(base_manual - base_estimado)
    pct = diff / base_estimado

    if diff > 2500 and pct > 0.15:
        return (
            f"⚠️ Desajuste grande: base manual {base_manual:,.0f}€ vs estimada {base_estimado:,.0f}€ "
            f"(~{pct*100:.0f}%)."
        )
    return ""


def validar_datos(draft: Dict[str, Any]) -> List[str]:
    errores: List[str] = []

    for campo in ["marca", "modelo", "anio", "horas", "cv"]:
        if _is_blank(draft.get(campo, "")):
            errores.append(f"El campo **{campo}** es obligatorio.")

    # precio_base puede ser número o "ESTIMAR"
    precio_base_raw = str(draft.get("precio_base", "")).strip()
    if _is_blank(precio_base_raw):
        errores.append("El campo **precio_base** es obligatorio (número o ESTIMAR).")
    elif precio_base_raw.upper() != "ESTIMAR":
        try:
            x = _parse_float(precio_base_raw)
            if x <= 0:
                errores.append("El **precio base** debe ser mayor que 0.")
        except Exception:
            errores.append("El campo **precio_base** debe ser numérico o ESTIMAR.")

    # año
    anio = str(draft.get("anio", "")).strip()
    if anio and (not anio.isdigit() or len(anio) != 4):
        errores.append("El campo **año** debe ser un número de 4 dígitos (ej: 2022).")

    # horas / cv / kg
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

    # fotos
    fotos_state = draft.get("fotos_state") or []
    if len(fotos_state) < 4:
        errores.append("Debes subir **mínimo 4 fotos** para tasar.")

    # vida neumáticos (obligatorio)
    if _is_blank(draft.get("vida_neum_grandes", "")):
        errores.append("Selecciona la **vida útil neumáticos grandes (%)**.")
    if _is_blank(draft.get("vida_neum_pequenos", "")):
        errores.append("Selecciona la **vida útil neumáticos pequeños (%)**.")

    return errores


# ------------------------------------------------------------
# MOTOR DE CÁLCULO
# ------------------------------------------------------------
def calcular_precio_final_y_desglose(
    draft: Dict[str, Any], coefs: Dict[str, Any], precio_base_num: float
) -> Tuple[float, List[Tuple[str, float]]]:
    """
    Devuelve:
      - precio_final
      - desglose [(concepto, importe)] donde importe puede ser + o -
    """
    cv = _parse_float(draft["cv"])
    kg = _parse_float(draft.get("kg_contrapesos", 0) or 0)

    vida_g = float(draft["vida_neum_grandes"])
    vida_p = float(draft["vida_neum_pequenos"])

    desglose: List[Tuple[str, float]] = []
    ajuste_total = 0.0

    pala = bool(draft.get("extra_pala", False))
    anclajes = bool(draft.get("extra_anclajes_pala", False))
    trip = bool(draft.get("extra_tripuntal_del", False))
    tdf = bool(draft.get("extra_tdf_del", False))
    comp = bool(draft.get("extra_compresor", False))
    autog = bool(draft.get("extra_autoguiado", False))

    # Pala
    if pala:
        v = float(coefs.get("pala_eur_por_cv", 0.0)) * cv
        desglose.append(("Pala usada", v))
        ajuste_total += v
        anclajes = False  # incluidos

    # Anclajes (solo si NO pala)
    if anclajes:
        v = float(coefs.get("anclajes_eur_por_cv", 0.0)) * cv
        desglose.append(("Anclajes de pala", v))
        ajuste_total += v

    # TDF fuerza tripuntal: coef combinado
    if tdf:
        trip = True
        v = float(coefs.get("tripuntal_tdf_eur_por_cv", 0.0)) * cv
        desglose.append(("Tripuntal + TDF del.", v))
        ajuste_total += v
    elif trip:
        v = float(coefs.get("tripuntal_eur_por_cv", 0.0)) * cv
        desglose.append(("Tripuntal del.", v))
        ajuste_total += v

    # Compresor fijo
    if comp:
        v = float(coefs.get("compresor_eur_fijo", 0.0))
        desglose.append(("Compresor aire", v))
        ajuste_total += v

    # Autoguiado (si algún día lo configuras en JSON)
    if autog:
        v_cv = float(coefs.get("autoguiado_eur_por_cv", 0.0)) * cv
        v_fx = float(coefs.get("autoguiado_eur_fijo", 0.0))
        v = v_cv + v_fx
        if v != 0:
            desglose.append(("Autoguiado", v))
            ajuste_total += v

    # Contrapesos €/kg
    if kg > 0:
        v = float(coefs.get("contrapesos_eur_por_kg", 0.0)) * kg
        desglose.append((f"Contrapesos ({kg:.0f} kg)", v))
        ajuste_total += v

    # Neumáticos: castigo lineal por vida útil
    neu = coefs.get("neumaticos", {}) if isinstance(coefs.get("neumaticos", {}), dict) else {}
    max_g = float(neu.get("max_grandes_eur_por_cv", 50.0))
    max_p = float(neu.get("max_pequenos_eur_por_cv", 20.0))

    penal_g = (1.0 - (vida_g / 100.0)) * max_g * cv
    penal_p = (1.0 - (vida_p / 100.0)) * max_p * cv

    if penal_g > 0:
        desglose.append((f"Neumáticos grandes (vida {vida_g:.0f}%)", -penal_g))
        ajuste_total -= penal_g
    if penal_p > 0:
        desglose.append((f"Neumáticos pequeños (vida {vida_p:.0f}%)", -penal_p))
        ajuste_total -= penal_p

    precio_final = precio_base_num + ajuste_total
    return precio_final, desglose


def desglose_texto(
    precio_base: float,
    precio_final: float,
    items: List[Tuple[str, float]],
    base_estimado: float | None = None,
    aviso: str = "",
) -> str:
    def fmt(x: float) -> str:
        return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    lines = []
    lines.append("[AJUSTES ECONÓMICOS]")
    lines.append(f"- Precio base usado: {fmt(precio_base)}")
    if base_estimado is not None:
        lines.append(f"- Precio base estimado IA: {fmt(float(base_estimado))}")
    if aviso:
        lines.append(f"- AVISO: {aviso}")

    for concepto, importe in items:
        sign = "+" if importe >= 0 else "-"
        lines.append(f"- {concepto}: {sign}{fmt(abs(importe))}")

    lines.append(f"- Precio final: {fmt(precio_final)}")
    return "\n".join(lines)


# ------------------------------------------------------------
# VISTA ACCESO (tasadores)
# ------------------------------------------------------------
def vista_acceso():
    if os.path.exists("agricolanoroestelogo.jpg"):
        st.image("agricolanoroestelogo.jpg", width=320)
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

ocultar_chrome_streamlit()

# ------------------------------------------------------------
# HEADER
# ------------------------------------------------------------
col_logo, col_controls = st.columns([6, 2])
with col_logo:
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
# CONEXIÓN IA (doble ejecución intacta)
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
# BORRADOR PERSISTENTE (incluye extras + vida neumáticos + base/cv/kg)
# ------------------------------------------------------------
st.session_state.setdefault(
    "draft",
    {
        "marca": "Valtra",
        "modelo": "G125",
        "anio": "2025",
        "horas": "2500",
        "precio_base": "ESTIMAR",  # por defecto
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
        "precio_base_estimado": None,
    },
)

OPC_VIDA = [""] + [str(x) for x in range(0, 101, 10)]

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

        colp1, colp2, colp3 = st.columns(3)
        with colp1:
            precio_base = st.text_input("Precio base (€) *", value=st.session_state["draft"]["precio_base"])
            st.caption("Escribe un número o pon **ESTIMAR**.")
        with colp2:
            cv = st.text_input("CV *", value=st.session_state["draft"]["cv"])
        with colp3:
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
        d["precio_base"] = precio_base
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
                    # -------------------------
                    # 1) Estimar precio base (JSON) o usar manual + avisar
                    # -------------------------
                    precio_base_raw = str(d["precio_base"]).strip()
                    modo_estimar = (precio_base_raw.upper() == "ESTIMAR")

                    # Estimamos SIEMPRE para poder avisar si hay desajuste (puedes cambiarlo a modo_estimar)
                    hacer_estimacion = True

                    base_estimado = None
                    aviso = ""

                    if hacer_estimacion:
                        try:
                            prompt_estimacion = (
                                'Devuelve EXCLUSIVAMENTE un JSON válido (sin texto adicional).\n'
                                'Formato: {"precio_base_eur": 12345}\n'
                                "- Solo un número entero en euros.\n"
                                "- Sin símbolos, sin separadores de miles.\n"
                            )

                            fotos_for_ai_est = fotos_up if fotos_up else _state_to_uploadlike(d["fotos_state"])

                            resp_base = ia_engine.realizar_peritaje(
                                st.session_state.vertex_client,
                                d["marca"],
                                d["modelo"],
                                d["anio"],
                                d["horas"],
                                prompt_estimacion,
                                fotos_for_ai_est,
                            )

                            try:
                                base_estimado = parse_precio_base_json(resp_base)
                            except Exception:
                                # fallback (por si el modelo no devuelve JSON estricto)
                                base_estimado = parse_first_euro_number(resp_base)

                            # guardrail: evitar "1", "2025", etc.
                            if base_estimado is not None and base_estimado < 1000:
                                base_estimado = None
                        except Exception:
                            base_estimado = None

                    if modo_estimar:
                        if base_estimado is None:
                            st.error("No se pudo estimar el precio base automáticamente. Introduce un precio base manual.")
                            st.stop()
                        precio_base_num = float(base_estimado)
                        d["precio_base"] = f"{precio_base_num:.0f}"  # fijamos base usada
                    else:
                        precio_base_num = _parse_float(d["precio_base"])
                        if base_estimado is not None:
                            aviso = detectar_desajuste_base(precio_base_num, float(base_estimado))
                            if aviso:
                                st.warning(aviso)

                    d["precio_base_estimado"] = base_estimado

                    # -------------------------
                    # 2) Calcular precio final + desglose
                    # -------------------------
                    precio_final, desglose_items = calcular_precio_final_y_desglose(d, COEFS, precio_base_num)

                    bloque_calc = desglose_texto(
                        precio_base=precio_base_num,
                        precio_final=precio_final,
                        items=desglose_items,
                        base_estimado=base_estimado,
                        aviso=aviso,
                    )

                    # -------------------------
                    # 3) Observaciones para IA (incluye desglose)
                    # -------------------------
                    obs_para_ia = (d["obs"] or "").strip()
                    obs_para_ia = (obs_para_ia + "\n\n" + bloque_calc).strip()

                    # Fotos
                    fotos_pil = _state_to_pil_images(d["fotos_state"])
                    fotos_for_ai = fotos_up if fotos_up else _state_to_uploadlike(d["fotos_state"])

                    # IA final
                    inf = ia_engine.realizar_peritaje(
                        st.session_state.vertex_client,
                        d["marca"],
                        d["modelo"],
                        d["anio"],
                        d["horas"],
                        obs_para_ia,
                        fotos_for_ai,
                    )

                    # HTML
                    ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")
                    html = html_generator.generar_informe_html(
                        d["marca"],
                        d["modelo"],
                        inf,
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
                        "informe_final": inf,
                        "html": html,
                        "nombre_archivo": nombre_fichero,
                        "id_archivo_drive": id_archivo,
                        "bloque_calc": bloque_calc,
                    }
                    st.rerun()

                except Exception as e:
                    st.error(f"Error en el proceso: {e}")

# ---------------- RESULTADOS ----------------
if "result" in st.session_state:
    res = st.session_state["result"]

    if res.get("id_archivo_drive"):
        st.success("✅ Peritaje finalizado y archivado en Drive.")
    else:
        st.success("✅ Peritaje finalizado.")
        st.warning("⚠️ No se recibió ID de Drive (permisos/archivo).")

    st.markdown("### Resultado del Análisis (IA)")
    st.markdown(res["informe_final"])

    st.markdown("### Desglose económico")
    st.code(res["bloque_calc"])

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
