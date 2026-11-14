-- SANDBOX CANDIDATE ONLY. Never apply to a live project from this branch.
-- E12: preserve legacy rows, store uint64 exactly, and make the capture path
-- mandatory for new outcomes without removing service_role's unrelated DML.
-- The privileged implementation lives in a non-exposed schema and runs as a
-- dedicated NOLOGIN role with only the four capture-column UPDATE privileges.

ALTER TABLE public.youtube_shorts_log
    ADD COLUMN IF NOT EXISTS published_at timestamptz,
    ADD COLUMN IF NOT EXISTS sync_captured_at timestamptz,
    ADD COLUMN IF NOT EXISTS elapsed_seconds_e12 numeric(20,6);

COMMENT ON COLUMN public.youtube_shorts_log.published_at IS
    'YouTube videos.list snippet.publishedAt for the exact video observed by the E12 collector.';
COMMENT ON COLUMN public.youtube_shorts_log.sync_captured_at IS
    'UTC client receive timestamp recorded immediately after the videos.list HTTP response body is read; not a YouTube server-side event timestamp.';
COMMENT ON COLUMN public.youtube_shorts_log.elapsed_seconds_e12 IS
    'Exact elapsed seconds derived from sync_captured_at minus published_at, stored to microsecond precision. Separate from legacy hs_al_publicar_al_sync, whose historical formula uses created_at.';

DO $preflight$
DECLARE
    v_invalid_rows bigint;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'youtube_shorts_log'
          AND column_name = 'hs_al_publicar_al_sync'
    ) THEN
        RAISE EXCEPTION
            'prd_sync_migration_preflight_failed: expected legacy elapsed column hs_al_publicar_al_sync is missing'
            USING ERRCODE = '42703';
    END IF;

    SELECT count(*) INTO v_invalid_rows
    FROM public.youtube_shorts_log
    WHERE views_primeras_3h < 0
       OR views_primeras_3h > 18446744073709551615
       OR views_primeras_3h <> trunc(views_primeras_3h);

    IF v_invalid_rows > 0 THEN
        RAISE EXCEPTION
            'prd_sync_migration_preflight_failed: invalid unsigned integer views_primeras_3h rows=%. No row values were changed; audit legacy records before retry.',
            v_invalid_rows
            USING ERRCODE = '23514';
    END IF;

    -- YouTube viewCount is unsigned 64-bit. Preflight precedes the cast so
    -- fractional values can never be silently rounded by numeric(20,0).
    ALTER TABLE public.youtube_shorts_log
        ALTER COLUMN views_primeras_3h TYPE numeric(20,0)
        USING views_primeras_3h::numeric;

    ALTER TABLE public.youtube_shorts_log
        DROP CONSTRAINT IF EXISTS youtube_shorts_log_views_nonnegative_ck;
    ALTER TABLE public.youtube_shorts_log
        ADD CONSTRAINT youtube_shorts_log_views_nonnegative_ck
        CHECK (
            views_primeras_3h IS NULL
            OR (
                views_primeras_3h >= 0
                AND views_primeras_3h <= 18446744073709551615
                AND views_primeras_3h = trunc(views_primeras_3h)
            )
        );
END;
$preflight$;

-- Existing rows with both new timestamps NULL remain readable as legacy data.
-- Every newly captured E12 row must have a complete timestamp pair, a count,
-- and the exact elapsed-hours value derived from those timestamps.
ALTER TABLE public.youtube_shorts_log
    DROP CONSTRAINT IF EXISTS youtube_shorts_log_sync_capture_window_ck;
ALTER TABLE public.youtube_shorts_log
    ADD CONSTRAINT youtube_shorts_log_sync_capture_window_ck
    CHECK (
        (
            published_at IS NULL
            AND sync_captured_at IS NULL
            AND elapsed_seconds_e12 IS NULL
        )
        OR (
            published_at IS NOT NULL
            AND sync_captured_at IS NOT NULL
            AND views_primeras_3h IS NOT NULL
            AND views_primeras_3h >= 0
            AND elapsed_seconds_e12 IS NOT NULL
            AND elapsed_seconds_e12 =
                EXTRACT(EPOCH FROM (sync_captured_at - published_at))
            AND sync_captured_at >= published_at + interval '2 hours 55 minutes'
            AND sync_captured_at <= published_at + interval '3 hours 5 minutes'
        )
    );

