import pandas as pd

def calcular_valor_extras(cv, ruedas_malas, pala, anclajes, tripuntal, tdf, compresor, kg_contrapesos):
    try:
        # Cargamos la tabla del repo
        df = pd.read_csv('tablas_precios_referencia.csv')
        # Convertimos a diccionario para buscar rápido: { 'Pala Usada': 41.6, ... }
        precios = dict(zip(df.Componente, df.Factor_EUR_CV))
    except:
        # Valores de rescate por si el archivo falla
        precios = {
            "Ruedas": 70.0, "Pala": 41.6, "Anclajes": 16.6, 
            "Tripuntal": 20.8, "Tripuntal_TDF": 25.0, "Compresor": 1000.0
        }

    total = 0
    # Lógica de cálculo
    if ruedas_malas: total -= (cv * precios.get("Ruedas (Castigo)", 70.0))
    if pala:         total += (cv * precios.get("Pala Usada", 41.6))
    if anclajes:     total += (cv * precios.get("Anclajes", 16.6))
    if tdf:          total += (cv * precios.get("Tripuntal + TDF", 25.0))
    elif tripuntal:  total += (cv * precios.get("Tripuntal", 20.8))
    
    if compresor:    total += precios.get("Compresor Aire", 1000.0)
    total += (kg_contrapesos * 1.0) # Contrapesos a 1€/kg
    
    return total
