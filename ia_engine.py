# ia_engine.py

import io
from google import genai
from google.oauth2 import service_account
from PIL import Image, ImageOps
import config_prompt

# API tipado (mejor para imágenes y tools)
try:
    from google.genai import types
    _HAS_TYPES = True
except Exception:
    _HAS_TYPES = False


def conectar_vertex(creds_dict=None):
    """
    Conexión híbrida a Vertex AI.
    - creds_dict=None: Cloud Run (ADC)
    - creds_dict!=None: local/Streamlit (service account en secrets)
    """
    if creds_dict is None:
        return genai.Client(vertexai=True, project="subida-fotos-drive", location="us-central1")

    pk = str(creds_dict.get("private_key", ""))
    clean_key = pk.strip().strip('"').strip("'").replace("\\n", "\n")

    auth_info = {
        "type": "service_account",
        "project_id": creds_dict.get("project_id"),
        "private_key": clean_key,
        "client_email": creds_dict.get("client_email"),
        "token_uri": "https://oauth2.googleapis.com/token",
    }

    google_creds = service_account.Credentials.from_service_account_info(auth_info)
    scoped_creds = google_creds.with_scopes(["https://www.googleapis.com/auth/cloud-platform"])

    return genai.Client(
        vertexai=True,
        project=auth_info["project_id"],
        location="us-central1",
        credentials=scoped_creds,
    )


def _normalizar_imagen_a_jpeg_bytes(uploaded_file, max_side=800, quality=60) -> bytes:
    img = Image.open(uploaded_file)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")

    w, h = img.size
    scale = max(w, h) / float(max_side)
    if scale > 1.0:
        new_w = int(round(w / scale))
        new_h = int(round(h / scale))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    # Aquí aplicamos la calidad 60 y optimización de tabla JPEG
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _tasacion_sin_busqueda(client, prompt_tasacion, fotos_sorted) -> str:
    """
    1) Estima precio SIN internet (estable).
    """
    if _HAS_TYPES:
        parts = []
        for f in fotos_sorted:
            data = _normalizar_imagen_a_jpeg_bytes(f)
            parts.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))

        resp = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=[prompt_tasacion, *parts],
            config=types.GenerateContentConfig(
                temperature=0.05,
                max_output_tokens=4096,
            ),
        )
        return resp.text

    # Fallback sin types
    fotos_pil = []
    for f in fotos_sorted:
        data = _normalizar_imagen_a_jpeg_bytes(f)
        fotos_pil.append(Image.open(io.BytesIO(data)))

    resp = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[prompt_tasacion] + fotos_pil,
        config={"temperature": 0.05, "max_output_tokens": 4096},
    )
    return resp.text


def _comparables_con_busqueda(client, prompt_comparables) -> str:
    """
    2) Busca anuncios SOLO para justificar (NO toca el precio).
       Devuelve TABLA sin URLs (según prompt).
    """
    if _HAS_TYPES:
        resp = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=[prompt_comparables],
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.0,
                max_output_tokens=2048,
            ),
        )
        return resp.text

    resp = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[prompt_comparables],
        config={
            "tools": [{"google_search": {}}],
            "temperature": 0.0,
            "max_output_tokens": 2048,
        },
    )
    return resp.text


def realizar_peritaje(client, marca, modelo, anio, horas, observaciones, lista_fotos):
    """
    Flujo:
    1) TASACIÓN (estable, sin búsqueda) => precio
    2) COMPARABLES (con búsqueda) => justificación en tabla (sin URLs)
    """
    fotos_sorted = sorted(lista_fotos, key=lambda f: getattr(f, "name", ""))

    prompt_tasacion = config_prompt.obtener_prompt_tasacion(marca, modelo, anio, horas, observaciones)
    prompt_comparables = config_prompt.obtener_prompt_comparables(marca, modelo, anio, horas)

    tasacion_txt = _tasacion_sin_busqueda(client, prompt_tasacion, fotos_sorted)

    try:
        comparables_txt = _comparables_con_busqueda(client, prompt_comparables)
    except Exception as e:
        comparables_txt = (
            'BLOQUE: COMPARABLES_TABLA\n'
            '| WEB | MODELO | AÑO | HORAS | PRECIO |\n'
            '|---|---|---|---|---|\n'
            f'| Error | {str(e)} | N/D | N/D | N/D |\n'
        )

    return f"{tasacion_txt}\n\n{comparables_txt}"
