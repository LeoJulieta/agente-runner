#!/usr/bin/env python3
"""
labs/gen_enjambre.py
Generador determinístico de hipótesis para enjambre experimental.

Gen 1 (25/9): el catálogo labs/variable_catalog.yaml es la fuente única de
verdad (pools por población, roles y derivadas). Emite IDs H041-H080,
var_roles explícitos y suposiciones de MEDICIÓN para discoverers.

Distribución de poblaciones (40 hormigas):
- 10 explorer / 12 exploiter / 6 reexplorer / 6 recombiner / 6 discoverer

Uso: python labs/gen_enjambre.py [--outdir <dir>]
"""
import sys
import random
import yaml
from pathlib import Path

SEED = 42
GEN = 1
GEN_OFFSET = 40                       # gen 0 ocupó H001-H040
TOTAL_HYPOTHESES = 40
LAST_INDEX = GEN_OFFSET + TOTAL_HYPOTHESES   # 80: H080_DISC es el único unknown
OUTPUT_DIR = Path("labs/hypotheses")
CATALOG_PATH = Path("labs/variable_catalog.yaml")
TAXONOMY_PATH = Path("labs/taxonomia_ingresos.yaml")

POPULATIONS = {
    "explorer": 10,      # 25%
    "exploiter": 12,     # 30%
    "reexplorer": 6,     # 15%
    "recombiner": 6,     # 15%
    "discoverer": 6,     # 15%
}

# Suposiciones de MEDICIÓN, atacables con el motor correlacional actual.
# Cada una va pareja a su proxy medible (deuda D1: las de mercado esperan
# experimentos categóricos/comparativos).
DISCOVERER_PAIRS = [
    ("hs_al_publicar_al_sync",
     "views_primeras_3h_es_comparable_entre_videos_con_distinto_retraso_de_sync"),
    ("likes",
     "los_likes_reflejan_engagement_temprano_y_no_exposicion_acumulada"),
    ("dia_semana",
     "el_efecto_de_la_hora_es_estable_entre_dias_de_semana"),
]

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


def load_catalog() -> dict:
    """Carga el catálogo único de verdad."""
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Catálogo no encontrado: {CATALOG_PATH}")
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_taxonomy() -> dict:
    """Carga taxonomía de ingresos desde YAML."""
    if not TAXONOMY_PATH.exists():
        return {"known": KNOWN_CATEGORIES, "combination": [], "emerging": [], "unknown": {}}
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
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


def build_derive(var_name: str, catalog_vars: dict):
    """Arma bloque derive desde el catálogo (fuente única de verdad)."""
    info = catalog_vars.get(var_name, {})
    if info.get("type") != "derived":
        return None
    spec = {"source": info["source"], "extract": info["extract"]}
    if info.get("tz_offset_hours") is not None:
        spec["tz_offset_hours"] = info["tz_offset_hours"]
    if info.get("optional_subtract_column"):
        spec["subtract_hours_from_column"] = info["optional_subtract_column"]
    return {var_name: spec}


def generate_baseline(population: str):
    """Baseline y comparison según población (confirmación vs exploración)."""
    if population in ["exploiter", "recombiner"]:
        value = random.choice([0.2, 0.3, -0.2, -0.3])
        comparison_type = "greater_than" if value > 0 else "less_than"
        description = f"Correlación {'positiva' if value > 0 else 'negativa'} > {abs(value)}"
    else:
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


