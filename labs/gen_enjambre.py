#!/usr/bin/env python3
"""
labs/gen_enjambre.py
Generador determinístico de hipótesis para enjambre experimental.

Distribución de poblaciones (40 hormigas total):
- 25% Exploradores (~10): combinaciones nuevas de variables sin expected_direction
- 30% Explotadores (~12): profundizar variables con señal, con expected_direction
- 15% Reexploradores (~6): reformular hipótesis fallidas con diferentes ventanas
- 15% Recombinadores (~6): combinar variables de hipótesis PROMISING/VERIFIED
- 15% Descubridores (~6): atacar suposiciones declaradas, al menos 1 category: unknown

Uso: python labs/gen_enjambre.py [--outdir <dir>]
"""
import os
import sys
import random
import yaml
from pathlib import Path

SEED = 42
TOTAL_HYPOTHESES = 40
OUTPUT_DIR = Path("labs/hypotheses")

# Distribución exacta
POPULATIONS = {
    "explorer": 10,      # 25%
    "exploiter": 12,     # 30%
    "reexplorer": 6,     # 15%
    "recombiner": 6,     # 15%
    "discoverer": 6,     # 15%
}

# Columnas reales existentes en youtube_shorts_log
REAL_COLUMNS = [
    "views_primeras_3h",
    "views_24h",
    "views_7d",
    "interacciones_totales",
    "tasa_clic_afiliado",
    "duracion_segundos",
    "categoria",
    "created_at",
    "hs_al_publicar_al_sync",
]

# Variables derivables (via bloque derive)
DERIVABLE_VARS = {
    "hora_publicacion": {"source": "created_at", "extract": "hour", "tz_offset_hours": -3},
    "dia_semana": {"source": "created_at", "extract": "weekday"},
}

# Categorías conocidas de la taxonomía
KNOWN_CATEGORIES = [
    "publicidad_adsense",
    "afiliados_amazon",
    "afiliados_saas",
    "sponsors_directos",
    "pdfs_guias",
    "pdfs_templates",
    "cursos_online",
    "micro_saas",
    "apis_pago",
    "membresias_newsletter",
    "servicios_productizados",
    "datasets_venta",
    "prompts_venta",
    "codigo_venta",
    "plantillas_venta",
]

# Suposiciones típicas para discoverers
ASSUMPTIONS = [
    "solo_funciona_en_ingles",
    "el_contenido_largo_convierte_mejor",
    "necesitamos_audiencia_previa",
    "hay_que_vender_producto_proprio",
    "los_shorts_no_generan_ingresos",
    "la_calidad_es_mas_importante_que_cantidad",
]

def load_taxonomy() -> dict:
    """Carga taxonomía de ingresos desde YAML."""
    path = Path("labs/taxonomia_ingresos.yaml")
    if not path.exists():
        return {"known": KNOWN_CATEGORIES, "combination": [], "emerging": [], "unknown": {}}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def generate_id(population: str, index: int) -> str:
    """Genera ID único para hipótesis."""
    prefix_map = {
        "explorer": "EXPR",
        "exploiter": "EXPL",
        "reexplorer": "REEX",
        "recombiner": "RECO",
        "discoverer": "DISC",
    }
    prefix = prefix_map.get(population, "HYP")
    return f"H{index:03d}_{prefix}"

def generate_vars(population: str, taxonomy: dict) -> dict:
    """Genera vars.independent y vars.dependent según población."""
    # El seed se setea en generate_hypothesis(SEED + index) para determinismo por hipótesis

    # Variable dependiente fija (métrica de resultado)
    dependent = ["views_primeras_3h"]

    if population == "explorer":
        # Exploradores: combinaciones nuevas de variables reales
        independent_var = random.choice([c for c in REAL_COLUMNS if c not in dependent])
        independent = [independent_var]

    elif population == "exploiter":
        # Explotadores: variables que mostraron señal (hora, duración)
        independent_var = random.choice(["hora_publicacion", "duracion_segundos", "interacciones_totales"])
        independent = [independent_var]

    elif population == "reexplorer":
        # Reexploradores: mismas variables con diferente enfoque temporal
        independent_var = random.choice(["views_24h", "views_7d", "tasa_clic_afiliado"])
        independent = [independent_var]

    elif population == "recombiner":
        # Recombinadores: combinación de variables existentes
        independent_var = random.choice(REAL_COLUMNS)
        independent = [independent_var]

    elif population == "discoverer":
        # Descubridores: proxy medible para atacar suposición
        independent_var = random.choice(["interacciones_totales", "tasa_clic_afiliado", "categoria"])
        independent = [independent_var]
    else:
        independent = [random.choice(REAL_COLUMNS)]

    return {
        "independent": independent,
        "dependent": dependent,
    }

def generate_derive(population: str, independent_var: str) -> dict | None:
    """Genera bloque derive si la variable es derivable."""
    if independent_var in DERIVABLE_VARS:
        spec = DERIVABLE_VARS[independent_var].copy()
        # Agregar ajuste de timezone si corresponde
        if "hora_publicacion" in independent_var:
            spec["subtract_hours_from_column"] = "hs_al_publicar_al_sync"
        return {independent_var: spec}
    return None

