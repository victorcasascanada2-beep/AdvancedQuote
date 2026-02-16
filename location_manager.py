import base64

def codificar_coordenadas(lat, lon):
    """
    Recibe: 41.503, -5.75
    Devuelve: NDEuNTAzLC01Ljc1 (Base64 puro)
    """
    if lat is None or lon is None:
        return "PENDIENTE"
        
    # 1. Creamos el string de coordenadas puras
    datos_raw = f"{lat},{lon}"
    
    # 2. Lo convertimos a Base64 sin ningún texto extra
    b64 = base64.b64encode(datos_raw.encode()).decode()
    
    return b64