def generate_hypothesis(index: int, population: str, pos: int,
                        catalog: dict, taxonomy: dict) -> dict:
    """Genera una hipótesis completa de gen 1."""
    random.seed(SEED + index)

    catalog_vars = catalog["variables"]
    pool = catalog["population_allowlist"][population]

    # Elección de variable independiente según población
    if population == "discoverer":
        pair = DISCOVERER_PAIRS[pos % len(DISCOVERER_PAIRS)]
        independent_var, assumption = pair[0], pair[1]
    elif population in ("reexplorer", "recombiner"):
        # Ciclado determinístico: garantiza diversidad >= 2 sin azar
        independent_var = pool[pos % len(pool)]
        assumption = None
    else:
        independent_var = random.choice(pool)
        assumption = None

    dependent_var = "views_primeras_3h"
    vars_dict = {"independent": [independent_var], "dependent": [dependent_var]}

    derive = build_derive(independent_var, catalog_vars)
    baseline, comparison = generate_baseline(population)

    # Categoría: unknown solo para la última discoverer (H080_DISC)
    if population == "discoverer" and index == LAST_INDEX:
        category = "unknown"
    elif population == "recombiner":
        category = "combination"
    else:
        category = random.choice(taxonomy.get("known", KNOWN_CATEGORIES))

    # Roles explícitos: el contrato declara, el catálogo manda, el motor verifica
    var_roles = {
        independent_var: catalog_vars[independent_var]["role"],
        dependent_var: catalog_vars[dependent_var]["role"],
    }

    contract = {
        "id": generate_id(population, index),
        "class": "A",
        "gen": GEN,
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
        "var_roles": var_roles,
    }

    if derive:
        contract["derive"] = derive

    if population in ["exploiter", "recombiner"]:
        contract["expected_direction"] = "positive" if baseline["value"] > 0 else "negative"

    if population == "discoverer":
        contract["assumption_under_test"] = assumption

    contract = {k: v for k, v in contract.items() if v is not None}
    return contract


def main():
    outdir = OUTPUT_DIR
    if len(sys.argv) > 2 and sys.argv[1] == "--outdir":
        outdir = Path(sys.argv[2])

    outdir.mkdir(parents=True, exist_ok=True)

    catalog = load_catalog()
    taxonomy = load_taxonomy()
    catalog_vars = catalog["variables"]

    hypotheses = []
    index = GEN_OFFSET + 1

    for population, count in POPULATIONS.items():
        for pos in range(count):
            hypotheses.append(generate_hypothesis(index, population, pos, catalog, taxonomy))
            index += 1

    for h in hypotheses:
        filepath = outdir / f"{h['id']}.yaml"
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(h, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"Generado: {filepath}")

    print(f"\nTotal: {len(hypotheses)} hipótesis generadas en {outdir}")

    from collections import Counter
    print("\nDistribución por población:")
    for pop, count in sorted(Counter(h["population_type"] for h in hypotheses).items()):
        print(f"  {pop}: {count}")

    print("\nDistribución por categoría:")
    for cat, count in sorted(Counter(h["category"] for h in hypotheses).items()):
        print(f"  {cat}: {count}")

    print("\nAutocheck de diversidad y catálogo:")
    ids = [h["id"] for h in hypotheses]
    assert len(ids) == len(set(ids)), "ERROR: Hay IDs duplicados"
    print(f"  IDs únicos: {len(set(ids))} (OK)")

    print("  Prefijos por población:")
    for prefix, count in sorted(Counter(h["id"].rsplit("_", 1)[1] for h in hypotheses).items()):
        print(f"    {prefix}: {count}")

    pop_vars = {}
    for h in hypotheses:
        pop_vars.setdefault(h["population_type"], set()).add(tuple(h["vars"]["independent"]))

    print("\nVariables independientes distintas por población:")
    for pop in sorted(pop_vars.keys()):
        print(f"  {pop}: {len(pop_vars[pop])} variable(s) distinta(s)")
        assert len(pop_vars[pop]) >= 2, f"ERROR: {pop} tiene solo {len(pop_vars[pop])} variable distinta"

    # Gate interno: todo contrato emitido debe pasar los gates del motor
    for h in hypotheses:
        pop = h["population_type"]
        indep = h["vars"]["independent"][0]
        assert indep in catalog["population_allowlist"][pop], f"ERROR: {indep} fuera del pool de {pop}"
        is_derived = catalog_vars[indep]["type"] == "derived"
        has_derive = indep in (h.get("derive") or {})
        assert is_derived == has_derive, f"ERROR: derive inconsistente en {h['id']}"
        for var_name, role in h["var_roles"].items():
            assert catalog_vars[var_name]["role"] == role, f"ERROR: var_roles inconsistente en {h['id']}"

    print("\n  ✓ Todos los checks pasaron")


if __name__ == "__main__":
    main()