-- A dedicated non-login role is the only database principal allowed to change
-- the protected capture columns. It has no role memberships, no RLS bypass,
-- no table ownership, and no INSERT/DELETE privileges.
DO $capture_role$
DECLARE
    v_role_oid oid;
    v_role record;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pr_d_capture_owner') THEN
        CREATE ROLE pr_d_capture_owner
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;

    SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
           rolinherit, rolreplication, rolbypassrls
      INTO v_role
      FROM pg_roles
     WHERE rolname = 'pr_d_capture_owner';

    v_role_oid := v_role.oid;
    IF v_role.rolcanlogin OR v_role.rolsuper OR v_role.rolcreatedb
       OR v_role.rolcreaterole OR v_role.rolinherit
       OR v_role.rolreplication OR v_role.rolbypassrls THEN
        RAISE EXCEPTION
            'prd_capture_role_preflight_failed: pr_d_capture_owner has unsafe role attributes';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_auth_members m
        WHERE (m.roleid = v_role_oid OR m.member = v_role_oid)
          AND NOT (
              m.roleid = v_role_oid
              AND m.member = (SELECT oid FROM pg_roles WHERE rolname = 'postgres')
          )
    ) THEN
        RAISE EXCEPTION
            'prd_capture_role_preflight_failed: pr_d_capture_owner has an untrusted role membership; only the trusted postgres administrator membership is permitted';
    END IF;

    IF NOT (
        SELECT relrowsecurity
        FROM pg_class
        WHERE oid = 'public.youtube_shorts_log'::regclass
    ) THEN
        RAISE EXCEPTION
            'prd_capture_table_preflight_failed: youtube_shorts_log must have RLS enabled';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE oid = 'public.youtube_shorts_log'::regclass
          AND relowner = v_role_oid
    ) THEN
        RAISE EXCEPTION
            'prd_capture_table_preflight_failed: restricted capture role must not own youtube_shorts_log';
    END IF;

    -- Supabase grants the managed postgres administrator membership in newly
    -- created roles. Ensure it can SET ROLE, but never inherit the capture role.
    GRANT pr_d_capture_owner TO postgres WITH SET TRUE, INHERIT FALSE;

    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'pr_d_internal') THEN
        CREATE SCHEMA pr_d_internal AUTHORIZATION pr_d_capture_owner;
    END IF;

    IF (
        SELECT nspowner FROM pg_namespace WHERE nspname = 'pr_d_internal'
    ) <> v_role_oid THEN
        RAISE EXCEPTION
            'prd_capture_schema_preflight_failed: pr_d_internal must be owned by pr_d_capture_owner';
    END IF;
END;
$capture_role$;

REVOKE ALL ON SCHEMA pr_d_internal FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA pr_d_internal TO service_role;
GRANT USAGE ON SCHEMA public TO pr_d_capture_owner;

GRANT SELECT (
    id, youtube_video_id, views_primeras_3h,
    published_at, sync_captured_at, elapsed_seconds_e12,
    hs_al_publicar_al_sync
) ON public.youtube_shorts_log TO pr_d_capture_owner;
GRANT UPDATE (
    views_primeras_3h, published_at, sync_captured_at, elapsed_seconds_e12
) ON public.youtube_shorts_log TO pr_d_capture_owner;

-- The restricted role is subject to RLS (it is not BYPASSRLS). Give it only
-- the row access needed by its narrowly-scoped capture function.
DROP POLICY IF EXISTS pr_d_capture_owner_select ON public.youtube_shorts_log;
CREATE POLICY pr_d_capture_owner_select
    ON public.youtube_shorts_log
    FOR SELECT TO pr_d_capture_owner
    USING (true);

DROP POLICY IF EXISTS pr_d_capture_owner_update ON public.youtube_shorts_log;
CREATE POLICY pr_d_capture_owner_update
    ON public.youtube_shorts_log
    FOR UPDATE TO pr_d_capture_owner
    USING (true)
    WITH CHECK (true);

