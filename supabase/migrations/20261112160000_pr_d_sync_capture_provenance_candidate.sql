-- SANDBOX CANDIDATE ONLY. Never apply to a live project from this branch.
-- Adds explicit YouTube publication and observation instants without changing
-- legacy rows or assuming youtube_video_id is the primary key.
-- A dedicated non-login owner is the only principal allowed to change the
-- protected capture columns. service_role can call the RPC but cannot SET ROLE
-- to this principal; no membership is granted to any login/API role.
DO $capture_writer_role$
DECLARE
    v_role_oid oid;
BEGIN
    SELECT oid INTO v_role_oid FROM pg_roles WHERE rolname = 'pr_d_capture_writer';
    IF v_role_oid IS NULL THEN
        EXECUTE 'CREATE ROLE pr_d_capture_writer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS';
    ELSE
        IF EXISTS (
            SELECT 1 FROM pg_roles
            WHERE oid = v_role_oid
              AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit OR rolreplication OR rolbypassrls)
        ) OR EXISTS (
            SELECT 1 FROM pg_auth_members
            WHERE roleid = v_role_oid OR member = v_role_oid
        ) THEN
            RAISE EXCEPTION
                'prd_capture_writer_role_misconfigured: dedicated role must be NOLOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOINHERIT, NOREPLICATION, NOBYPASSRLS, and have no memberships';
        END IF;
    END IF;
END;
$capture_writer_role$;


-- Add provenance columns only after the privileged-role preflight passes.
ALTER TABLE public.youtube_shorts_log
    ADD COLUMN IF NOT EXISTS published_at timestamptz,
    ADD COLUMN IF NOT EXISTS sync_captured_at timestamptz;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'youtube_shorts_log_sync_capture_window_ck'
          AND conrelid = 'public.youtube_shorts_log'::regclass
    ) THEN
        ALTER TABLE public.youtube_shorts_log
            ADD CONSTRAINT youtube_shorts_log_sync_capture_window_ck
            CHECK (
                (published_at IS NULL AND sync_captured_at IS NULL)
                OR (
                    published_at IS NOT NULL
                    AND sync_captured_at IS NOT NULL
                    AND views_primeras_3h IS NOT NULL
                    AND views_primeras_3h >= 0
                    AND sync_captured_at >= published_at + interval '2 hours 55 minutes'
                    AND sync_captured_at <= published_at + interval '3 hours 5 minutes'
                )
            );
    END IF;
END;
$migration$;

-- YouTube documents viewCount as an unsigned 64-bit integer. numeric(20,0)
-- preserves the full uint64 range; PostgreSQL integer/bigint cannot represent it.
-- Preflight before widening so no legacy value is rewritten on a rejected migration.
DO $views_nonnegative$
DECLARE
    v_invalid_rows bigint;
BEGIN
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

    -- A prior candidate may already have installed the guard trigger. Drop only
    -- this known trigger inside the migration transaction before changing the
    -- referenced column type; it is recreated below before commit.
    DROP TRIGGER IF EXISTS youtube_shorts_log_capture_write_guard
        ON public.youtube_shorts_log;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'youtube_shorts_log'
          AND column_name = 'views_primeras_3h'
          AND data_type = 'numeric'
          AND numeric_precision = 20
          AND numeric_scale = 0
    ) THEN
        ALTER TABLE public.youtube_shorts_log
            ALTER COLUMN views_primeras_3h TYPE numeric(20,0)
            USING views_primeras_3h::numeric(20,0);
    END IF;

    ALTER TABLE public.youtube_shorts_log
        DROP CONSTRAINT IF EXISTS youtube_shorts_log_views_nonnegative_ck;
    ALTER TABLE public.youtube_shorts_log
        ADD CONSTRAINT youtube_shorts_log_views_nonnegative_ck
        CHECK (views_primeras_3h IS NULL OR (
            views_primeras_3h >= 0
            AND views_primeras_3h <= 18446744073709551615
            AND views_primeras_3h = trunc(views_primeras_3h)
        ));
END;
$views_nonnegative$;

GRANT USAGE ON SCHEMA public TO pr_d_capture_writer;
GRANT SELECT ON public.youtube_shorts_log TO pr_d_capture_writer;
GRANT UPDATE (views_primeras_3h, published_at, sync_captured_at)
    ON public.youtube_shorts_log TO pr_d_capture_writer;
DROP POLICY IF EXISTS pr_d_capture_writer_select ON public.youtube_shorts_log;
CREATE POLICY pr_d_capture_writer_select
    ON public.youtube_shorts_log FOR SELECT TO pr_d_capture_writer USING (true);
DROP POLICY IF EXISTS pr_d_capture_writer_update ON public.youtube_shorts_log;
CREATE POLICY pr_d_capture_writer_update
    ON public.youtube_shorts_log FOR UPDATE TO pr_d_capture_writer USING (true) WITH CHECK (true);
GRANT CREATE ON SCHEMA public TO pr_d_capture_writer;

