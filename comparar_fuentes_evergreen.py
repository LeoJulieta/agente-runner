"""
One-off manual: compara fuentes de trafico entre evergreen ganadores y
flojos (sesion 18/8, pedido de Qwen). Correr una sola vez, no es parte del
ciclo automatico. Requiere las mismas credenciales YouTube que ya usa
sincronizar_metricas() en el pipeline (YOUTUBE_REFRESH_TOKEN con scope
yt-analytics.readonly).

Los 6 IDs salen de Supabase con el criterio acordado: angulo LIKE
'Evergreen deep-dive%', publicados hace 7+ dias (views estabilizadas),
top 3 por views vs 3 con 2-10 views de dias distintos (no 0 views -- un
video con 0 views no genera filas en el reporte de fuente de trafico,
no serviria para comparar). Se descartaron los primeros 3 flojos elegidos
(0 views, todos del 11/8) porque ese dia se publicaron 16 evergreens con
hasta 3 repeticiones del mismo topic en 24h (antes del cooldown de 6h en
produccion) -- se canibalizaban entre si, no era representativo del
criterio evergreen en general.
"""
from youtube_uploader import obtener_access_token
from youtube_shorts_agent import obtener_fuentes_trafico_por_video

GANADORES = {
    "GJZcz6HjUSc": "Shocking Buys Poor People Make (204 views, 30/7)",
    "__ImqejTjr0": "Shocking: 5 Kidney Danger Signs (87 views, 10/8)",
    "n3HTzl9SMio": "Shocking Places Gravity Doesn't Work (56 views, 6/8)",
}
FLOJOS = {
    "3k7LWIGYATk": "Money Habits Keeping You Poor (2 views, 5/8)",
    "EiVdANR0g4U": "Signs They're Secretly Jealous (4 views, 2/8)",
    "jiFTqVKENrw": "Animals You Never Knew Existed (8 views, 1/8)",
}

if __name__ == "__main__":
    token = obtener_access_token()
    if not token:
        print("No se pudo obtener access_token -- revisar YOUTUBE_REFRESH_TOKEN.")
        raise SystemExit(1)

    todos_ids = list(GANADORES.keys()) + list(FLOJOS.keys())
    resultado = obtener_fuentes_trafico_por_video(token, todos_ids, dias=30)

    print("\n=== GANADORES ===")
    for vid, label in GANADORES.items():
        print(f"{vid} -- {label}")
        print(f"  {resultado.get(vid, 'sin datos')}")

    print("\n=== FLOJOS ===")
    for vid, label in FLOJOS.items():
        print(f"{vid} -- {label}")
        print(f"  {resultado.get(vid, 'sin datos')}")

    print(
        "\nH1 (>=85% feed en ambos grupos): la premisa 'search demand' esta "
        "muerta -- criterio pasa a ser curiosity gap.\n"
        "H2 (ganadores >20% busqueda): search demand se mantiene solo para "
        "ese subtipo de evergreen."
    )
