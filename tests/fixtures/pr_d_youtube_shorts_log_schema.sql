-- Minimal legacy-shaped fixture based on the audited production column types,
-- nullability, RLS model, and updated_at trigger. The E12 migration must widen
-- the legacy int4 metric without rewriting the 307 existing outcome rows.
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

CREATE SCHEMA IF NOT EXISTS pr_d_test;
CREATE TABLE pr_d_test.youtube_shorts_log (
    id bigserial PRIMARY KEY,
    youtube_video_id text,
    views_primeras_3h integer,
    hs_al_publicar_al_sync numeric,
    status text DEFAULT 'pending',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE OR REPLACE FUNCTION pr_d_test.update_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $updated_at$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$updated_at$;

CREATE TRIGGER shorts_updated_at
    BEFORE UPDATE ON pr_d_test.youtube_shorts_log
    FOR EACH ROW
    EXECUTE FUNCTION pr_d_test.update_updated_at();

ALTER TABLE pr_d_test.youtube_shorts_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY anon_read
    ON pr_d_test.youtube_shorts_log
    FOR SELECT TO anon
    USING (true);
CREATE POLICY service_all
    ON pr_d_test.youtube_shorts_log
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

GRANT USAGE ON SCHEMA pr_d_test TO anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON TABLE pr_d_test.youtube_shorts_log TO anon, authenticated, service_role;
GRANT USAGE, SELECT
    ON SEQUENCE pr_d_test.youtube_shorts_log_id_seq TO service_role;