-- The guard preserves old rows and unrelated updates, but rejects every new
-- direct write to the capture fields unless it runs as the dedicated RPC owner.
CREATE OR REPLACE FUNCTION public.pr_d_guard_capture_write()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.views_primeras_3h IS NOT NULL
           OR OLD.published_at IS NOT NULL
           OR OLD.sync_captured_at IS NOT NULL THEN
            RAISE EXCEPTION 'prd_capture_evidence_delete_prohibited'
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF (
            NEW.views_primeras_3h IS NOT NULL
            OR NEW.published_at IS NOT NULL
            OR NEW.sync_captured_at IS NOT NULL
        ) AND current_user <> 'pr_d_capture_writer' THEN
            RAISE EXCEPTION 'prd_capture_write_requires_rpc'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.views_primeras_3h IS NOT NULL
       AND NEW.youtube_video_id IS DISTINCT FROM OLD.youtube_video_id THEN
        RAISE EXCEPTION 'prd_capture_video_identity_is_immutable'
            USING ERRCODE = '42501';
    END IF;

    IF (
        NEW.views_primeras_3h IS DISTINCT FROM OLD.views_primeras_3h
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
        OR NEW.sync_captured_at IS DISTINCT FROM OLD.sync_captured_at
    ) AND current_user <> 'pr_d_capture_writer' THEN
        RAISE EXCEPTION 'prd_capture_write_requires_rpc'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$guard$;

DROP TRIGGER IF EXISTS youtube_shorts_log_capture_write_guard
    ON public.youtube_shorts_log;
CREATE TRIGGER youtube_shorts_log_capture_write_guard
    BEFORE INSERT OR UPDATE OF youtube_video_id, views_primeras_3h, published_at, sync_captured_at OR DELETE
    ON public.youtube_shorts_log
    FOR EACH ROW EXECUTE FUNCTION public.pr_d_guard_capture_write();
REVOKE ALL ON FUNCTION public.pr_d_guard_capture_write() FROM PUBLIC, anon, authenticated, service_role;

-- Temporarily grant the migration executor membership so CREATE OR REPLACE
-- remains replayable after the function has been transferred to the owner role.
DO $capture_owner_membership$
BEGIN
    EXECUTE format('GRANT pr_d_capture_writer TO %I WITH ADMIN OPTION', current_user);
END;
$capture_owner_membership$;

-- Remove the earlier int32 overload from this candidate if the migration is replayed.
DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(bigint, text, integer, timestamptz, timestamptz);

-- SECURITY DEFINER runs as the isolated writer role. The role has only SELECT
-- and UPDATE on the three capture columns; it cannot log in or be assumed by
-- service_role. A fixed search_path and qualified object names prevent shadowing.
CREATE OR REPLACE FUNCTION public.pr_d_capture_views_once(
    p_row_id bigint, p_youtube_video_id text, p_views numeric,
    p_published_at timestamptz, p_sync_captured_at timestamptz
)
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    WITH changed AS (
        UPDATE public.youtube_shorts_log
        SET views_primeras_3h = p_views,
            published_at = p_published_at,
            sync_captured_at = p_sync_captured_at
        WHERE id = p_row_id
          AND youtube_video_id = p_youtube_video_id
          AND views_primeras_3h IS NULL
          AND published_at IS NULL
          AND sync_captured_at IS NULL
          AND p_views IS NOT NULL
          AND p_views >= 0
          AND p_views <= 18446744073709551615
          AND p_views = trunc(p_views)
          AND p_published_at IS NOT NULL
          AND p_sync_captured_at >= p_published_at + interval '2 hours 55 minutes'
          AND p_sync_captured_at <= p_published_at + interval '3 hours 5 minutes'
        RETURNING id
    )
    SELECT EXISTS (SELECT 1 FROM changed);
$function$;

DO $capture_owner_transfer$
BEGIN
    EXECUTE 'ALTER FUNCTION public.pr_d_capture_views_once(bigint, text, numeric, timestamptz, timestamptz) OWNER TO pr_d_capture_writer';
    EXECUTE format('REVOKE pr_d_capture_writer FROM %I', current_user);
END;
$capture_owner_transfer$;
REVOKE CREATE ON SCHEMA public FROM pr_d_capture_writer;

-- Least privilege: PostgreSQL grants EXECUTE on new functions to PUBLIC by default.
REVOKE ALL ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz
) TO service_role;

-- TRUNCATE bypasses row-level triggers and would erase captured evidence in bulk.
-- API roles do not need DDL/foreign-key privileges on this table.
REVOKE TRUNCATE, TRIGGER, REFERENCES
    ON TABLE public.youtube_shorts_log
    FROM PUBLIC, anon, authenticated, service_role;

CREATE INDEX IF NOT EXISTS youtube_shorts_log_sync_capture_pending_idx
    ON public.youtube_shorts_log (id)
    WHERE views_primeras_3h IS NULL;