-- Defense in depth: even service_role's existing table-level DML grants cannot
-- write, replace, or delete a captured outcome outside the restricted helper.
-- Ordinary updates to unrelated columns remain available to existing callers.
CREATE OR REPLACE FUNCTION public.pr_d_guard_capture_fields()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF current_user <> 'pr_d_capture_owner'
           AND (
               NEW.views_primeras_3h IS NOT NULL
               OR NEW.published_at IS NOT NULL
               OR NEW.sync_captured_at IS NOT NULL
               OR NEW.elapsed_seconds_e12 IS NOT NULL
               OR NEW.hs_al_publicar_al_sync IS NOT NULL
           ) THEN
            RAISE EXCEPTION
                'prd_capture_write_denied: populated capture fields require the controlled CAS path'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF current_user <> 'pr_d_capture_owner'
           AND (
               OLD.views_primeras_3h IS NOT NULL
               OR OLD.published_at IS NOT NULL
               OR OLD.sync_captured_at IS NOT NULL
               OR OLD.elapsed_seconds_e12 IS NOT NULL
               OR OLD.hs_al_publicar_al_sync IS NOT NULL
           ) THEN
            RAISE EXCEPTION
                'prd_capture_delete_denied: captured outcome rows are immutable'
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;

    IF current_user <> 'pr_d_capture_owner'
       AND (
           NEW.views_primeras_3h IS DISTINCT FROM OLD.views_primeras_3h
           OR NEW.published_at IS DISTINCT FROM OLD.published_at
           OR NEW.sync_captured_at IS DISTINCT FROM OLD.sync_captured_at
           OR NEW.elapsed_seconds_e12 IS DISTINCT FROM OLD.elapsed_seconds_e12
           OR NEW.hs_al_publicar_al_sync IS DISTINCT FROM OLD.hs_al_publicar_al_sync
           OR (
               OLD.views_primeras_3h IS NOT NULL
               AND (
                   NEW.youtube_video_id IS DISTINCT FROM OLD.youtube_video_id
                   OR NEW.id IS DISTINCT FROM OLD.id
               )
           )
       ) THEN
        RAISE EXCEPTION
            'prd_capture_write_denied: capture fields and captured video identity require the controlled CAS path'
            USING ERRCODE = '42501';
    END IF;

    RETURN NEW;
END;
$guard$;

REVOKE ALL ON FUNCTION public.pr_d_guard_capture_fields()
    FROM PUBLIC, anon, authenticated, service_role;

DROP TRIGGER IF EXISTS youtube_shorts_log_pr_d_capture_guard
    ON public.youtube_shorts_log;
CREATE TRIGGER youtube_shorts_log_pr_d_capture_guard
    BEFORE INSERT OR UPDATE OR DELETE ON public.youtube_shorts_log
    FOR EACH ROW
    EXECUTE FUNCTION public.pr_d_guard_capture_fields();

-- Private SECURITY DEFINER helper: its owner has only SELECT plus UPDATE on
-- the four capture columns and an explicit RLS policy. The JWT role check
-- prevents use through a non-service Data API request. The schema is not
-- exposed to PostgREST; only the invoker wrapper below is exposed.
CREATE OR REPLACE FUNCTION pr_d_internal.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $capture$
DECLARE
    v_claims jsonb;
    v_updated integer;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION
            'prd_capture_role_denied: service_role JWT claim required'
            USING ERRCODE = '42501';
    END IF;

    IF p_views IS NULL
       OR p_views < 0
       OR p_views > 18446744073709551615
       OR p_views <> trunc(p_views)
       OR p_published_at IS NULL
       OR p_sync_captured_at IS NULL
       OR p_sync_captured_at < p_published_at + interval '2 hours 55 minutes'
       OR p_sync_captured_at > p_published_at + interval '3 hours 5 minutes' THEN
        RETURN false;
    END IF;

    UPDATE public.youtube_shorts_log
       SET views_primeras_3h = p_views,
           published_at = p_published_at,
           sync_captured_at = p_sync_captured_at,
           elapsed_seconds_e12 =
               EXTRACT(EPOCH FROM (p_sync_captured_at - p_published_at))
     WHERE id = p_row_id
       AND youtube_video_id = p_youtube_video_id
       AND views_primeras_3h IS NULL
       AND published_at IS NULL
       AND sync_captured_at IS NULL
       AND elapsed_seconds_e12 IS NULL
       AND hs_al_publicar_al_sync IS NULL;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$capture$;

ALTER FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz
) OWNER TO pr_d_capture_owner;

REVOKE ALL ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz
) TO service_role;

-- PostgREST calls only this SECURITY INVOKER wrapper in the exposed public
-- schema. The private helper is not part of the Data API schema surface.
DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(
    bigint, text, integer, timestamptz, timestamptz
);
CREATE OR REPLACE FUNCTION public.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz
)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $wrapper$
    SELECT pr_d_internal.pr_d_capture_views_once(
        p_row_id, p_youtube_video_id, p_views,
        p_published_at, p_sync_captured_at
    );
$wrapper$;

REVOKE ALL ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz
) TO service_role;

CREATE INDEX IF NOT EXISTS youtube_shorts_log_sync_capture_pending_idx
    ON public.youtube_shorts_log (id)
    WHERE views_primeras_3h IS NULL;
