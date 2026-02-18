import base64
from io import BytesIO
from PIL import Image
import re
import datetime

# -------------------------------------------------
# UTILIDADES IMÁGENES
# -------------------------------------------------

def procesar_logo_b64(ruta_logo: str) -> str:
    """Carga el logo desde el repo y lo convierte a Base64."""
    try:
        with Image.open(ruta_logo) as img:
            buffered = BytesIO()
            # No reducimos tanto la calidad para el logo
            img.save(buffered, format="PNG") 
            return base64.b64encode(buffered.getvalue()).decode()
    except Exception as e:
        print(f"Error cargando el logo: {e}")
        return ""

def procesar_foto_b64(foto: Image.Image) -> str:
    """Reduce peso de foto y la convierte a Base64."""
    buffered = BytesIO()
    foto.thumbnail((800, 800))
    if foto.mode in ("RGBA", "P"):
        foto = foto.convert("RGB")
    foto.save(buffered, format="JPEG", quality=70, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode()

# (Tu función formatear_contenido se mantiene igual)

# -------------------------------------------------
# GENERADOR HTML FINAL CON LOGO
# -------------------------------------------------

def generar_informe_html(marca: str, modelo: str, informe_texto: str, lista_fotos: list, texto_ubicacion: str, ruta_logo: str = "transparente.png") -> bytes:
    
    # 1. Procesar Logo
    logo_b64 = procesar_logo_b64(ruta_logo)
    logo_tag = f'<img src="data:image/png;base64,{logo_b64}" style="height: 60px;">' if logo_b64 else ""

    # 2. Procesar Fotos
    fotos_html = ""
    for foto in lista_fotos:
        img_b64 = procesar_foto_b64(foto)
        fotos_html += (
            f'<img src="data:image/jpeg;base64,{img_b64}" '
            f'style="width:48%;margin:1%;border-radius:5px;border:1px solid #ddd;" loading="lazy">'
        )

    contenido_final = formatear_contenido(informe_texto)
    fecha_hoy = datetime.datetime.now().strftime("%d/%m/%Y")

    html_template = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; color: #333; background-color: #f4f4f4; }}
        .container {{ background-color: white; max-width: 850px; margin: auto; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
        
        /* HEADER CON LOGO */
        .header {{ 
            display: flex; 
            align-items: center; 
            justify-content: space-between; 
            border-bottom: 4px solid #2e7d32; 
            padding-bottom: 20px; 
            margin-bottom: 30px; 
        }}
        .header-logo {{ flex: 1; text-align: left; }}
        .header-title {{ flex: 2; text-align: right; }}
        
        .header h1 {{ color: #2e7d32; margin: 0; font-size: 24px; text-transform: uppercase; }}
        .content {{ line-height: 1.6; font-size: 15px; color: #444; }}
        
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th {{ background-color: #2e7d32; color: white; padding: 10px; text-align: left; }}
        td {{ padding: 8px; border: 1px solid #eee; }}
        tr:nth-child(even) {{ background-color: #fcfcfc; }}
        
        .gallery {{ text-align: center; margin-top: 30px; padding: 20px; border: 1px solid #eee; border-radius: 10px; }}
        .footer {{ margin-top: 50px; text-align: center; border-top: 1px solid #eee; padding-top: 20px; }}
        .ref-tasacion {{ color: #bbb; font-family: monospace; font-size: 10px; margin-top: 10px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-logo">
                {logo_tag}
            </div>
            <div class="header-title">
                <h1>Agrícola Noroeste</h1>
                <p style="font-weight:bold;margin:5px 0; color:#666;">INFORME DE TASACIÓN</p>
                <p style="margin:0; font-size:13px;"><strong>Activo:</strong> {marca} {modelo} | <strong>Fecha:</strong> {fecha_hoy}</p>
            </div>
        </div>

        <div class="content">
            {contenido_final}
        </div>

        <div class="gallery">
            <h4 style="color:#2e7d32;margin-top:0;">Registro Fotográfico</h4>
            {fotos_html}
        </div>

        <div class="footer">
            <p style="color:#888; font-size: 12px;">Este documento es un análisis técnico para uso interno comercial.</p>
            <div class="ref-tasacion">
                Ref Tasación: {texto_ubicacion}
            </div>
        </div>
    </div>
</body>
</html>
"""
    return html_template.encode("utf-8")
