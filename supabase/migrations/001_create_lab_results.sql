-- supabase/migrations/001_create_lab_results.sql
-- Fase 0 P/L/D/E - tabla de resultados del laboratorio.
-- No toca ninguna tabla de producción.

CREATE TABLE IF NOT EXISTS lab_results (
    id bigserial PRIMARY KEY,
    lab_id text NOT NULL,
    gen int DEFAULT 0,
    params jsonb,
    metrics jsonb,
    status text CHECK (status IN ('PROMETE', 'VERIFICADO', 'STALE', 'CADUCADO')),
    evidence_count int DEFAULT 0,
    reproducible boolean DEFAULT false,
    last_test timestamptz,
    creado_en timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lab_results_lab_id ON lab_results (lab_id);
CREATE INDEX IF NOT EXISTS idx_lab_results_status ON lab_results (status);
