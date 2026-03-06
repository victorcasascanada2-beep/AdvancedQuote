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


# -------------------------------------------------
# PARSEO RESULTADO_FINAL → METRICS
# -------------------------------------------------
def _extraer_bloque_resultado_final(texto: str) -> str:
    if not texto:
        return ""
    m = re.search(r"(?is)BLOQUE\s*:\s*RESULTADO_FINAL\s*(.*)", texto)
    if not m:
        return ""
    tail = m.group(1)
    m2 = re.search(r"(?is)\n\s*BLOQUE\s*:\s*", tail)
    return tail[: m2.start()] if m2 else tail


def _extraer_entero(block: str, key: str) -> Optional[int]:
    if not block:
        return None
    m = re.search(rf"(?im)^\s*-?\s*{re.escape(key)}\s*:\s*([\-]?\d+)\s*$", block)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _fmt_eur(n: Optional[int]) -> str:
    if n is None:
        return "—"
    s = f"{n:,}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def _fmt_eur_float(n: Optional[float]) -> str:
    if n is None:
        return "—"
    s = f"{round(n):,}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def _quitar_bloque_resultado_final(texto: str) -> str:
    if not texto:
        return ""
    return re.sub(
        r"(?is)BLOQUE\s*:\s*RESULTADO_FINAL\s*.*?(?=\n\s*BLOQUE\s*:|\Z)",
        "",
        texto,
    ).strip()


def _texto_plano_a_html(texto: str) -> str:
    if not texto:
        return ""
    lineas = texto.splitlines()
    out = []
    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue
        linea = (
            linea.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        out.append(f"<p>{linea}</p>")
    return "\n".join(out)


# -------------------------------------------------
# FORMATEO TEXTO IA → HTML
# -------------------------------------------------
def formatear_contenido(texto: str) -> str:
    if not texto:
        return ""

    lineas = texto.split("\n")
    out = []
    en_tabla = False

    for linea in lineas:
        if "|" in linea:
            cols = [c.strip() for c in linea.split("|") if c.strip()]
            if not cols:
                continue

            if not en_tabla:
                out.append('<div class="table-wrap"><table class="md-table"><thead><tr>')
                for c in cols:
                    out.append(f"<th>{c}</th>")
                out.append("</tr></thead><tbody>")
                en_tabla = True
            elif "---" in linea:
                continue
            else:
                out.append("<tr>")
                for c in cols:
                    out.append(f"<td>{c}</td>")
                out.append("</tr>")
        else:
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
    base_dict: Optional[dict] = None,
    extras_total: float = 0.0,
    bloque_extras: str = "",
) -> bytes:

    fecha_hoy = datetime.datetime.now().strftime("%d/%m/%Y")

    # --- METRICS ---
    block_rf = _extraer_bloque_resultado_final(informe_texto or "")
    base_dict = base_dict or {}

    valor_mercado = base_dict.get("VALOR_MERCADO")
    precio_venta = base_dict.get("PRECIO_VENTA")
    precio_compra = base_dict.get("PRECIO_COMPRA")

    if valor_mercado is None:
        valor_mercado = _extraer_entero(block_rf, "VALOR_MERCADO")
    if precio_venta is None:
        precio_venta = _extraer_entero(block_rf, "PRECIO_VENTA")
    if precio_compra is None:
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

    extras_html = ""
    if bloque_extras:
        extras_html = f"""
        <div class="card">
          <h2>Extras / Ajustes (Aparte)</h2>
          <div class="extras-box">
            {_texto_plano_a_html(bloque_extras)}
          </div>
        </div>
        """

    referencia_html = ""
    if valor_mercado is not None:
        ref_mercado = float(valor_mercado) + float(extras_total or 0)
        ref_venta = float(precio_venta or 0) + float(extras_total or 0)
        ref_compra = float(precio_compra or 0) + float(extras_total or 0)

        referencia_html = f"""
        <div class="card">
          <h2>Referencia (base + extras) — solo orientativo</h2>
          <div class="metrics">
            <div class="metric">
              <div class="metric-label">MERCADO + EXTRAS</div>
              <div class="metric-value">{_fmt_eur_float(ref_mercado)}</div>
            </div>
            <div class="metric">
              <div class="metric-label">VENTA + EXTRAS</div>
              <div class="metric-value">{_fmt_eur_float(ref_venta)}</div>
            </div>
            <div class="metric">
              <div class="metric-label">COMPRA + EXTRAS</div>
              <div class="metric-value">{_fmt_eur_float(ref_compra)}</div>
            </div>
          </div>
        </div>
        """

    texto_sin_rf = _quitar_bloque_resultado_final(informe_texto or "")
    contenido_final = formatear_contenido(texto_sin_rf)

    # LOGO
    logo_src = cargar_logo_b64("Transparente.png")
    logo_html = f'<img class="logo" src="{logo_src}">' if logo_src else ""

    # FOTOS
    fotos_html = ""
    for foto in (lista_fotos or []):
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
  display:grid; grid-template-columns:repeat(3,1fr);
  gap:14px; margin-top:14px;
}}
.metric {{
  background:#e6f2e6; border:1px solid var(--border);
  border-radius:12px; padding:14px 16px;
}}
.metric-label {{ font-size:12px; opacity:.8; }}
.metric-value {{
  margin-top:6px; font-size:38px; font-weight:800; line-height:1;
}}

.card {{
  background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:14px; margin-top:14px;
}}

.extras-box {{
  background:#f8fbf8;
  border:1px solid var(--border);
  border-radius:10px;
  padding:12px 14px;
}}
.extras-box p {{
  margin:6px 0;
  white-space:pre-wrap;
}}

.table-wrap {{ overflow-x:auto; }}
table.md-table {{ width:100%; border-collapse:collapse; font-size:12px; }}
table.md-table th {{ background:var(--green); color:#fff; padding:8px; }}
table.md-table td {{ padding:8px; border-top:1px solid #eee; }}

.gallery {{ display:flex; flex-wrap:wrap; gap:10px; }}
.photo {{ width:calc(50% - 5px); border-radius:10px; border:1px solid var(--border); }}

.footer {{ margin-top:20px; text-align:center; font-size:11px; color:var(--muted); }}
.ref {{ font-family:monospace; font-size:10px; }}

@media(max-width:650px){{
  .header {{ flex-direction:column; }}
  .metrics{{ grid-template-columns:1fr; }}
  .photo{{ width:100%; }}
}}
</style>
</head>

<body>
<div class="page">

<div class="header">
  <div class="brand">
    {logo_html}
    <div>
      <h1 class="title">Tasación de maquinaria</h1>
      <div class="subtitle">Agrícola Noroeste · Valoración orientativa</div>
      {vendedor_html}
    </div>
  </div>
  <div class="meta">
    <div><b>Activo:</b> {marca} {modelo}</div>
    <div><b>Fecha:</b> {fecha_hoy}</div>
  </div>
</div>

{metrics_html}
{extras_html}
{referencia_html}

<div class="card">
  <h2>Resultado del análisis</h2>
  {contenido_final}
</div>

<div class="card">
  <h2>Registro fotográfico</h2>
  <div class="gallery">{fotos_html}</div>
</div>

<div class="footer">
  Documento interno · Agrícola Noroeste
  <div class="ref">Ref Tasación: {texto_ubicacion}</div>
</div>

</div>
</body>
</html>
"""
    return html.encode("utf-8")
