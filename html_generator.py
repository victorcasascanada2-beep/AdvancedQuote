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
    """Convierte PIL Image a base64 JPG optimizado (solo para FOTOS)."""
    buffered = BytesIO()
    img = img.copy()
    img.thumbnail(max_size)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buffered, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode()


def cargar_logo_b64(path: str) -> str:
    """
    Carga un logo local y devuelve un DATA URI listo para <img src="...">.
    - Si tiene transparencia -> PNG (respeta alpha)
    - Si no -> JPG
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
# FORMATEO TEXTO IA → HTML
# -------------------------------------------------
def formatear_contenido(texto: str) -> str:
    """Convierte Markdown simple en HTML (tablas + negritas)."""
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
) -> bytes:
    """Genera HTML final estilo app (sin botones)."""

    fecha_hoy = datetime.datetime.now().strftime("%d/%m/%Y")
    contenido_final = formatear_contenido(informe_texto or "")

    # LOGO (PNG transparente)
    logo_src = cargar_logo_b64("Transparente.png")
    logo_html = (
        f'<img class="logo" src="{logo_src}" alt="Agrícola Noroeste">'
        if logo_src
        else ""
    )

    # Fotos
    fotos_html = ""
    for foto in (lista_fotos or []):
        img_b64 = _img_to_b64_jpg(foto, max_size=(900, 900), quality=72)
        fotos_html += f'<img class="photo" src="data:image/jpeg;base64,{img_b64}" alt="Foto">'

    vendedor_html = f'<div class="user">👤 {vendedor}</div>' if vendedor else ""

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
  --text: #1f2937;
  --muted: #6b7280;
  --border: rgba(0,0,0,.08);
}}

body {{
  margin: 0;
  font-family: "Segoe UI", Arial, sans-serif;
  background: var(--bg);
}}

.page {{
  max-width: 980px;
  margin: auto;
  padding: 22px 16px 40px;
}}

.header {{
  background: #dff0df;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
}}

.brand {{
  display: flex;
  gap: 14px;
  align-items: center;
}}

.logo {{
  width: 160px;
}}

.title {{
  margin: 0;
  font-size: 20px;
  color: var(--green);
}}

.subtitle {{
  font-size: 12px;
  color: var(--muted);
}}

.meta {{
  font-size: 12px;
  color: var(--muted);
  text-align: right;
}}

.user {{
  margin-top: 6px;
  font-weight: 600;
}}

.card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
  margin-top: 14px;
}}

.gallery {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}}

.photo {{
  width: calc(50% - 5px);
  border-radius: 10px;
  border: 1px solid var(--border);
}}

.footer {{
  margin-top: 20px;
  text-align: center;
  font-size: 11px;
  color: var(--muted);
}}

.ref {{
  font-family: monospace;
  font-size: 10px;
  margin-top: 6px;
}}

@media (max-width: 650px) {{
  .header {{
    flex-direction: column;
    align-items: flex-start;
  }}
  .photo {{
    width: 100%;
  }}
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
