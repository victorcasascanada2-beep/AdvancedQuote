import base64
from io import BytesIO
from PIL import Image
import re
import datetime
import os
from typing import Optional


# -------------------------------------------------
# UTILIDADES IMÁGENES
# -------------------------------------------------
def _img_to_b64_jpg(img: Image.Image, max_size=(900, 900), quality=75) -> str:
    """Convierte PIL Image a base64 JPG optimizado (solo fotos)."""
    buffered = BytesIO()
    img = img.copy()
    img.thumbnail(max_size)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buffered, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode()


def cargar_logo_b64(path: str) -> str:
    """
    Devuelve DATA URI del logo:
    - PNG si hay alpha (transparente)
    - JPG si no
    """
    if not path or not os.path.exists(path):
        return ""

    try:
        with Image.open(path) as img:
            img = img.copy()
            img.thumbnail((520, 260))
            buffered = BytesIO()

            has_alpha = (
                img.mode in ("RGBA", "LA")
                or (img.mode == "P" and "transparency" in img.info)
            )

            if has_alpha:
                img.save(buffered, format="PNG", optimize=True)
                b64 = base64.b64encode(buffered.getvalue()).decode()
                return f"data:image/png;base64,{b64}"

            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(buffered, format="JPEG", quality=85, optimize=True)
            b64 = base64.b64encode(buffered.getvalue()).decode()
            return f"data:image/jpeg;base64,{b64}"

    except Exception:
        return ""


def _extraer_bloque_resultado_final(texto: str) -> str:
    m = re.search(r"BLOQUE:\s*RESULTADO_FINAL(.*?)(?:BLOQUE:|$)", texto, flags=re.S | re.I)
    return m.group(1).strip() if m else ""


def _extraer_entero(block: str, key: str):
    mm = re.search(rf"{re.escape(key)}\s*:\s*([0-9\.\,]+)", block)
    if not mm:
        return None
    return int(float(mm.group(1).replace(".", "").replace(",", ".")))


def _fmt_eur(x: Optional[int]) -> str:
    if x is None:
        return "N/D"
    try:
        return f"{int(x):,} €".replace(",", ".")
    except Exception:
        return "N/D"


def _extraer_bloque_comparables_tabla(texto: str) -> str:
    m = re.search(r"BLOQUE:\s*COMPARABLES_TABLA(.*?)(?:BLOQUE:|$)", texto, flags=re.S | re.I)
    return m.group(1).strip() if m else ""


def _escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _markdown_tabla_a_html(texto: str) -> str:
    """
    Convierte un bloque estilo markdown simple en HTML (tabla + párrafos).
    """
    if not texto:
        return ""

    out = []
    lines = [ln.rstrip() for ln in texto.splitlines()]
    en_tabla = False

    for linea in lines:
        # Tabla markdown
        if "|" in linea and linea.count("|") >= 2:
            cols = [c.strip() for c in linea.strip().strip("|").split("|")]

            # header separator
            if all(set(c) <= {"-", ":"} for c in cols):
                continue

            if not en_tabla:
                en_tabla = True
                out.append('<div class="table-wrap"><table><tbody>')

            out.append("<tr>" + "".join(f"<td>{_escape_html(c)}</td>" for c in cols) + "</tr>")
            continue

        # cerrar tabla si veníamos de una
        if en_tabla:
            out.append("</tbody></table></div>")
            en_tabla = False

        if linea.strip():
            linea = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", linea)
            out.append(f"<p>{linea}</p>")

    if en_tabla:
        out.append("</tbody></table></div>")

    return "\n".join(out)


