import base64
from io import BytesIO
from PIL import Image
import re
import datetime
import os


# -------------------------------------------------
# UTILIDADES IMÁGENES
# -------------------------------------------------
def _img_to_b64_jpg(img: Image.Image, max_size=(900, 900), quality=75) -> str:
    """Convierte PIL Image a base64 JPG optimizado."""
    buffered = BytesIO()
    img = img.copy()
    img.thumbnail(max_size)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buffered, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode()


def cargar_logo_b64(path: str) -> str:
    """
    Carga un logo local y lo devuelve como DATA URI listo para <img src="...">.
    - Si tiene transparencia (alpha) => PNG (no negro).
    - Si no => JPG optimizado.
    """
    if not path or not os.path.exists(path):
        return ""

    try:
        with Image.open(path) as img:
            img = img.copy()
            img.thumbnail((520, 260))
            buffered = BytesIO()

            has_alpha = (
                img.mode in ("RGBA", "LA") or
                (img.mode == "P" and "transparency" in img.info)
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
# FORMATEO TEXTO IA → HTML (manteniendo tablas markdown)
# -------------------------------------------------
def formatear_contenido(texto: str) -> str:
    """
    Convierte Markdown simple a HTML:
    - Tablas markdown con pipes -> <table>
    - Negritas **texto** -> <b>
    - Saltos a <p>
    """
    if not texto:
        return ""

    lineas = texto.split("\n")
    out = []
    en_tabla = False

    for linea in lineas:
        # tabla markdown (pipes)
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
                # separador de cabecera de tabla markdown
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
# GENERADOR HTML FINAL (estilo “pantalla”, sin botones)
# -------------------------------------------------
def generar_informe_html(
    marca: str,
    modelo: str,
    informe_texto: str,
    lista_fotos: list,
    texto_ubicacion: str,
    vendedor: str = "",
) -> bytes:
    """
    Genera HTML con estilo tipo “app”:
    - Fondo verde claro
    - Cabecera con logo + título
    - Secciones tipo tarjeta
    - Sin botones
    """

    fecha_hoy = datetime.datetime.now().strftime("%d/%m/%Y")
    contenido_final = formatear_contenido(informe_texto or "")

    # Logo (mismo nombre que usas en Streamlit)
    logo_b64 = cargar_logo_b64("Transparente.png")

    # Galería
    fotos_html = ""
    for foto in (lista_fotos or []):
        img_b64 = _img_to_b64_jpg(foto, max_size=(900, 900), quality=72)
        fotos_html += (
            f'<img class="photo" src="data:image/jpeg;base64,{img_b64}" loading="lazy" alt="Foto">'
        )

    logo_html = ""
    if logo_b64:
        logo_html = f'<img class="logo" src="data:image/jpeg;base64,{logo_b64}" alt="Agrícola Noroeste">'

    vendedor_html = f'<div class="user">👤 {vendedor}</div>' if (vendedor or "").strip() else ""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tasación - {marca} {modelo}</title>
  <style>
    :root {{
      --bg: #e8f3e8;
      --card: #ffffff;
      --green: #2e7d32;
      --green2: #1f6b27;
      --text: #1f2937;
      --muted: #6b7280;
      --border: rgba(0,0,0,0.08);
    }}

    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}

    .page {{
      max-width: 980px;
      margin: 0 auto;
      padding: 22px 16px 40px;
    }}

    /* CABECERA */
    .header {{
      background: #dff0df;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}

    .brand {{
      display: flex;
      align-items: center;
      gap: 14px;
      min-width: 0;
    }}

    .logo {{
      width: 150px;
      height: auto;
      display: block;
    }}

    .title-wrap {{
      min-width: 0;
    }}

    .title {{
      margin: 0;
      font-size: 20px;
      font-weight: 800;
      color: var(--green2);
    }}

    .subtitle {{
      margin: 4px 0 0;
      font-size: 12px;
      color: var(--muted);
    }}

    .meta {{
      text-align: right;
      font-size: 12px;
      color: var(--muted);
      white-space: nowrap;
    }}

    .user {{
      margin-top: 6px;
      font-size: 12px;
      color: var(--text);
      font-weight: 600;
    }}

    .divider {{
      height: 1px;
      background: rgba(0,0,0,0.12);
      margin: 14px 0 16px;
      border: 0;
    }}

    /* “alert” */
    .status {{
      background: #dff6e5;
      border: 1px solid rgba(46,125,50,0.25);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 13px;
      margin-top: 14px;
    }}

    /* CARDS */
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 16px;
      margin-top: 14px;
    }}

    .card h2 {{
      margin: 0 0 10px;
      font-size: 16px;
      color: var(--text);
    }}

    .content p {{
      margin: 0 0 10px;
      line-height: 1.45;
      font-size: 13px;
      color: #2b2f36;
    }}

    /* TABLAS markdown */
    .table-wrap {{
      overflow-x: auto;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #fff;
      margin: 10px 0 12px;
    }}
    table.md-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    table.md-table th {{
      background: var(--green);
      color: #fff;
      text-align: left;
      padding: 10px;
      font-weight: 700;
    }}
    table.md-table td {{
      padding: 8px 10px;
      border-top: 1px solid rgba(0,0,0,0.06);
      white-space: nowrap;
    }}
    table.md-table tr:nth-child(even) td {{
      background: #fafafa;
    }}

    /* GALERÍA */
    .gallery {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .photo {{
      width: calc(50% - 5px);
      border-radius: 10px;
      border: 1px solid rgba(0,0,0,0.12);
      background: #fff;
      object-fit: cover;
    }}

    /* FOOTER */
    .footer {{
      margin-top: 18px;
      text-align: center;
      color: var(--muted);
      font-size: 11px;
    }}
    .ref {{
      margin-top: 6px;
      color: #9aa3af;
      font-family: monospace;
      font-size: 10px;
      word-break: break-all;
    }}

    @media (max-width: 650px) {{
      .header {{
        flex-direction: column;
        align-items: flex-start;
      }}
      .meta {{
        text-align: left;
      }}
      .photo {{
        width: 100%;
      }}
      .logo {{
        width: 170px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">

    <div class="header">
      <div class="brand">
        {logo_html}
        <div class="title-wrap">
          <h1 class="title">Tasación de maquinaria</h1>
          <div class="subtitle">Agrícola Noroeste · Valoración orientativa basada en estado, horas y mercado</div>
          {vendedor_html}
        </div>
      </div>
      <div class="meta">
        <div><b>Activo:</b> {marca} {modelo}</div>
        <div><b>Fecha:</b> {fecha_hoy}</div>
      </div>
    </div>

    <div class="status">✅ Informe generado y preparado para archivo.</div>

    <div class="card">
      <h2>Resultado del Análisis (IA)</h2>
      <div class="content">
        {contenido_final}
      </div>
    </div>

    <div class="card">
      <h2>Registro fotográfico</h2>
      <div class="gallery">
        {fotos_html}
      </div>
    </div>

    <div class="footer">
      Este documento es un análisis técnico para uso interno comercial.
      <div class="ref">Ref Tasación: {texto_ubicacion}</div>
    </div>

  </div>
</body>
</html>
"""
    return html.encode("utf-8")
