-- SANDBOX CANDIDATE ONLY. Generate the versioned migration with
-- supabase migration new e12_worker_lease_fencing before committing.
-- Prerequisites: the capture-provenance migration has created pr_d_capture_owner,
-- pr_d_internal, and the existing five-argument capture CAS function.

DO $preflight$
DECLARE v_owner oid;
BEGIN
    SELECT oid INTO v_owner FROM pg_roles WHERE rolname = 'pr_d_capture_owner';
    IF v_owner IS NULL THEN
        RAISE EXCEPTION 'prd_e12_lease_preflight_failed: pr_d_capture_owner missing';
    END IF;
    IF (SELECT nspowner FROM pg_namespace WHERE nspname = 'pr_d_internal') <> v_owner THEN
        RAISE EXCEPTION 'prd_e12_lease_preflight_failed: pr_d_internal owner mismatch';
    END IF;
    IF to_regprocedure('pr_d_internal.pr_d_capture_views_once(bigint,text,numeric,timestamp with time zone,timestamp with time zone)') IS NULL THEN
        RAISE EXCEPTION 'prd_e12_lease_preflight_failed: existing capture CAS function missing';
    END IF;
END;
$preflight$;

CREATE TABLE pr_d_internal.e12_worker_lease (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    owner_run_id uuid NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    fencing_token bigint NOT NULL CHECK (fencing_token > 0),
    heartbeat_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
ALTER TABLE pr_d_internal.e12_worker_lease OWNER TO pr_d_capture_owner;
REVOKE ALL ON TABLE pr_d_internal.e12_worker_lease FROM PUBLIC, anon, authenticated, service_role;
COMMENT ON TABLE pr_d_internal.e12_worker_lease IS
    'Single active E12 execution lease. Fencing token increases on takeover and is checked in the capture transaction.';

CREATE OR REPLACE FUNCTION pr_d_internal.pr_d_claim_e12_worker_lease(p_run_id uuid, p_ttl_seconds integer)
RETURNS TABLE(acquired boolean, fencing_token text, lease_expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $claim$
DECLARE
    v_claims jsonb;
    v_token bigint;
    v_expiry timestamptz;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_e12_lease_role_denied: service_role JWT claim required' USING ERRCODE = '42501';
    END IF;
    IF p_run_id IS NULL OR p_ttl_seconds IS NULL OR p_ttl_seconds < 30 OR p_ttl_seconds > 300 THEN
        RAISE EXCEPTION 'prd_e12_lease_arguments_invalid' USING ERRCODE = '22023';
    END IF;

    INSERT INTO pr_d_internal.e12_worker_lease AS lease (
        singleton, owner_run_id, lease_expires_at, fencing_token, heartbeat_at, updated_at
    ) VALUES (
        true, p_run_id, clock_timestamp() + make_interval(secs => p_ttl_seconds), 1, clock_timestamp(), clock_timestamp()
    )
    ON CONFLICT (singleton) DO UPDATE
       SET owner_run_id = EXCLUDED.owner_run_id,
           lease_expires_at = EXCLUDED.lease_expires_at,
           fencing_token = CASE WHEN lease.lease_expires_at <= clock_timestamp()
                                THEN lease.fencing_token + 1 ELSE lease.fencing_token END,
           heartbeat_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE (lease.lease_expires_at <= clock_timestamp() AND lease.fencing_token < 9223372036854775807)
        OR (lease.owner_run_id = EXCLUDED.owner_run_id AND lease.lease_expires_at > clock_timestamp())
    RETURNING lease.fencing_token, lease.lease_expires_at INTO v_token, v_expiry;

    IF NOT FOUND THEN
        RETURN QUERY SELECT false, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY SELECT true, v_token::text, v_expiry;
END;
$claim$;

CREATE OR REPLACE FUNCTION pr_d_internal.pr_d_renew_e12_worker_lease(
    p_run_id uuid, p_fencing_token bigint, p_ttl_seconds integer
)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $renew$
DECLARE v_claims jsonb; v_now timestamptz; v_updated integer;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_e12_lease_role_denied: service_role JWT claim required' USING ERRCODE = '42501';
    END IF;
    IF p_run_id IS NULL OR p_fencing_token IS NULL OR p_ttl_seconds IS NULL
       OR p_ttl_seconds < 30 OR p_ttl_seconds > 300 THEN
        RAISE EXCEPTION 'prd_e12_lease_arguments_invalid' USING ERRCODE = '22023';
    END IF;
    v_now := clock_timestamp();
    UPDATE pr_d_internal.e12_worker_lease
       SET lease_expires_at = clock_timestamp() + make_interval(secs => p_ttl_seconds),
           heartbeat_at = clock_timestamp(), updated_at = clock_timestamp()
     WHERE singleton AND owner_run_id = p_run_id AND fencing_token = p_fencing_token
       AND lease_expires_at > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$renew$;

CREATE OR REPLACE FUNCTION pr_d_internal.pr_d_release_e12_worker_lease(p_run_id uuid, p_fencing_token bigint)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $release$
DECLARE v_claims jsonb; v_now timestamptz; v_updated integer;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_e12_lease_role_denied: service_role JWT claim required' USING ERRCODE = '42501';
    END IF;
    IF p_run_id IS NULL OR p_fencing_token IS NULL THEN
        RAISE EXCEPTION 'prd_e12_lease_arguments_invalid' USING ERRCODE = '22023';
    END IF;
    v_now := clock_timestamp();
    UPDATE pr_d_internal.e12_worker_lease
       SET lease_expires_at = clock_timestamp(), heartbeat_at = clock_timestamp(), updated_at = clock_timestamp()
     WHERE singleton AND owner_run_id = p_run_id AND fencing_token = p_fencing_token
       AND lease_expires_at > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$release$;

ALTER FUNCTION pr_d_internal.pr_d_claim_e12_worker_lease(uuid, integer) OWNER TO pr_d_capture_owner;
ALTER FUNCTION pr_d_internal.pr_d_renew_e12_worker_lease(uuid, bigint, integer) OWNER TO pr_d_capture_owner;
ALTER FUNCTION pr_d_internal.pr_d_release_e12_worker_lease(uuid, bigint) OWNER TO pr_d_capture_owner;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_claim_e12_worker_lease(uuid, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_renew_e12_worker_lease(uuid, bigint, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_release_e12_worker_lease(uuid, bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_claim_e12_worker_lease(uuid, integer) TO service_role;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_renew_e12_worker_lease(uuid, bigint, integer) TO service_role;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_release_e12_worker_lease(uuid, bigint) TO service_role;

CREATE OR REPLACE FUNCTION public.pr_d_claim_e12_worker_lease(p_run_id uuid, p_ttl_seconds integer)
RETURNS TABLE(acquired boolean, fencing_token text, lease_expires_at timestamptz)
LANGUAGE sql SECURITY INVOKER SET search_path = pg_catalog, public
AS $wrapper$ SELECT * FROM pr_d_internal.pr_d_claim_e12_worker_lease(p_run_id, p_ttl_seconds); $wrapper$;

CREATE OR REPLACE FUNCTION public.pr_d_renew_e12_worker_lease(p_run_id uuid, p_fencing_token bigint, p_ttl_seconds integer)
RETURNS boolean LANGUAGE sql SECURITY INVOKER SET search_path = pg_catalog, public
AS $wrapper$ SELECT pr_d_internal.pr_d_renew_e12_worker_lease(p_run_id, p_fencing_token, p_ttl_seconds); $wrapper$;

CREATE OR REPLACE FUNCTION public.pr_d_release_e12_worker_lease(p_run_id uuid, p_fencing_token bigint)
RETURNS boolean LANGUAGE sql SECURITY INVOKER SET search_path = pg_catalog, public
AS $wrapper$ SELECT pr_d_internal.pr_d_release_e12_worker_lease(p_run_id, p_fencing_token); $wrapper$;

REVOKE ALL ON FUNCTION public.pr_d_claim_e12_worker_lease(uuid, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.pr_d_renew_e12_worker_lease(uuid, bigint, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.pr_d_release_e12_worker_lease(uuid, bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_claim_e12_worker_lease(uuid, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.pr_d_renew_e12_worker_lease(uuid, bigint, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.pr_d_release_e12_worker_lease(uuid, bigint) TO service_role;

-- Remove old CAS signatures so no caller can bypass fencing after upgrade.
DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(bigint, text, numeric, timestamptz, timestamptz);
DROP FUNCTION IF EXISTS pr_d_internal.pr_d_capture_views_once(bigint, text, numeric, timestamptz, timestamptz);

CREATE FUNCTION pr_d_internal.pr_d_capture_views_once(
    p_row_id bigint, p_youtube_video_id text, p_views numeric,
    p_published_at timestamptz, p_sync_captured_at timestamptz,
    p_run_id uuid, p_fencing_token bigint
)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $capture$
DECLARE
    v_claims jsonb;
    v_updated integer;
    v_lease_live boolean;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_capture_role_denied: service_role JWT claim required' USING ERRCODE = '42501';
    END IF;
    IF p_views IS NULL OR p_views < 0 OR p_views > 18446744073709551615
       OR p_views <> trunc(p_views) OR p_published_at IS NULL OR p_sync_captured_at IS NULL
       OR p_run_id IS NULL OR p_fencing_token IS NULL
       OR p_sync_captured_at < p_published_at + interval '2 hours 55 minutes'
       OR p_sync_captured_at > p_published_at + interval '3 hours 5 minutes' THEN
        RETURN false;
    END IF;

    -- The row lock prevents lease takeover between authorization and CAS write.
    SELECT true INTO v_lease_live
      FROM pr_d_internal.e12_worker_lease
     WHERE singleton AND owner_run_id = p_run_id AND fencing_token = p_fencing_token
       AND lease_expires_at > clock_timestamp()
     FOR UPDATE;
    IF NOT COALESCE(v_lease_live, false) THEN RETURN false; END IF;

    UPDATE public.youtube_shorts_log
       SET views_primeras_3h = p_views,
           published_at = p_published_at,
           sync_captured_at = p_sync_captured_at,
           elapsed_seconds_e12 = EXTRACT(EPOCH FROM (p_sync_captured_at - p_published_at))
     WHERE id = p_row_id AND youtube_video_id = p_youtube_video_id
       AND views_primeras_3h IS NULL AND published_at IS NULL
       AND sync_captured_at IS NULL AND elapsed_seconds_e12 IS NULL
       AND hs_al_publicar_al_sync IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$capture$;

ALTER FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
) OWNER TO pr_d_capture_owner;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
) TO service_role;

CREATE FUNCTION public.pr_d_capture_views_once(
    p_row_id bigint, p_youtube_video_id text, p_views numeric,
    p_published_at timestamptz, p_sync_captured_at timestamptz,
    p_run_id uuid, p_fencing_token bigint
)
RETURNS boolean LANGUAGE sql SECURITY INVOKER SET search_path = pg_catalog, public
AS $wrapper$
    SELECT pr_d_internal.pr_d_capture_views_once(
        p_row_id, p_youtube_video_id, p_views, p_published_at,
        p_sync_captured_at, p_run_id, p_fencing_token
    );
$wrapper$;
REVOKE ALL ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
) TO service_role;
