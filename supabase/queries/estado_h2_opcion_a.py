#!/usr/bin/env python3
"""
Consulta: estado_h2_opcion_a (v2)

Reporta:
- Cantidad de seeds capturados con views_primeras_3h (tabla youtube_shorts_log)
- Cantidad de filas en trending_cola con oportunidad='cola_sports_urgente' y categoria='sports'
"""

def run(client):
    """
    Ejecuta consultas de estado para H2 y Opción A.
    
    Args:
        client: Cliente de Supabase
        
    Returns:
        dict con los resultados de las consultas
    """
    # 1. Contar seeds capturados en youtube_shorts_log (con views_primeras_3h != null)
    log_response = client.table("youtube_shorts_log").select("id", count="exact").not_.is_("views_primeras_3h", None).execute()
    seeds_capturados = log_response.count if hasattr(log_response, 'count') else 0
    
    # 2. Contar filas en trending_cola con oportunidad='cola_sports_urgente' y categoria='sports'
    cola_response = client.table("trending_cola").select("id", count="exact").eq("oportunidad", "cola_sports_urgente").eq("categoria", "sports").execute()
    cola_sports_urgente = cola_response.count if hasattr(cola_response, 'count') else 0
    
    # 3. caducidad_hs vive en trending_cola (migración Opción A)
    try:
        caducidad_response = client.table("trending_cola").select("caducidad_hs").limit(1).execute()
        tiene_caducidad_hs = True
    except Exception:
        tiene_caducidad_hs = False
    
    # 4. items sports en trending_cola
    sports_response = client.table("trending_cola").select("id", count="exact").eq("categoria", "sports").execute()
    items_sports_en_cola = sports_response.count if hasattr(sports_response, 'count') else 0
    
    return {
        "seeds_capturados": seeds_capturados,
        "items_en_cola_sports_urgente": cola_sports_urgente,
        "tiene_caducidad_hs": tiene_caducidad_hs,
        "items_sports_en_cola": items_sports_en_cola
    }
