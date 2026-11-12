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
