-- Disposable-only bootstrap for the isolated PostgREST HTTP E2E.
-- This file is executed only against the dedicated PostgreSQL service container.
DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN BYPASSRLS;
    END IF;
END
$roles$;

CREATE TABLE public.lab_results (
    id bigserial PRIMARY KEY,
    lab_id text NOT NULL,
    gen integer DEFAULT 0,
    params jsonb,
    metrics jsonb,
    status text CHECK (status IN ('PROMETE','VERIFICADO','STALE','CADUCADO')),
    evidence_count integer DEFAULT 0,
    reproducible boolean DEFAULT false,
    last_test timestamptz,
    creado_en timestamptz DEFAULT now(),
    status_extended text,
    failure_reason text,
    pivot_hint text,
    population_type text,
    category text,
    assumption_under_test text,
    expected_direction text
);


-- Reproduce the currently deployed row-protection trigger before the candidate
-- migration hardens it to cover every column except status and last_test.
CREATE OR REPLACE FUNCTION public.trg_lab_results_proteccion()
RETURNS trigger
LANGUAGE plpgsql
AS $legacy_guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'lab_results: DELETE prohibido (regla 2)';
    END IF;
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
$legacy_guard$;

CREATE TRIGGER trg_lab_results_proteccion
    BEFORE DELETE OR UPDATE ON public.lab_results
    FOR EACH ROW EXECUTE FUNCTION public.trg_lab_results_proteccion();

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
ALTER TABLE public.lab_results ENABLE ROW LEVEL SECURITY;
GRANT ALL PRIVILEGES ON public.lab_results TO anon, authenticated, service_role;
GRANT USAGE, SELECT ON SEQUENCE public.lab_results_id_seq TO service_role;

-- The caller runs this bootstrap, then applies migration 004 and reloads PostgREST.

-- PostgREST connects as a non-superuser authenticator and can switch only to
-- the explicitly granted API roles.
DO $authenticator$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticator') THEN
        CREATE ROLE authenticator NOINHERIT LOGIN PASSWORD 'prd_test_auth';
    END IF;
END
$authenticator$;
GRANT anon, authenticated, service_role TO authenticator;


-- Candidate E12 capture RPC is exercised over HTTP on this disposable table.
CREATE TABLE public.youtube_shorts_log (
    id bigserial PRIMARY KEY,
    youtube_video_id text NOT NULL,
    views_primeras_3h integer
);
ALTER TABLE public.youtube_shorts_log ENABLE ROW LEVEL SECURITY;
GRANT ALL PRIVILEGES ON TABLE public.youtube_shorts_log TO anon, authenticated, service_role;
GRANT USAGE, SELECT ON SEQUENCE public.youtube_shorts_log_id_seq TO service_role;
