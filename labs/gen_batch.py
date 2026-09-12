#!/usr/bin/env python3
"""
Fase 2 - Paso 1/2: Generador determinístico de contratos YAML.
Genera 7 hipótesis (H002 a H008) en labs/hypotheses/
Esquema idéntico a H001.yaml (referencia en main).
"""

import os
import yaml

# Catálogo hardcodeado según especificación
# H002 = independent hora_publicacion con derive {source: created_at, subtract_hours_from_column: hs_al_publicar_al_sync, tz_offset_hours: -3, extract: hour}, comparison less_than, baseline −0.3
# H003/H004 = hora_local derive {source: created_at, tz_offset_hours: -3, extract: hour} pos/neg
# H005/H006 = hora_utc derive {source: created_at, extract: hour} pos/neg
# H007/H008 = independent hs_al_publicar_al_sync sin derive pos/neg

CATALOGO = [
    {
        "id": "H002",
        "description": "Correlación entre hora de publicación y views en primeras 3 horas (menos que umbral negativo)",
        "independent": "hora_publicacion",
        "derive": {
            "source": "created_at",
            "subtract_hours_from_column": "hs_al_publicar_al_sync",
            "tz_offset_hours": -3,
            "extract": "hour"
        },
        "comparison_type": "less_than",
        "comparison_description": "Correlación medida < -0.3 (correlación moderada o fuerte negativa)",
        "baseline_value": -0.3,
    },
    {
        "id": "H003",
        "description": "Correlación positiva entre hora local de publicación y views en primeras 3 horas",
        "independent": "hora_local",
        "derive": {
            "source": "created_at",
            "tz_offset_hours": -3,
            "extract": "hour"
        },
        "comparison_type": "greater_than",
        "comparison_description": "Correlación medida > 0.3 (correlación moderada o fuerte)",
        "baseline_value": 0.3,
    },
    {
        "id": "H004",
        "description": "Correlación negativa entre hora local de publicación y views en primeras 3 horas",
        "independent": "hora_local",
        "derive": {
            "source": "created_at",
            "tz_offset_hours": -3,
            "extract": "hour"
        },
        "comparison_type": "less_than",
        "comparison_description": "Correlación medida < -0.3 (correlación moderada o fuerte negativa)",
        "baseline_value": -0.3,
    },
    {
        "id": "H005",
        "description": "Correlación positiva entre hora UTC de publicación y views en primeras 3 horas",
        "independent": "hora_utc",
        "derive": {
            "source": "created_at",
            "extract": "hour"
        },
        "comparison_type": "greater_than",
        "comparison_description": "Correlación medida > 0.3 (correlación moderada o fuerte)",
        "baseline_value": 0.3,
    },
    {
        "id": "H006",
        "description": "Correlación negativa entre hora UTC de publicación y views en primeras 3 horas",
        "independent": "hora_utc",
        "derive": {
            "source": "created_at",
            "extract": "hour"
        },
        "comparison_type": "less_than",
        "comparison_description": "Correlación medida < -0.3 (correlación moderada o fuerte negativa)",
        "baseline_value": -0.3,
    },
    {
        "id": "H007",
        "description": "Correlación positiva entre hs_al_publicar_al_sync y views en primeras 3 horas",
        "independent": "hs_al_publicar_al_sync",
        "derive": None,  # Sin derive
        "comparison_type": "greater_than",
        "comparison_description": "Correlación medida > 0.3 (correlación moderada o fuerte)",
        "baseline_value": 0.3,
    },
    {
        "id": "H008",
        "description": "Correlación negativa entre hs_al_publicar_al_sync y views en primeras 3 horas",
        "independent": "hs_al_publicar_al_sync",
        "derive": None,  # Sin derive
        "comparison_type": "less_than",
        "comparison_description": "Correlación medida < -0.3 (correlación moderada o fuerte negativa)",
        "baseline_value": -0.3,
    },
]


def build_yaml_doc(hipotesis):
    """Construye el documento YAML siguiendo exactamente el esquema de H001.yaml"""
    doc = {
        "id": hipotesis["id"],
        "description": hipotesis["description"],
        "class": "A",
        "gen": 0,
        "dataset": ["youtube_shorts_log"],
        "vars": {
            "independent": [hipotesis["independent"]],
            "dependent": ["views_primeras_3h"]
        },
    }

    # Solo agregar derive si existe y no es None
    if hipotesis.get("derive") is not None:
        # derive es un diccionario claveado por el nombre de la variable independiente
        doc["derive"] = {hipotesis["independent"]: hipotesis["derive"]}

    doc["metric"] = {"primary": "correlation"}

    doc["baseline"] = {
        "type": "fixed",
        "value": hipotesis["baseline_value"]
    }

    doc["comparison"] = {
        "type": hipotesis["comparison_type"],
        "description": hipotesis["comparison_description"]
    }

    doc["sample_min"] = 30
    doc["max_runtime"] = 300
    doc["evidence_required"] = True
    doc["reproducibility_required"] = True
    doc["cost_limit"] = 0
    doc["authorized"] = False

    return doc


