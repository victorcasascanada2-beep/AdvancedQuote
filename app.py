# app.py py
import os
import io
import re
import base64
import json
import datetime
import requests

from typing import Dict, Any, List

import streamlit as st
from PIL import Image

import ia_engine
import html_generator
import google_drive_manager
import google_sheets_manager
import location_manager
import calculos


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
ES_CLOUD_RUN = os.environ.get("K_SERVICE") is not None
CREDS = None if ES_CLOUD_RUN else st.secrets.get("gcp_service_account", None)

st.set_page_config(page_title="Tasación IA", layout="wide")


# ------------------------------------------------------------
# HELPERS / STATE
# ------------------------------------------------------------
def init_state():
    if "draft" not in st.session_state:
        st.session_state["draft"] = {
            "marca": "",
            "modelo": "",
            "anio": "",
            "horas": "",
            "cv": "",
            "observaciones": "",
            "fotos_state": [],
        }
    if "result" not in st.session_state:
        st.session_state["result"] = {}
    if "vendedor" not in st.session_state:
        st.session_state["vendedor"] = ""


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
def _is_blank(s: Any) -> bool: return s is None or str(s).strip() == ""
def _parse_float(value: Any) -> float: return float(str(value).replace(",", ".").strip())


def validar_datos(draft: Dict[str, Any]) -> List[str]:
    errores = []
    for campo in ["marca", "modelo", "anio", "horas", "cv"]:
        if _is_blank(draft.get(campo, "")): errores.append(f"El campo **{campo}** es obligatorio.")
    anio = str(draft.get("anio", "")).strip()
    if anio and (not anio.isdigit() or len(anio) != 4):
        errores.append("El campo **año** debe ser un número de 4 dígitos.")
    try:
        _ = _parse_float(draft.get("horas", "0"))
    except Exception:
        errores.append("El campo **horas** debe ser numérico.")
    try:
        _ = _parse_float(draft.get("cv", "0"))
    except Exception:
        errores.append("El campo **cv** debe ser numérico.")
    return errores


def parse_resultado_final(texto: str) -> Dict[str, Any]:
    """
    Extrae (si existe) el bloque RESULTADO_FINAL y devuelve dict.
    """
    if not texto:
        return {}
    m = re.search(r"BLOQUE:\s*RESULTADO_FINAL(.*?)(?:BLOQUE:|$)", texto, flags=re.S | re.I)
    if not m:
        return {}
    block = m.group(1).strip()

    def get_int(key):
        mm = re.search(rf"{re.escape(key)}\s*:\s*([0-9\.\,]+)", block)
        if not mm: return None
        return int(float(mm.group(1).replace(".", "").replace(",", ".")))

    return {
        "valor_mercado": get_int("VALOR_MERCADO"),
        "precio_venta": get_int("PRECIO_VENTA"),
        "precio_compra": get_int("PRECIO_COMPRA"),
    }


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------
init_state()

st.title("Tasación IA")

with st.sidebar:
    st.subheader("Vendedor")
    vendedor = st.text_input("Nombre vendedor", value=st.session_state.get("vendedor", ""))
    st.session_state["vendedor"] = vendedor.strip()


col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("Datos")
    d = st.session_state["draft"]
    d["marca"] = st.text_input("Marca", value=d.get("marca", ""))
    d["modelo"] = st.text_input("Modelo", value=d.get("modelo", ""))
    d["anio"] = st.text_input("Año", value=d.get("anio", ""))
    d["horas"] = st.text_input("Horas", value=d.get("horas", ""))
    d["cv"] = st.text_input("CV", value=d.get("cv", ""))
    d["observaciones"] = st.text_area("Observaciones", value=d.get("observaciones", ""))

    st.subheader("Fotos")
    uploaded = st.file_uploader(
        "Sube fotos (JPG/PNG/WEBP).",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True
    )

    if uploaded is not None:
        d["fotos_state"] = _fotos_to_state(uploaded)

    if d.get("fotos_state"):
        st.caption(f"Fotos cargadas (optimizado): {len(d['fotos_state'])}")

    run = st.button("Generar informe", type="primary")


with col2:
    st.subheader("Resultado")
    if run:
        errores = validar_datos(st.session_state["draft"])
        if errores:
            for e in errores:
                st.error(e)
            st.stop()

        d = st.session_state["draft"]
        marca = d["marca"]
        modelo = d["modelo"]
        anio = d["anio"]
        horas = d["horas"]
        cv = d["cv"]
        obs = d.get("observaciones", "")

        with st.spinner("Conectando a Vertex..."):
            client = ia_engine.conectar_vertex(CREDS)

        texto_ubicacion = ""
        try:
            texto_ubicacion = location_manager.obtener_texto_ubicacion()
        except Exception:
            texto_ubicacion = ""

        with st.spinner("Analizando con IA..."):
            inf = ia_engine.realizar_peritaje(client, marca, modelo, anio, horas, obs, _state_to_uploadlike(d["fotos_state"]))

        base_dict = parse_resultado_final(inf)
        ref_b64 = base64.b64encode(texto_ubicacion.encode("utf-8")).decode("utf-8")

        # ✅ CAMBIO: pasar fotos_state DIRECTO (sin PIL)
        html = html_generator.generar_informe_html(
            marca,
            modelo,
            inf,
            d["fotos_state"],
            ref_b64,
            vendedor=st.session_state.get("vendedor", "")
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
            requests.post(
                url_sheets,
                json={
                    "marca": marca,
                    "modelo": modelo,
                    "anio": anio,
                    "horas": horas,
                    "cv": cv,
                    "valor_mercado": base_dict.get("valor_mercado"),
                    "precio_venta": base_dict.get("precio_venta"),
                    "precio_compra": base_dict.get("precio_compra"),
                    "drive_id": id_drive,
                    "vendedor": st.session_state.get("vendedor", ""),
                },
                timeout=20
            )
        except Exception:
            pass

        st.success("Informe generado y subido.")
        st.write("ID Drive:", id_drive)

        st.markdown("### Resultado del Análisis (IA)")
        st.markdown(inf)
