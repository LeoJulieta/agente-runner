-- Migration 002: lab_results RLS + protección constitucional
-- Propósito: Habilitar Row Level Security en lab_results (deny-all anon)
-- Nota: service_role bypassea RLS: writers intactos
-- Protección Regla 2/5: DELETE prohibido, UPDATE solo permite cambios en status/last_test

-- Habilitar RLS (sin policies = deny-all para anon/authenticated)
ALTER TABLE public.lab_results ENABLE ROW LEVEL SECURITY;

-- Función trigger de protección constitucional
CREATE OR REPLACE FUNCTION public.trg_lab_results_proteccion()
RETURNS TRIGGER AS $$
BEGIN
    -- Regla 2: DELETE prohibido
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'lab_results: DELETE prohibido (regla 2)';
    END IF;

    -- Regla 5: UPDATE solo permite cambios en status / last_test
    -- El resto de columnas debe permanecer inmutable
    IF TG_OP = 'UPDATE' THEN
        IF OLD.lab_id IS DISTINCT FROM NEW.lab_id
            OR OLD.gen IS DISTINCT FROM NEW.gen
            OR OLD.params IS DISTINCT FROM NEW.params
            OR OLD.metrics IS DISTINCT FROM NEW.metrics
            OR OLD.evidence_count IS DISTINCT FROM NEW.evidence_count
            OR OLD.reproducible IS DISTINCT FROM NEW.reproducible
            OR OLD.creado_en IS DISTINCT FROM NEW.creado_en
        THEN
            RAISE EXCEPTION 'lab_results: UPDATE prohibido en columnas inmutables (regla 2/5). Solo status/last_test pueden modificarse.';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger before update or delete por fila
DROP TRIGGER IF EXISTS trg_lab_results_proteccion ON public.lab_results;
CREATE TRIGGER trg_lab_results_proteccion
    BEFORE UPDATE OR DELETE ON public.lab_results
    FOR EACH ROW
    EXECUTE FUNCTION public.trg_lab_results_proteccion();