def generate_baseline(population: str) -> dict:
    # El seed se setea en generate_hypothesis(SEED + index) para determinismo por hipótesis

    if population in ["exploiter", "recombiner"]:
        # Confirmación: baseline con dirección esperada
        value = random.choice([0.2, 0.3, -0.2, -0.3])
        comparison_type = "greater_than" if value > 0 else "less_than"
        description = f"Correlación {'positiva' if value > 0 else 'negativa'} > {abs(value)}"
    else:
        # Exploración: baseline neutral
        value = 0.3
        comparison_type = "greater_than"
        description = "Correlación medida > umbral"

    return {
        "type": "fixed",
        "value": value,
    }, {
        "type": comparison_type,
        "description": description,
    }

def generate_hypothesis(index: int, population: str, taxonomy: dict) -> dict:
    """Genera una hipótesis completa."""
    random.seed(SEED + index)

    hypothesis_id = generate_id(population, index)
    vars_dict = generate_vars(population, taxonomy)
    independent_var = vars_dict["independent"][0]

    # Generar derive si aplica
    derive = generate_derive(population, independent_var)

    # Generar baseline y comparison
    baseline, comparison = generate_baseline(population)

    # Determinar categoría
    is_unknown_discoverer = (population == "discoverer" and index == TOTAL_HYPOTHESES)
    if is_unknown_discoverer:
        category = "unknown"
    elif population in ["recombiner"]:
        category = "combination"
    else:
        category = random.choice(KNOWN_CATEGORIES)

    # Construir contrato base
    contract = {
        "id": hypothesis_id,
        "class": "A",
        "gen": 0,
        "dataset": ["youtube_shorts_log"],
        "vars": vars_dict,
        "metric": {"primary": "correlation"},
        "baseline": baseline,
        "comparison": comparison,
        "sample_min": 30,
        "max_runtime": 300,
        "cost_limit": 0,
        "authorized": False,
        "population_type": population,
        "category": category,
        "income_category": category if category in KNOWN_CATEGORIES else None,
    }

    # Agregar derive si existe
    if derive:
        contract["derive"] = derive

    # Agregar expected_direction solo para confirmación (exploiter/recombiner)
    if population in ["exploiter", "recombiner"]:
        direction = "positive" if baseline["value"] > 0 else "negative"
        contract["expected_direction"] = direction

    # Agregar assumption_under_test solo para discoverer
    if population == "discoverer":
        contract["assumption_under_test"] = random.choice(ASSUMPTIONS)

    # Limpiar campos None
    contract = {k: v for k, v in contract.items() if v is not None}

    return contract

def main():
    outdir = OUTPUT_DIR
    if len(sys.argv) > 2 and sys.argv[1] == "--outdir":
        outdir = Path(sys.argv[2])

    outdir.mkdir(parents=True, exist_ok=True)

    # Cargar taxonomía
    taxonomy = load_taxonomy()

    # Generar todas las hipótesis
    hypotheses = []
    index = 1

    for population, count in POPULATIONS.items():
        for _ in range(count):
            hypothesis = generate_hypothesis(index, population, taxonomy)
            hypotheses.append(hypothesis)
            index += 1

    # Guardar cada hipótesis en archivo YAML
    for h in hypotheses:
        filename = f"{h['id']}.yaml"
        filepath = outdir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(h, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"Generado: {filepath}")

    print(f"\nTotal: {len(hypotheses)} hipótesis generadas en {outdir}")

    # Resumen de distribución
    from collections import Counter
    pop_counts = Counter(h["population_type"] for h in hypotheses)
    cat_counts = Counter(h["category"] for h in hypotheses)

    print("\nDistribución por población:")
    for pop, count in sorted(pop_counts.items()):
        print(f"  {pop}: {count}")

    print("\nDistribución por categoría:")
    for cat, count in sorted(cat_counts.items()):
        print(f"  {cat}: {count}")

    # Autocheck de diversidad: IDs únicos y variables distintas por población
    print("\nAutocheck de diversidad:")

    # Verificar IDs únicos
    ids = [h["id"] for h in hypotheses]
    assert len(ids) == len(set(ids)), f"ERROR: Hay IDs duplicados"
    print(f"  IDs únicos: {len(set(ids))} (OK)")

    # Verificar prefijos únicos por población
    from collections import Counter
    id_prefixes = [h["id"].rsplit("_", 1)[1] for h in hypotheses]
    prefix_counts = Counter(id_prefixes)

    print("  Prefijos por población:")
    for prefix, count in sorted(prefix_counts.items()):
        print(f"    {prefix}: {count}")

    # Tabla de variables independientes distintas por población
    print("\nVariables independientes distintas por población:")
    pop_vars = {}
    for h in hypotheses:
        pop = h["population_type"]
        indep = tuple(h["vars"]["independent"])
        if pop not in pop_vars:
            pop_vars[pop] = set()
        pop_vars[pop].add(indep)

    all_ok = True
    for pop in sorted(pop_vars.keys()):
        vars_list = list(pop_vars[pop])
        print(f"  {pop}: {len(vars_list)} variable(s) distinta(s)")
        if len(vars_list) < 2:
            print(f"    WARNING: {pop} tiene solo 1 variable distinta")
            all_ok = False

    # Assert: al menos 2 variables distintas por población
    for pop, vars_set in pop_vars.items():
        assert len(vars_set) >= 2, f"ERROR: {pop} tiene solo {len(vars_set)} variable distinta (mínimo 2)"

    print("\n  ✓ Todos los checks pasaron")

if __name__ == "__main__":
    main()
