import os
import re
import base64
import datetime
from io import BytesIO

from PIL import Image


def _extraer_bloque_resultado_final(texto: str) -> str:
    m = re.search(r"BLOQUE:\s*RESULTADO_FINAL(.*?)(?:BLOQUE:|$)", texto, flags=re.S | re.I)
    return m.group(1).strip() if m else ""


def _extraer_entero(block: str, key: str):
    mm = re.search(rf"{re.escape(key)}\s*:\s*([0-9\.\,]+)", block)
    if not mm:
        return None
    return int(float(mm.group(1).replace(".", "").replace(",", ".")))


def _extraer_bloque_comparables_tabla(texto: str) -> str:
    m = re.search(r"BLOQUE:\s*COMPARABLES_TABLA(.*?)(?:BLOQUE:|$)", texto, flags=re.S | re.I)
    return m.group(1).strip() if m else ""


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

        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            buf = BytesIO()
            img.save(buf, format="PNG", optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f"data:image/png;base64,{b64}"

        buf = BytesIO()
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=85, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"

    except Exception:
        return ""


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
        <div class="metric-title">Valor de mercado</div>
        <div class="metric-value">{valor_mercado if valor_mercado is not None else "N/D"} €</div>
      </div>
      <div class="metric">
        <div class="metric-title">Precio recomendado venta</div>
        <div class="metric-value">{precio_venta if precio_venta is not None else "N/D"} €</div>
      </div>
      <div class="metric">
        <div class="metric-title">Precio recomendado compra</div>
        <div class="metric-value">{precio_compra if precio_compra is not None else "N/D"} €</div>
      </div>
    </div>
    """

    # --- COMPARABLES ---
    comparables_tabla = _extraer_bloque_comparables_tabla(informe_texto or "")
    comparables_html = ""
    if comparables_tabla:
        comparables_html = f"""
        <div class="section">
          <h2>Comparables (justificación)</h2>
          <pre class="mono">{comparables_tabla}</pre>
        </div>
        """

    # Logo (si existe)
    logo_b64 = cargar_logo_b64("Transparente.png")
    logo_html = f'<img class="logo" src="{logo_b64}">' if logo_b64 else ""

    ubicacion_html = ""
    try:
        if texto_ubicacion:
            # texto_ubicacion ya viene en base64 (por app.py)
            ubic_txt = base64.b64decode(texto_ubicacion.encode("utf-8")).decode("utf-8")
            if ubic_txt.strip():
                ubicacion_html = f'<div class="ubication">{ubic_txt}</div>'
    except Exception:
        ubicacion_html = ""

    # FOTOS
    fotos_html = ""
    for foto in (lista_fotos or []):
        # Soporta dos formatos:
        # 1) PIL.Image (flujo antiguo)
        # 2) dict con bytes ya normalizados: {"data": b"...", "type": "image/jpeg", ...} (flujo optimizado)
        if isinstance(foto, dict) and "data" in foto:
            data = foto.get("data") or b""
            img_b64 = base64.b64encode(data).decode() if data else ""
        else:
            img_b64 = _img_to_b64_jpg(foto)
        fotos_html += f'<img class="photo" src="data:image/jpeg;base64,{img_b64}">'

    vendedor_html = f'<div class="user">👤 {vendedor}</div>' if vendedor else ""

    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width, initial-scale=1"/>
      <title>Tasación {marca} {modelo}</title>
      <style>
        body {{
          font-family: Arial, sans-serif;
          margin: 24px;
          color: #111;
        }}
        .header {{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:16px;
          border-bottom: 1px solid #ddd;
          padding-bottom: 12px;
          margin-bottom: 18px;
        }}
        .logo {{
          height: 48px;
          object-fit: contain;
        }}
        .title {{
          font-size: 20px;
          font-weight: 700;
        }}
        .sub {{
          font-size: 13px;
          color: #444;
        }}
        .user {{
          font-size: 13px;
          color: #333;
          padding: 6px 10px;
          border: 1px solid #ddd;
          border-radius: 8px;
          background: #fafafa;
        }}
        .ubication {{
          font-size: 12px;
          color: #444;
          margin-top: 6px;
        }}
        .metrics {{
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 12px;
          margin: 18px 0;
        }}
        .metric {{
          border: 1px solid #ddd;
          border-radius: 12px;
          padding: 12px;
          background: #fcfcfc;
        }}
        .metric-title {{
          font-size: 12px;
          color: #666;
          margin-bottom: 6px;
        }}
        .metric-value {{
          font-size: 18px;
          font-weight: 700;
        }}
        .section {{
          margin-top: 22px;
        }}
        h2 {{
          font-size: 16px;
          margin: 0 0 10px 0;
        }}
        .mono {{
          white-space: pre-wrap;
          background: #0b0b0b;
          color: #f2f2f2;
          padding: 12px;
          border-radius: 10px;
          font-size: 12px;
          overflow-x: auto;
        }}
        .photos {{
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 10px;
          margin-top: 10px;
        }}
        .photo {{
          width: 100%;
          border-radius: 10px;
          border: 1px solid #e4e4e4;
          object-fit: cover;
        }}
        @media (max-width: 900px) {{
          .metrics {{ grid-template-columns: 1fr; }}
          .photos {{ grid-template-columns: 1fr 1fr; }}
        }}
      </style>
    </head>
    <body>
      <div class="header">
        <div>
          {logo_html}
          <div class="title">Tasación {marca} {modelo}</div>
          <div class="sub">Fecha: {fecha_hoy}</div>
          {ubicacion_html}
        </div>
        {vendedor_html}
      </div>

      {metrics_html}

      <div class="section">
        <h2>Informe IA</h2>
        <pre class="mono">{(informe_texto or "").replace("<", "&lt;").replace(">", "&gt;")}</pre>
      </div>

      {comparables_html}

      <div class="section">
        <h2>Fotos</h2>
        <div class="photos">
          {fotos_html}
        </div>
      </div>

    </body>
    </html>
    """

    return html.encode("utf-8")