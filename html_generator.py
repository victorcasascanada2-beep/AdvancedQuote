import base64
from io import BytesIO
from PIL import Image
import re
import datetime

# -------------------------------------------------
# UTILIDADES IMÁGENES
# -------------------------------------------------

def procesar_foto_b64(foto: Image.Image) -> str:
    """Reduce peso de foto y la convierte a Base64 para incrustar en HTML."""
    buffered = BytesIO()
    # Mantenemos un tamaño razonable para que el PDF no explote
    foto.thumbnail((800, 800))
    if foto.mode in ("RGBA", "P"):
        foto = foto.convert("RGB")
    foto.save(buffered, format="JPEG", quality=70, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode()

# -------------------------------------------------
# FORMATEO TEXTO IA → HTML
# -------------------------------------------------

def formatear_contenido(texto: str) -> str:
    """Convierte Markdown simple en HTML profesional."""
    lineas = texto.split('\n')
    resultado = []
    en_tabla = False

    for linea in lineas:
        if '|' in linea:
            columnas = [c.strip() for c in linea.split('|') if c.strip()]
            if not columnas: continue

            if not en_tabla:
                resultado.append('<div style="overflow-x:auto;"><table><thead><tr>')
                for col in columnas:
                    resultado.append(f'<th>{col}</th>')
                resultado.append('</tr></thead><tbody>')
                en_tabla = True
            elif '---' in linea:
                continue
            else:
                resultado.append('<tr>')
                for col in columnas:
                    resultado.append(f'<td>{col}</td>')
                resultado.append('</tr>')
        else:
            if en_tabla:
                resultado.append('</tbody></table></div>')
                en_tabla = False

            if linea.strip():
                # Negritas de Markdown a HTML
                linea_formateada = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', linea)
                resultado.append(f'<p>{linea_formateada}</p>')

    if en_tabla:
        resultado.append('</tbody></table></div>')

    return '\n'.join(resultado)

# -------------------------------------------------
# GENERADOR HTML FINAL
# -------------------------------------------------

def generar_informe_html(marca: str, modelo: str, informe_texto: str, lista_fotos: list, texto_ubicacion: str) -> bytes:
    """Genera el HTML final con la Ref Tasación discreta en el pie."""

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
        .header {{ text-align: center; border-bottom: 4px solid #2e7d32; padding-bottom: 20px; margin-bottom: 30px; }}
        .header h1 {{ color: #2e7d32; margin: 0; font-size: 28px; text-transform: uppercase; }}
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
            <h1>Agrícola Noroeste</h1>
            <p style="font-weight:bold;margin:10px 0;">INFORME DE TASACIÓN PROFESIONAL</p>
            <p><strong>Activo:</strong> {marca} {modelo} | <strong>Fecha:</strong> {fecha_hoy}</p>
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