# -------------------------------------------------
# GENERADOR HTML FINAL
# -------------------------------------------------
def generar_informe_html(
    marca: str,
    modelo: str,
    informe_texto: str,
    lista_fotos: list,
    texto_ubicacion: str,
    vendedor: str = "",
) -> bytes:

    fecha_hoy = datetime.datetime.now().strftime("%d/%m/%Y")

    # --- METRICS ---
    block_rf = _extraer_bloque_resultado_final(informe_texto or "")
    valor_mercado = _extraer_entero(block_rf, "VALOR_MERCADO")
    precio_venta = _extraer_entero(block_rf, "PRECIO_VENTA")
    precio_compra = _extraer_entero(block_rf, "PRECIO_COMPRA")

    metrics_html = f"""
    <div class="metrics">
      <div class="metric">
        <div class="metric-label">VALOR_MERCADO</div>
        <div class="metric-value">{_fmt_eur(valor_mercado)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">PRECIO_VENTA</div>
        <div class="metric-value">{_fmt_eur(precio_venta)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">PRECIO_COMPRA</div>
        <div class="metric-value">{_fmt_eur(precio_compra)}</div>
      </div>
    </div>
    """

    comparables_tabla = _extraer_bloque_comparables_tabla(informe_texto or "")
    comparables_html = _markdown_tabla_a_html(comparables_tabla) if comparables_tabla else ""

    # Logo
    logo_b64 = cargar_logo_b64("Transparente.png")
    logo_html = f'<img class="logo" src="{logo_b64}">' if logo_b64 else ""

    # Ubicación (viene en base64)
    ubicacion_html = ""
    try:
        if texto_ubicacion:
            ubic_txt = base64.b64decode(texto_ubicacion.encode("utf-8")).decode("utf-8")
            if ubic_txt.strip():
                ubicacion_html = f'<div class="subtitle">{_escape_html(ubic_txt)}</div>'
    except Exception:
        ubicacion_html = ""

    # FOTOS
    fotos_html = ""
    for foto in (lista_fotos or []):
        # Soporta dos formatos:
        # - PIL.Image (flujo antiguo)
        # - dict con bytes ya normalizados: {"data": b"...", "type": "image/jpeg", ...}
        if isinstance(foto, dict) and "data" in foto:
            data = foto.get("data") or b""
            img_b64 = base64.b64encode(data).decode("utf-8") if data else ""
        else:
            img_b64 = _img_to_b64_jpg(foto)
        fotos_html += f'<img class="photo" src="data:image/jpeg;base64,{img_b64}">'

    vendedor_html = f'<div class="user">👤 {vendedor}</div>' if vendedor else ""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tasación - {marca} {modelo}</title>

<style>
:root {{
  --bg:#e8f3e8; --card:#fff; --green:#2e7d32;
  --text:#1f2937; --muted:#6b7280; --border:rgba(0,0,0,.08);
}}

body {{ margin:0; font-family:Segoe UI,Arial; background:var(--bg); }}
.page {{ max-width:980px; margin:auto; padding:22px 16px 40px; }}

.header {{
  background:#dff0df; border:1px solid var(--border); border-radius:12px;
  padding:16px; display:flex; justify-content:space-between; gap:16px;
}}

.brand {{ display:flex; gap:14px; align-items:center; }}
.logo {{ width:160px; }}
.title {{ margin:0; font-size:20px; color:var(--green); }}
.subtitle {{ font-size:12px; color:var(--muted); }}
.meta {{ font-size:12px; color:var(--muted); text-align:right; }}
.user {{ margin-top:6px; font-weight:600; }}

.metrics {{
  display:grid; grid-template-columns: repeat(3, 1fr);
  gap:12px; margin:14px 0;
}}
.metric {{
  background:var(--card); border:1px solid var(--border); border-radius:12px;
  padding:12px;
}}
.metric-label {{ font-size:12px; color:var(--muted); }}
.metric-value {{ font-size:18px; font-weight:800; color:var(--text); margin-top:6px; }}

.card {{
  background:var(--card); border:1px solid var(--border); border-radius:12px;
  padding:14px; margin-top:12px;
}}
.h2 {{ margin:0 0 10px; color:var(--text); font-size:15px; }}

.table-wrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; }}
td {{ border:1px solid var(--border); padding:8px; font-size:12px; }}

.photos {{
  display:grid; grid-template-columns: repeat(3, 1fr);
  gap:10px; margin-top:10px;
}}
.photo {{
  width:100%; border-radius:10px; border:1px solid var(--border);
  object-fit:cover;
}}
@media (max-width: 900px) {{
  .metrics {{ grid-template-columns: 1fr; }}
  .photos {{ grid-template-columns: 1fr 1fr; }}
}}
</style>
</head>

<body>
<div class="page">

  <div class="header">
    <div class="brand">
      {logo_html}
      <div>
        <h1 class="title">Tasación - {marca} {modelo}</h1>
        <div class="subtitle">Fecha: {fecha_hoy}</div>
        {ubicacion_html}
      </div>
    </div>
    <div class="meta">
      {vendedor_html}
    </div>
  </div>

  {metrics_html}

  <div class="card">
    <div class="h2">Informe IA</div>
    <div style="white-space:pre-wrap; font-size:12px; color:var(--text);">{_escape_html(informe_texto)}</div>
  </div>

  {"<div class='card'><div class='h2'>Comparables</div>" + comparables_html + "</div>" if comparables_html else ""}

  <div class="card">
    <div class="h2">Fotos</div>
    <div class="photos">
      {fotos_html}
    </div>
  </div>

</div>
</body>
</html>
"""
    return html.encode("utf-8")