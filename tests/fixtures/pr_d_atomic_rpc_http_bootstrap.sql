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

-- Start from the actual legacy type. The candidate migration must widen it.
CREATE TABLE public.youtube_shorts_log (
    id bigserial PRIMARY KEY,
    youtube_video_id text NOT NULL,
    views_primeras_3h integer,
    hs_al_publicar_al_sync numeric,
    status text NOT NULL DEFAULT 'pending'
);
ALTER TABLE public.youtube_shorts_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_all
    ON public.youtube_shorts_log
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE
    ON TABLE public.youtube_shorts_log TO service_role;
GRANT USAGE, SELECT
    ON SEQUENCE public.youtube_shorts_log_id_seq TO service_role;
