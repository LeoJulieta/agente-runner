-- Migration 003: Schema expandido para enjambre experimental
-- Propósito: Agregar columnas para status extendido, análisis de fracasos, poblaciones y categorías
-- Nota: Todas las columnas nuevas son opcionales (default NULL) para no romper filas existentes

-- Status extendido (VERIFIED / PROMISING / INCONCLUSIVE / FAILED / INVALID / STALE)
ALTER TABLE public.lab_results ADD COLUMN IF NOT EXISTS status_extended TEXT;

-- Análisis estructurado de fracasos
ALTER TABLE public.lab_results ADD COLUMN IF NOT EXISTS failure_reason TEXT;
-- Metodológicas: insufficient_sample, weak_effect, high_variance, temporal_instability, invalid_hypothesis
-- De mercado: no_demand, saturated_offer, price_insufficient, no_distribution, market_shifted, wrong_product, wrong_channel

ALTER TABLE public.lab_results ADD COLUMN IF NOT EXISTS pivot_hint TEXT;
-- Sugerencia de pivote para la siguiente generación (ej: "demanda insuficiente para PDF → medir automatización de tarea")

-- Población (cinco tipos: explorer / exploiter / reexplorer / recombiner / discoverer)
ALTER TABLE public.lab_results ADD COLUMN IF NOT EXISTS population_type TEXT;

-- Categoría (known / combination / emerging / unknown)
ALTER TABLE public.lab_results ADD COLUMN IF NOT EXISTS category TEXT;

-- Para población discoverer: suposición bajo prueba
ALTER TABLE public.lab_results ADD COLUMN IF NOT EXISTS assumption_under_test TEXT;

-- Para validación confirmatoria: dirección preregistrada
ALTER TABLE public.lab_results ADD COLUMN IF NOT EXISTS expected_direction TEXT;
