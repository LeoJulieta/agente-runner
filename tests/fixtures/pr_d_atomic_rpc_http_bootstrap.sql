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
    creado_en timestamptz DEFAULT now()
);

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.lab_results TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.lab_results_id_seq TO service_role;

-- The caller runs this bootstrap, then applies migration 004 and reloads PostgREST.
