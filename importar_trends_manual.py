"""
importar_trends_manual.py

Reemplaza el proceso manual (Leo sube CSV a Claude, Claude parsea a mano y
arma SQL) por un script que hace exactamente lo mismo, sin intervencion
humana ni de LLM. Pensado para correr en GitHub Actions, disparado cuando
Leo sube un CSV nuevo al repo.

USO:
  Colocar los .csv exportados de trends.google.com en la carpeta
  trends_csv_pendientes/ (nombre de archivo esperado tipo Google Trends:
  trending_XX_Nd_YYYYMMDD-HHMM.csv, donde XX es el geo de 2 letras).
  Correr este script -- procesa TODOS los .csv de esa carpeta, los importa
  a trends_manual_import (Supabase) y los mueve a trends_csv_pendientes/procesados/
  para no reprocesarlos la proxima corrida.

LOGICA (identica a la que se uso a mano toda la sesion del 29/7 al 1/8):
  - Parsea el CSV real de Google Trends (columnas: Tendencias, Volumen de
    busquedas, Inicio, Finalizada, Desglose de tendencias).
  - Convierte fechas en español ("27 de julio de 2026 a las 17:10:00 UTC-3")
    a ISO 8601 UTC.
  - Descarta tendencias que no esten mayormente en alfabeto latino (ej. hindi
    en devanagari) -- no sirven para el matching en ingles del canal.
  - Deduplica por tendencia+geo, quedandose con la de mayor volumen.
  - Se queda con el top 60 por geo (no importa el firehose completo, la
    mayoria es ruido de bajo volumen).
  - Trunca keywords_relacionadas a 150 caracteres (no hace falta el desglose
    completo para el uso que se le da).
  - Upsert en trends_manual_import (on_conflict tendencia_norm+geo+ventana),
    asi reimportar el mismo tema no duplica, solo actualiza.
"""
import os
import re
import csv
import glob
import shutil
from datetime import datetime, timezone, timedelta
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

CARPETA_PENDIENTES = "trends_csv_pendientes"
CARPETA_PROCESADOS = os.path.join(CARPETA_PENDIENTES, "procesados")
TOP_POR_GEO = 60

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def parsear_fecha_es(s):
    if not s:
        return None
    m = re.match(r"(\d{1,2}) de (\w+) de (\d{4}) a las (\d{1,2}):(\d{2}):(\d{2}) UTC([+-]\d+)", s)
    if not m:
        return None
    dia, mes_txt, anio, h, mi, se, offset = m.groups()
    mes = MESES.get(mes_txt.lower())
    if not mes:
        return None
    dt = datetime(int(anio), mes, int(dia), int(h), int(mi), int(se), tzinfo=timezone(timedelta(hours=int(offset))))
    return dt.astimezone(timezone.utc).isoformat()


def volumen_a_num(v):
    if not v:
        return 0
    v = v.replace("+", "").strip()
    m = re.match(r"([\d.,]+)\s*(mil|M)?", v)
    if not m:
        return 0
    num = float(m.group(1).replace(".", "").replace(",", "."))
    if m.group(2) == "M":
        return num * 1_000_000
    if m.group(2) == "mil":
        return num * 1_000
    return num


def es_mayormente_latino(s):
    if not s:
        return False
    letras = [c for c in s if c.isalpha()]
    if not letras:
        return False
    latinas = sum(1 for c in letras if ord(c) < 0x250)
    return latinas / len(letras) > 0.7


def extraer_geo_de_nombre(nombre_archivo):
    """trending_US_2d_20260801-1038.csv -> 'US'"""
    m = re.match(r"trending_([A-Z]{2})_", os.path.basename(nombre_archivo))
    return m.group(1) if m else "US"


def extraer_ventana_de_nombre(nombre_archivo):
    """trending_US_2d_20260801-1038.csv -> '2d'"""
    m = re.search(r"_(\d+d)_", os.path.basename(nombre_archivo))
    return m.group(1) if m else "?"


def parsear_csv(path):
    geo = extraer_geo_de_nombre(path)
    ventana = extraer_ventana_de_nombre(path)
    filas = []
    descartadas = 0
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tendencia = (row.get("Tendencias") or "").strip()
            if not tendencia:
                continue
            if not es_mayormente_latino(tendencia):
                descartadas += 1
                continue
            filas.append({
                "tendencia": tendencia,
                "volumen_busqueda": (row.get("Volumen de búsquedas") or "").strip(),
                "geo": geo,
                "ventana": ventana,
                "inicio": parsear_fecha_es((row.get("Inicio") or "").strip()),
                "finalizada": parsear_fecha_es((row.get("Finalizada") or "").strip()),
                "keywords_relacionadas": (row.get("Desglose de tendencias") or "")[:150],
                "_vol_num": volumen_a_num(row.get("Volumen de búsquedas")),
            })
    return filas, descartadas


def curar_top(filas, top_n=TOP_POR_GEO):
    """Dedup por tendencia+geo (se queda con la de mayor volumen), despues top N por geo."""
    mejores = {}
    for r in filas:
        key = (r["tendencia"].lower().strip(), r["geo"])
        if key not in mejores or r["_vol_num"] > mejores[key]["_vol_num"]:
            mejores[key] = r
    por_geo = {}
    for r in mejores.values():
        por_geo.setdefault(r["geo"], []).append(r)
    curados = []
    for geo, lista in por_geo.items():
        lista.sort(key=lambda r: -r["_vol_num"])
        curados.extend(lista[:top_n])
    return curados


def importar_a_supabase(filas):
    importados = 0
    errores = 0
    for r in filas:
        try:
            supabase.table("trends_manual_import").upsert({
                "tendencia": r["tendencia"],
                "volumen_busqueda": r["volumen_busqueda"],
                "geo": r["geo"],
                "ventana": r["ventana"],
                "inicio": r["inicio"],
                "finalizada": r["finalizada"],
                "keywords_relacionadas": r["keywords_relacionadas"],
            }, on_conflict="tendencia_norm,geo,ventana").execute()
            importados += 1
        except Exception as e:
            print(f"  Error importando '{r['tendencia'][:40]}': {e}")
            errores += 1
    return importados, errores


def main():
    os.makedirs(CARPETA_PROCESADOS, exist_ok=True)
    archivos = glob.glob(os.path.join(CARPETA_PENDIENTES, "*.csv"))
    if not archivos:
        print(f"Sin CSVs nuevos en {CARPETA_PENDIENTES}/ -- nada para hacer.")
        return

    print(f"Encontrados {len(archivos)} CSVs para procesar.\n")
    todas_las_filas = []
    total_descartadas = 0
    for path in archivos:
        filas, descartadas = parsear_csv(path)
        print(f"  {os.path.basename(path)}: {len(filas)} filas latinas, {descartadas} descartadas (no latinas)")
        todas_las_filas.extend(filas)
        total_descartadas += descartadas

    curados = curar_top(todas_las_filas)
    print(f"\nTotal parseado: {len(todas_las_filas)} filas ({total_descartadas} descartadas por escritura no latina)")
    print(f"Curados para importar (top {TOP_POR_GEO} por geo, deduplicado): {len(curados)}")

    importados, errores = importar_a_supabase(curados)
    print(f"\nImportados a Supabase: {importados} | Errores: {errores}")

    for path in archivos:
        shutil.move(path, os.path.join(CARPETA_PROCESADOS, os.path.basename(path)))
    print(f"\n{len(archivos)} archivos movidos a {CARPETA_PROCESADOS}/ (no se reprocesan en la proxima corrida).")


if __name__ == "__main__":
    main()