def autocheck(yaml_files):
    """
    Autocheck final: recargar cada YAML escrito y assertear que existen:
    - id
    - vars.independent[0]
    - vars.dependent[0]
    - metric.primary
    - baseline.type
    - baseline.value
    - comparison.type
    - Si hay derive, su única clave == vars.independent[0]

    Imprime tabla de resultados del autocheck.
    """
    print("\n" + "=" * 80)
    print("AUTOCHECK FINAL - Validación de YAMLs generados")
    print("=" * 80)

    results = []

    for filepath in yaml_files:
        filename = os.path.basename(filepath)
        checks = {
            "id": False,
            "vars.independent[0]": False,
            "vars.dependent[0]": False,
            "metric.primary": False,
            "baseline.type": False,
            "baseline.value": False,
            "comparison.type": False,
            "derive_key_match": None,  # None = N/A, True/False = pass/fail
        }

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                doc = yaml.safe_load(f)

            # Check id
            checks["id"] = "id" in doc and doc["id"] is not None

            # Check vars.independent[0]
            checks["vars.independent[0]"] = (
                "vars" in doc and
                "independent" in doc["vars"] and
                len(doc["vars"]["independent"]) > 0 and
                doc["vars"]["independent"][0] is not None
            )

            # Check vars.dependent[0]
            checks["vars.dependent[0]"] = (
                "vars" in doc and
                "dependent" in doc["vars"] and
                len(doc["vars"]["dependent"]) > 0 and
                doc["vars"]["dependent"][0] is not None
            )

            # Check metric.primary
            checks["metric.primary"] = (
                "metric" in doc and
                "primary" in doc["metric"] and
                doc["metric"]["primary"] is not None
            )

            # Check baseline.type
            checks["baseline.type"] = (
                "baseline" in doc and
                "type" in doc["baseline"] and
                doc["baseline"]["type"] is not None
            )

            # Check baseline.value
            checks["baseline.value"] = (
                "baseline" in doc and
                "value" in doc["baseline"] and
                doc["baseline"]["value"] is not None
            )

            # Check comparison.type
            checks["comparison.type"] = (
                "comparison" in doc and
                "type" in doc["comparison"] and
                doc["comparison"]["type"] is not None
            )

            # Check derive key match (si existe derive)
            if "derive" in doc and doc["derive"] is not None:
                independent_var = doc["vars"]["independent"][0]
                derive_keys = list(doc["derive"].keys())
                checks["derive_key_match"] = (
                    len(derive_keys) == 1 and
                    derive_keys[0] == independent_var
                )
            else:
                checks["derive_key_match"] = None  # N/A

        except Exception as e:
            checks["error"] = str(e)

        all_passed = all([
            checks["id"],
            checks["vars.independent[0]"],
            checks["vars.dependent[0]"],
            checks["metric.primary"],
            checks["baseline.type"],
            checks["baseline.value"],
            checks["comparison.type"],
        ])

        # derive_key_match puede ser None (N/A) y aún así pasar
        if checks["derive_key_match"] is False:
            all_passed = False

        results.append({
            "filename": filename,
            "checks": checks,
            "all_passed": all_passed
        })

    # Imprimir tabla
    print(f"\n{'Archivo':<15} {'id':<4} {'vars.ind[0]':<10} {'vars.dep[0]':<10} {'metric.p':<9} {'base.type':<9} {'base.val':<8} {'comp.type':<9} {'derive_key':<10} {'OK?':<5}")
    print("-" * 105)

    for r in results:
        c = r["checks"]
        derive_str = "N/A" if c["derive_key_match"] is None else ("PASS" if c["derive_key_match"] else "FAIL")
        ok_str = "PASS" if r["all_passed"] else "FAIL"

        print(f"{r['filename']:<15} "
              f"{'✓' if c['id'] else '✗':<4} "
              f"{'✓' if c['vars.independent[0]'] else '✗':<10} "
              f"{'✓' if c['vars.dependent[0]'] else '✗':<10} "
              f"{'✓' if c['metric.primary'] else '✗':<9} "
              f"{'✓' if c['baseline.type'] else '✗':<9} "
              f"{'✓' if c['baseline.value'] else '✗':<8} "
              f"{'✓' if c['comparison.type'] else '✗':<9} "
              f"{derive_str:<10} "
              f"{ok_str:<5}")

    print("-" * 105)
    total_passed = sum(1 for r in results if r["all_passed"])
    print(f"Total: {total_passed}/{len(results)} archivos PASSED")
    print("=" * 80 + "\n")

    return all(r["all_passed"] for r in results)


def main():
    output_dir = "labs/hypotheses"
    os.makedirs(output_dir, exist_ok=True)

    generated_files = []

    for hipotesis in CATALOGO:
        filename = f"{hipotesis['id']}.yaml"
        filepath = os.path.join(output_dir, filename)

        # Construir el documento YAML
        doc = build_yaml_doc(hipotesis)

        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(doc, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

        generated_files.append(filepath)
        print(f"Generado: {filepath}")

    # Autocheck final
    autocheck(generated_files)


if __name__ == "__main__":
    main()
