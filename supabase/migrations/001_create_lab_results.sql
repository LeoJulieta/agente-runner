-- Migración: Crear tabla lab_results para arquitectura P/L/D/E
-- Qué: Tabla para almacenar resultados de experimentos de laboratorio
-- Por qué: Base para Fase 0 - trazabilidad y reproducibilidad de experimentos
-- Cuándo: 2024-09-03 (Fase 0)

CREATE TABLE IF NOT EXISTS lab_results (
    id bigserial PRIMARY KEY,
    lab_id text NOT NULL,
    gen int DEFAULT 0,
    params jsonb,
    metrics jsonb,
    status text CHECK (status IN ('PROMETE', 'VERIFICADO', 'STALE', 'CADUCADO')),
    evidence_count int DEFAULT 0,
    reproducible bool DEFAULT false,
    last_test timestamptz,
    creado_en timestamptz DEFAULT now()
);

-- Índice para búsquedas por lab_id y gen
CREATE INDEX IF NOT EXISTS idx_lab_results_lab_id ON lab_results(lab_id);
CREATE INDEX IF NOT EXISTS idx_lab_results_status ON lab_results(status);