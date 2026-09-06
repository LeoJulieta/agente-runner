"""
importar_studio_export.py

Reemplaza el proceso manual de "Leo exporta un ZIP de YouTube Studio, lo sube
a Claude, Claude lo analiza y arma el UPDATE a mano" por un script que hace
lo mismo solo, sin intervencion humana ni de LLM.

USO:
  Colocar el .zip exportado desde YouTube Studio (Analytics -> Contenido ->
  Exportar informe actual) en la carpeta studio_zips_pendientes/. Correr
  este script -- procesa TODOS los .zip de esa carpeta, actualiza
  ctr_real e impresiones_miniatura en yt_trends_history (matcheando por
  youtube_video_id), y mueve los .zip ya procesados a
  studio_zips_pendientes/procesados/.

QUE TRAE EL ZIP (3 archivos, se usa solo "Datos de la tabla.csv"):
  - Totales.csv: views por dia, agregado de canal -- no se usa aca.
  - Datos del gráfico.csv: views por dia POR VIDEO -- no se usa aca (es la
    serie temporal, no el agregado final).
  - Datos de la tabla.csv: 1 fila por video con el agregado del periodo
    exportado -- ESTE es el que importa: Contenido (=youtube_video_id),
    Duracion, Visualizaciones, Impresiones, Porcentaje de clics de las
    impresiones (%) -- este ultimo es el CTR REAL que la YouTube Analytics
    API viene devolviendo 400 para esta cuenta (ver sesion 21) -- via este
    export si esta disponible.

IMPORTANTE: esto es un UPDATE, no un INSERT -- solo actualiza videos que ya
existen en yt_trends_history (publicados por el pipeline). Videos del CSV
que no matcheen ningun youtube_video_id existente se listan al final del
log pero no generan error -- es normal, pasa con videos muy viejos o de
antes de que existiera la tabla.
"""
import os
import glob
import shutil
import zipfile
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

CARPETA_PENDIENTES = "studio_zips_pendientes"
CARPETA_PROCESADOS = os.path.join(CARPETA_PENDIENTES, "procesados")
NOMBRE_CSV_TABLA = "Datos de la tabla.csv"


def parsear_zip(path_zip):
    import csv
    import io
    filas = []
    with zipfile.ZipFile(path_zip) as z:
        nombre_real = next((n for n in z.namelist() if n.endswith(NOMBRE_CSV_TABLA)), None)
        if not nombre_real:
            print(f"  {os.path.basename(path_zip)}: no se encontro '{NOMBRE_CSV_TABLA}' adentro, se salta.")
            return []
        with z.open(nombre_real) as f:
            texto = io.TextIOWrapper(f, encoding="utf-8")
            reader = csv.DictReader(texto)
            for r in reader:
                video_id = r.get("Contenido", "").strip()
                if not video_id or video_id == "Total":
                    continue
                try:
                    ctr_pct = r.get("Porcentaje de clics de las impresiones (%)", "0") or "0"
                    impresiones = r.get("Impresiones", "0") or "0"
                    filas.append({
                        "video_id": video_id,
                        "ctr_real": round(float(ctr_pct) / 100, 4),
                        "impresiones": int(impresiones),
                    })
                except (ValueError, TypeError):
                    continue
    return filas


def actualizar_supabase(filas):
    actualizados = 0
    sin_match = []
    for f in filas:
        try:
            resp = (
                supabase.table("yt_trends_history")
                .update({"ctr_real": f["ctr_real"], "impresiones_miniatura": f["impresiones"]})
                .eq("youtube_video_id", f["video_id"])
                .execute()
            )
            if resp.data:
                actualizados += 1
            else:
                sin_match.append(f["video_id"])
        except Exception as e:
            print(f"  Error actualizando {f['video_id']}: {e}")
    return actualizados, sin_match


def main():
    os.makedirs(CARPETA_PROCESADOS, exist_ok=True)
    archivos = glob.glob(os.path.join(CARPETA_PENDIENTES, "*.zip"))
    if not archivos:
        print(f"Sin ZIPs nuevos en {CARPETA_PENDIENTES}/ -- nada para hacer.")
        return

    print(f"Encontrados {len(archivos)} ZIPs para procesar.\n")
    todas_las_filas = []
    for path in archivos:
        filas = parsear_zip(path)
        print(f"  {os.path.basename(path)}: {len(filas)} videos con datos")
        todas_las_filas.extend(filas)

    # Dedup: si el mismo video aparece en 2 exports (rangos de fecha
    # superpuestos), se queda con el que tenga mas impresiones (mas dato
    # acumulado, mas reciente/completo)
    mejores = {}
    for f in todas_las_filas:
        if f["video_id"] not in mejores or f["impresiones"] > mejores[f["video_id"]]["impresiones"]:
            mejores[f["video_id"]] = f
    filas_finales = list(mejores.values())
    print(f"\nTotal parseado: {len(todas_las_filas)} filas, {len(filas_finales)} unicas tras deduplicar")

    actualizados, sin_match = actualizar_supabase(filas_finales)
    print(f"\nActualizados en Supabase: {actualizados} | Sin match (video no encontrado): {len(sin_match)}")
    if sin_match:
        print(f"  IDs sin match (normal si son videos viejos): {sin_match[:10]}{'...' if len(sin_match) > 10 else ''}")

    for path in archivos:
        shutil.move(path, os.path.join(CARPETA_PROCESADOS, os.path.basename(path)))
    print(f"\n{len(archivos)} archivos movidos a {CARPETA_PROCESADOS}/ (no se reprocesan en la proxima corrida).")


if __name__ == "__main__":
    main()
