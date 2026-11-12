-- SANDBOX CANDIDATE ONLY.
-- Depends on 20261112231203_e12_worker_lease_fencing.sql.
-- Ed25519 signatures are verified by the worker and independently offline;
-- PostgreSQL binds and stores the signed canonical payload and trusted key ID,
-- but does not claim to verify Ed25519 itself.

DO $preflight$
BEGIN
    IF to_regprocedure('pr_d_internal.pr_d_capture_views_once(bigint,text,numeric,timestamp with time zone,timestamp with time zone,uuid,bigint)') IS NULL THEN
        RAISE EXCEPTION 'prd_e12_attestation_preflight_failed: fenced capture CAS function missing';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pr_d_capture_owner') THEN
        RAISE EXCEPTION 'prd_e12_attestation_preflight_failed: capture owner role missing';
    END IF;
END;
$preflight$;

ALTER TABLE public.youtube_shorts_log
    ADD COLUMN IF NOT EXISTS e12_capture_run_id uuid,
    ADD COLUMN IF NOT EXISTS e12_fencing_token bigint,
    ADD COLUMN IF NOT EXISTS collector_attestation_version text,
    ADD COLUMN IF NOT EXISTS collector_attestation_algorithm text,
    ADD COLUMN IF NOT EXISTS collector_key_id text,
    ADD COLUMN IF NOT EXISTS collector_public_key_spki_base64 text,
    ADD COLUMN IF NOT EXISTS collector_payload_canonical text,
    ADD COLUMN IF NOT EXISTS collector_payload_sha256 text,
    ADD COLUMN IF NOT EXISTS collector_signature text,
    ADD COLUMN IF NOT EXISTS collector_response_sha256 text,
    ADD COLUMN IF NOT EXISTS collector_requested_ids_sha256 text,
    ADD COLUMN IF NOT EXISTS collector_build text;

CREATE TABLE pr_d_internal.e12_collector_key_registry (
    key_id text PRIMARY KEY CHECK (key_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    algorithm text NOT NULL CHECK (algorithm = 'Ed25519'),
    public_key_spki_base64 text NOT NULL
        CHECK (public_key_spki_base64 ~ '^[A-Za-z0-9+/]{59}=$'),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revoked_at timestamptz,
    CHECK (
        (status = 'active' AND revoked_at IS NULL)
        OR (status = 'revoked' AND revoked_at IS NOT NULL)
    )
);
ALTER TABLE pr_d_internal.e12_collector_key_registry OWNER TO pr_d_capture_owner;
REVOKE ALL ON TABLE pr_d_internal.e12_collector_key_registry
    FROM PUBLIC, anon, authenticated, service_role;
COMMENT ON TABLE pr_d_internal.e12_collector_key_registry IS
    'Admin-controlled Ed25519 public-key trust registry. The worker role has no direct write access.';

GRANT UPDATE (
    e12_capture_run_id,
    e12_fencing_token,
    collector_attestation_version,
    collector_attestation_algorithm,
    collector_key_id,
    collector_public_key_spki_base64,
    collector_payload_canonical,
    collector_payload_sha256,
    collector_signature,
    collector_response_sha256,
    collector_requested_ids_sha256,
    collector_build
) ON public.youtube_shorts_log TO pr_d_capture_owner;

ALTER TABLE public.youtube_shorts_log
    DROP CONSTRAINT IF EXISTS youtube_shorts_log_sync_capture_window_ck;
ALTER TABLE public.youtube_shorts_log
    ADD CONSTRAINT youtube_shorts_log_sync_capture_window_ck
    CHECK (
        (
            -- Legacy rows may predate the collector attestation columns.
            e12_capture_run_id IS NULL
            AND e12_fencing_token IS NULL
            AND collector_attestation_version IS NULL
            AND collector_attestation_algorithm IS NULL
            AND collector_key_id IS NULL
            AND collector_public_key_spki_base64 IS NULL
            AND collector_payload_canonical IS NULL
            AND collector_payload_sha256 IS NULL
            AND collector_signature IS NULL
            AND collector_response_sha256 IS NULL
            AND collector_requested_ids_sha256 IS NULL
            AND collector_build IS NULL
            AND (
                (published_at IS NULL AND sync_captured_at IS NULL AND elapsed_seconds_e12 IS NULL)
                OR (
                    published_at IS NOT NULL
                    AND sync_captured_at IS NOT NULL
                    AND views_primeras_3h IS NOT NULL
                    AND views_primeras_3h >= 0
                    AND elapsed_seconds_e12 IS NOT NULL
                    AND elapsed_seconds_e12 = EXTRACT(EPOCH FROM (sync_captured_at - published_at))
                    AND sync_captured_at >= published_at + interval '2 hours 55 minutes'
                    AND sync_captured_at <= published_at + interval '3 hours 5 minutes'
                )
            )
        )
        OR (
            published_at IS NOT NULL
            AND sync_captured_at IS NOT NULL
            AND views_primeras_3h IS NOT NULL
            AND views_primeras_3h >= 0
            AND elapsed_seconds_e12 IS NOT NULL
            AND elapsed_seconds_e12 = EXTRACT(EPOCH FROM (sync_captured_at - published_at))
            AND sync_captured_at >= published_at + interval '2 hours 55 minutes'
            AND sync_captured_at <= published_at + interval '3 hours 5 minutes'
            AND e12_capture_run_id IS NOT NULL
            AND e12_fencing_token IS NOT NULL
            AND e12_fencing_token > 0
            AND collector_attestation_version = 'e12-observation-attestation/v1'
            AND collector_attestation_algorithm = 'Ed25519'
            AND collector_key_id IS NOT NULL
            AND collector_public_key_spki_base64 IS NOT NULL
            AND collector_payload_canonical IS NOT NULL
            AND collector_payload_sha256 ~ '^[a-f0-9]{64}

CREATE OR REPLACE FUNCTION public.pr_d_guard_capture_fields()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            NEW.views_primeras_3h IS NOT NULL
            OR NEW.published_at IS NOT NULL
            OR NEW.sync_captured_at IS NOT NULL
            OR NEW.elapsed_seconds_e12 IS NOT NULL
            OR NEW.hs_al_publicar_al_sync IS NOT NULL
            OR NEW.e12_capture_run_id IS NOT NULL
            OR NEW.e12_fencing_token IS NOT NULL
            OR NEW.collector_attestation_version IS NOT NULL
            OR NEW.collector_attestation_algorithm IS NOT NULL
            OR NEW.collector_key_id IS NOT NULL
            OR NEW.collector_public_key_spki_base64 IS NOT NULL
            OR NEW.collector_payload_canonical IS NOT NULL
            OR NEW.collector_payload_sha256 IS NOT NULL
            OR NEW.collector_signature IS NOT NULL
            OR NEW.collector_response_sha256 IS NOT NULL
            OR NEW.collector_requested_ids_sha256 IS NOT NULL
            OR NEW.collector_build IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_write_denied: populated capture/attestation fields require controlled CAS'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            OLD.views_primeras_3h IS NOT NULL
            OR OLD.published_at IS NOT NULL
            OR OLD.sync_captured_at IS NOT NULL
            OR OLD.elapsed_seconds_e12 IS NOT NULL
            OR OLD.hs_al_publicar_al_sync IS NOT NULL
            OR OLD.e12_capture_run_id IS NOT NULL
            OR OLD.e12_fencing_token IS NOT NULL
            OR OLD.collector_signature IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_delete_denied: captured outcome rows are immutable'
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;

    IF current_user <> 'pr_d_capture_owner' AND (
        NEW.views_primeras_3h IS DISTINCT FROM OLD.views_primeras_3h
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
        OR NEW.sync_captured_at IS DISTINCT FROM OLD.sync_captured_at
        OR NEW.elapsed_seconds_e12 IS DISTINCT FROM OLD.elapsed_seconds_e12
        OR NEW.hs_al_publicar_al_sync IS DISTINCT FROM OLD.hs_al_publicar_al_sync
        OR NEW.e12_capture_run_id IS DISTINCT FROM OLD.e12_capture_run_id
        OR NEW.e12_fencing_token IS DISTINCT FROM OLD.e12_fencing_token
        OR NEW.collector_attestation_version IS DISTINCT FROM OLD.collector_attestation_version
        OR NEW.collector_attestation_algorithm IS DISTINCT FROM OLD.collector_attestation_algorithm
        OR NEW.collector_key_id IS DISTINCT FROM OLD.collector_key_id
        OR NEW.collector_public_key_spki_base64 IS DISTINCT FROM OLD.collector_public_key_spki_base64
        OR NEW.collector_payload_canonical IS DISTINCT FROM OLD.collector_payload_canonical
        OR NEW.collector_payload_sha256 IS DISTINCT FROM OLD.collector_payload_sha256
        OR NEW.collector_signature IS DISTINCT FROM OLD.collector_signature
        OR NEW.collector_response_sha256 IS DISTINCT FROM OLD.collector_response_sha256
        OR NEW.collector_requested_ids_sha256 IS DISTINCT FROM OLD.collector_requested_ids_sha256
        OR NEW.collector_build IS DISTINCT FROM OLD.collector_build
        OR (
            OLD.views_primeras_3h IS NOT NULL
            AND (
                NEW.youtube_video_id IS DISTINCT FROM OLD.youtube_video_id
                OR NEW.id IS DISTINCT FROM OLD.id
            )
        )
    ) THEN
        RAISE EXCEPTION 'prd_capture_write_denied: capture, attestation and captured identity are immutable'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$guard$;

REVOKE ALL ON FUNCTION public.pr_d_guard_capture_fields()
    FROM PUBLIC, anon, authenticated, service_role;

DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);
DROP FUNCTION IF EXISTS pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);

CREATE FUNCTION pr_d_internal.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $capture$
DECLARE
    v_claims jsonb;
    v_updated integer;
    v_lease_live boolean;
    v_key_registered boolean;
    v_payload jsonb;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_capture_role_denied: service_role JWT claim required'
            USING ERRCODE = '42501';
    END IF;

    IF p_views IS NULL OR p_views < 0 OR p_views > 18446744073709551615
       OR p_views <> trunc(p_views) OR p_published_at IS NULL OR p_sync_captured_at IS NULL
       OR p_run_id IS NULL OR p_fencing_token IS NULL OR p_fencing_token <= 0
       OR p_attestation_version IS DISTINCT FROM 'e12-observation-attestation/v1'
       OR p_attestation_algorithm IS DISTINCT FROM 'Ed25519'
       OR p_collector_key_id IS NULL
       OR p_collector_public_key_spki_base64 IS NULL
       OR p_collector_payload_canonical IS NULL
       OR p_collector_payload_sha256 IS NULL
       OR p_collector_signature IS NULL
       OR p_collector_response_sha256 IS NULL
       OR p_collector_requested_ids_sha256 IS NULL
       OR p_collector_build IS NULL
       OR p_collector_public_key_spki_base64 !~ '^[A-Za-z0-9+/]{59}=$'
       OR length(decode(p_collector_public_key_spki_base64, 'base64')) <> 44
       OR p_collector_payload_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_signature !~ '^[A-Za-z0-9+/]{86}==$'
       OR length(decode(p_collector_signature, 'base64')) <> 64
       OR p_collector_response_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_requested_ids_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_build !~ '^[A-Za-z0-9._+/-]{1,96}$'
       OR length(p_collector_payload_canonical) > 4096
       OR p_sync_captured_at < p_published_at + interval '2 hours 55 minutes'
       OR p_sync_captured_at > p_published_at + interval '3 hours 5 minutes' THEN
        RETURN false;
    END IF;

    BEGIN
        v_payload := p_collector_payload_canonical::jsonb;
    EXCEPTION WHEN others THEN
        RETURN false;
    END;

    IF jsonb_typeof(v_payload) IS DISTINCT FROM 'array' THEN
        RETURN false;
    END IF;
    IF jsonb_array_length(v_payload) <> 12
       OR v_payload ->> 0 IS DISTINCT FROM p_attestation_version
       OR v_payload ->> 1 IS DISTINCT FROM p_collector_key_id
       OR v_payload ->> 2 IS DISTINCT FROM p_run_id::text
       OR v_payload ->> 3 IS DISTINCT FROM p_fencing_token::text
       OR v_payload ->> 4 IS DISTINCT FROM p_row_id::text
       OR v_payload ->> 5 IS DISTINCT FROM p_youtube_video_id
       OR (v_payload ->> 6)::timestamptz IS DISTINCT FROM p_published_at
       OR v_payload ->> 7 IS DISTINCT FROM p_views::text
       OR (v_payload ->> 8)::timestamptz IS DISTINCT FROM p_sync_captured_at
       OR v_payload ->> 9 IS DISTINCT FROM p_collector_response_sha256
       OR v_payload ->> 10 IS DISTINCT FROM p_collector_requested_ids_sha256
       OR v_payload ->> 11 IS DISTINCT FROM p_collector_build THEN
        RETURN false;
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM pr_d_internal.e12_collector_key_registry
         WHERE key_id = p_collector_key_id
           AND algorithm = p_attestation_algorithm
           AND public_key_spki_base64 = p_collector_public_key_spki_base64
           AND status = 'active'
           AND revoked_at IS NULL
    ) INTO v_key_registered;
    IF NOT v_key_registered THEN RETURN false; END IF;

    -- Lock the lease row through the CAS transaction. A takeover cannot race
    -- between this authorization check and the protected write.
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
           elapsed_seconds_e12 = EXTRACT(EPOCH FROM (p_sync_captured_at - p_published_at)),
           e12_capture_run_id = p_run_id,
           e12_fencing_token = p_fencing_token,
           collector_attestation_version = p_attestation_version,
           collector_attestation_algorithm = p_attestation_algorithm,
           collector_key_id = p_collector_key_id,
           collector_public_key_spki_base64 = p_collector_public_key_spki_base64,
           collector_payload_canonical = p_collector_payload_canonical,
           collector_payload_sha256 = p_collector_payload_sha256,
           collector_signature = p_collector_signature,
           collector_response_sha256 = p_collector_response_sha256,
           collector_requested_ids_sha256 = p_collector_requested_ids_sha256,
           collector_build = p_collector_build
     WHERE id = p_row_id AND youtube_video_id = p_youtube_video_id
       AND views_primeras_3h IS NULL AND published_at IS NULL
       AND sync_captured_at IS NULL AND elapsed_seconds_e12 IS NULL
       AND hs_al_publicar_al_sync IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$capture$;

ALTER FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) OWNER TO pr_d_capture_owner;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

CREATE FUNCTION public.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $wrapper$
    SELECT pr_d_internal.pr_d_capture_views_once(
        p_row_id, p_youtube_video_id, p_views, p_published_at,
        p_sync_captured_at, p_run_id, p_fencing_token,
        p_attestation_version, p_attestation_algorithm, p_collector_key_id,
        p_collector_public_key_spki_base64, p_collector_payload_canonical,
        p_collector_payload_sha256, p_collector_signature,
        p_collector_response_sha256, p_collector_requested_ids_sha256,
        p_collector_build
    );
$wrapper$;

REVOKE ALL ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

            AND collector_signature ~ '^[A-Za-z0-9+/]{86}==

CREATE OR REPLACE FUNCTION public.pr_d_guard_capture_fields()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            NEW.views_primeras_3h IS NOT NULL
            OR NEW.published_at IS NOT NULL
            OR NEW.sync_captured_at IS NOT NULL
            OR NEW.elapsed_seconds_e12 IS NOT NULL
            OR NEW.hs_al_publicar_al_sync IS NOT NULL
            OR NEW.e12_capture_run_id IS NOT NULL
            OR NEW.e12_fencing_token IS NOT NULL
            OR NEW.collector_attestation_version IS NOT NULL
            OR NEW.collector_attestation_algorithm IS NOT NULL
            OR NEW.collector_key_id IS NOT NULL
            OR NEW.collector_public_key_spki_base64 IS NOT NULL
            OR NEW.collector_payload_canonical IS NOT NULL
            OR NEW.collector_payload_sha256 IS NOT NULL
            OR NEW.collector_signature IS NOT NULL
            OR NEW.collector_response_sha256 IS NOT NULL
            OR NEW.collector_requested_ids_sha256 IS NOT NULL
            OR NEW.collector_build IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_write_denied: populated capture/attestation fields require controlled CAS'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            OLD.views_primeras_3h IS NOT NULL
            OR OLD.published_at IS NOT NULL
            OR OLD.sync_captured_at IS NOT NULL
            OR OLD.elapsed_seconds_e12 IS NOT NULL
            OR OLD.hs_al_publicar_al_sync IS NOT NULL
            OR OLD.e12_capture_run_id IS NOT NULL
            OR OLD.e12_fencing_token IS NOT NULL
            OR OLD.collector_signature IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_delete_denied: captured outcome rows are immutable'
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;

    IF current_user <> 'pr_d_capture_owner' AND (
        NEW.views_primeras_3h IS DISTINCT FROM OLD.views_primeras_3h
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
        OR NEW.sync_captured_at IS DISTINCT FROM OLD.sync_captured_at
        OR NEW.elapsed_seconds_e12 IS DISTINCT FROM OLD.elapsed_seconds_e12
        OR NEW.hs_al_publicar_al_sync IS DISTINCT FROM OLD.hs_al_publicar_al_sync
        OR NEW.e12_capture_run_id IS DISTINCT FROM OLD.e12_capture_run_id
        OR NEW.e12_fencing_token IS DISTINCT FROM OLD.e12_fencing_token
        OR NEW.collector_attestation_version IS DISTINCT FROM OLD.collector_attestation_version
        OR NEW.collector_attestation_algorithm IS DISTINCT FROM OLD.collector_attestation_algorithm
        OR NEW.collector_key_id IS DISTINCT FROM OLD.collector_key_id
        OR NEW.collector_public_key_spki_base64 IS DISTINCT FROM OLD.collector_public_key_spki_base64
        OR NEW.collector_payload_canonical IS DISTINCT FROM OLD.collector_payload_canonical
        OR NEW.collector_payload_sha256 IS DISTINCT FROM OLD.collector_payload_sha256
        OR NEW.collector_signature IS DISTINCT FROM OLD.collector_signature
        OR NEW.collector_response_sha256 IS DISTINCT FROM OLD.collector_response_sha256
        OR NEW.collector_requested_ids_sha256 IS DISTINCT FROM OLD.collector_requested_ids_sha256
        OR NEW.collector_build IS DISTINCT FROM OLD.collector_build
        OR (
            OLD.views_primeras_3h IS NOT NULL
            AND (
                NEW.youtube_video_id IS DISTINCT FROM OLD.youtube_video_id
                OR NEW.id IS DISTINCT FROM OLD.id
            )
        )
    ) THEN
        RAISE EXCEPTION 'prd_capture_write_denied: capture, attestation and captured identity are immutable'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$guard$;

REVOKE ALL ON FUNCTION public.pr_d_guard_capture_fields()
    FROM PUBLIC, anon, authenticated, service_role;

DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);
DROP FUNCTION IF EXISTS pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);

CREATE FUNCTION pr_d_internal.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $capture$
DECLARE
    v_claims jsonb;
    v_updated integer;
    v_lease_live boolean;
    v_key_registered boolean;
    v_payload jsonb;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_capture_role_denied: service_role JWT claim required'
            USING ERRCODE = '42501';
    END IF;

    IF p_views IS NULL OR p_views < 0 OR p_views > 18446744073709551615
       OR p_views <> trunc(p_views) OR p_published_at IS NULL OR p_sync_captured_at IS NULL
       OR p_run_id IS NULL OR p_fencing_token IS NULL OR p_fencing_token <= 0
       OR p_attestation_version IS DISTINCT FROM 'e12-observation-attestation/v1'
       OR p_attestation_algorithm IS DISTINCT FROM 'Ed25519'
       OR p_collector_key_id IS NULL
       OR p_collector_public_key_spki_base64 !~ '^[A-Za-z0-9+/]{59}=$'
       OR length(decode(p_collector_public_key_spki_base64, 'base64')) <> 44
       OR p_collector_payload_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_signature !~ '^[A-Za-z0-9+/]{86}==$'
       OR length(decode(p_collector_signature, 'base64')) <> 64
       OR p_collector_response_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_requested_ids_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_build !~ '^[A-Za-z0-9._+/-]{1,96}$'
       OR p_collector_payload_canonical IS NULL
       OR length(p_collector_payload_canonical) > 4096
       OR p_sync_captured_at < p_published_at + interval '2 hours 55 minutes'
       OR p_sync_captured_at > p_published_at + interval '3 hours 5 minutes' THEN
        RETURN false;
    END IF;

    BEGIN
        v_payload := p_collector_payload_canonical::jsonb;
    EXCEPTION WHEN others THEN
        RETURN false;
    END;

    IF jsonb_typeof(v_payload) <> 'array'
       OR jsonb_array_length(v_payload) <> 12
       OR v_payload ->> 0 IS DISTINCT FROM p_attestation_version
       OR v_payload ->> 1 IS DISTINCT FROM p_collector_key_id
       OR v_payload ->> 2 IS DISTINCT FROM p_run_id::text
       OR v_payload ->> 3 IS DISTINCT FROM p_fencing_token::text
       OR v_payload ->> 4 IS DISTINCT FROM p_row_id::text
       OR v_payload ->> 5 IS DISTINCT FROM p_youtube_video_id
       OR (v_payload ->> 6)::timestamptz IS DISTINCT FROM p_published_at
       OR v_payload ->> 7 IS DISTINCT FROM p_views::text
       OR (v_payload ->> 8)::timestamptz IS DISTINCT FROM p_sync_captured_at
       OR v_payload ->> 9 IS DISTINCT FROM p_collector_response_sha256
       OR v_payload ->> 10 IS DISTINCT FROM p_collector_requested_ids_sha256
       OR v_payload ->> 11 IS DISTINCT FROM p_collector_build THEN
        RETURN false;
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM pr_d_internal.e12_collector_key_registry
         WHERE key_id = p_collector_key_id
           AND algorithm = p_attestation_algorithm
           AND public_key_spki_base64 = p_collector_public_key_spki_base64
           AND status = 'active'
           AND revoked_at IS NULL
    ) INTO v_key_registered;
    IF NOT v_key_registered THEN RETURN false; END IF;

    -- Lock the lease row through the CAS transaction. A takeover cannot race
    -- between this authorization check and the protected write.
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
           elapsed_seconds_e12 = EXTRACT(EPOCH FROM (p_sync_captured_at - p_published_at)),
           e12_capture_run_id = p_run_id,
           e12_fencing_token = p_fencing_token,
           collector_attestation_version = p_attestation_version,
           collector_attestation_algorithm = p_attestation_algorithm,
           collector_key_id = p_collector_key_id,
           collector_public_key_spki_base64 = p_collector_public_key_spki_base64,
           collector_payload_canonical = p_collector_payload_canonical,
           collector_payload_sha256 = p_collector_payload_sha256,
           collector_signature = p_collector_signature,
           collector_response_sha256 = p_collector_response_sha256,
           collector_requested_ids_sha256 = p_collector_requested_ids_sha256,
           collector_build = p_collector_build
     WHERE id = p_row_id AND youtube_video_id = p_youtube_video_id
       AND views_primeras_3h IS NULL AND published_at IS NULL
       AND sync_captured_at IS NULL AND elapsed_seconds_e12 IS NULL
       AND hs_al_publicar_al_sync IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$capture$;

ALTER FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) OWNER TO pr_d_capture_owner;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

CREATE FUNCTION public.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $wrapper$
    SELECT pr_d_internal.pr_d_capture_views_once(
        p_row_id, p_youtube_video_id, p_views, p_published_at,
        p_sync_captured_at, p_run_id, p_fencing_token,
        p_attestation_version, p_attestation_algorithm, p_collector_key_id,
        p_collector_public_key_spki_base64, p_collector_payload_canonical,
        p_collector_payload_sha256, p_collector_signature,
        p_collector_response_sha256, p_collector_requested_ids_sha256,
        p_collector_build
    );
$wrapper$;

REVOKE ALL ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

            AND collector_response_sha256 ~ '^[a-f0-9]{64}

CREATE OR REPLACE FUNCTION public.pr_d_guard_capture_fields()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            NEW.views_primeras_3h IS NOT NULL
            OR NEW.published_at IS NOT NULL
            OR NEW.sync_captured_at IS NOT NULL
            OR NEW.elapsed_seconds_e12 IS NOT NULL
            OR NEW.hs_al_publicar_al_sync IS NOT NULL
            OR NEW.e12_capture_run_id IS NOT NULL
            OR NEW.e12_fencing_token IS NOT NULL
            OR NEW.collector_attestation_version IS NOT NULL
            OR NEW.collector_attestation_algorithm IS NOT NULL
            OR NEW.collector_key_id IS NOT NULL
            OR NEW.collector_public_key_spki_base64 IS NOT NULL
            OR NEW.collector_payload_canonical IS NOT NULL
            OR NEW.collector_payload_sha256 IS NOT NULL
            OR NEW.collector_signature IS NOT NULL
            OR NEW.collector_response_sha256 IS NOT NULL
            OR NEW.collector_requested_ids_sha256 IS NOT NULL
            OR NEW.collector_build IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_write_denied: populated capture/attestation fields require controlled CAS'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            OLD.views_primeras_3h IS NOT NULL
            OR OLD.published_at IS NOT NULL
            OR OLD.sync_captured_at IS NOT NULL
            OR OLD.elapsed_seconds_e12 IS NOT NULL
            OR OLD.hs_al_publicar_al_sync IS NOT NULL
            OR OLD.e12_capture_run_id IS NOT NULL
            OR OLD.e12_fencing_token IS NOT NULL
            OR OLD.collector_signature IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_delete_denied: captured outcome rows are immutable'
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;

    IF current_user <> 'pr_d_capture_owner' AND (
        NEW.views_primeras_3h IS DISTINCT FROM OLD.views_primeras_3h
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
        OR NEW.sync_captured_at IS DISTINCT FROM OLD.sync_captured_at
        OR NEW.elapsed_seconds_e12 IS DISTINCT FROM OLD.elapsed_seconds_e12
        OR NEW.hs_al_publicar_al_sync IS DISTINCT FROM OLD.hs_al_publicar_al_sync
        OR NEW.e12_capture_run_id IS DISTINCT FROM OLD.e12_capture_run_id
        OR NEW.e12_fencing_token IS DISTINCT FROM OLD.e12_fencing_token
        OR NEW.collector_attestation_version IS DISTINCT FROM OLD.collector_attestation_version
        OR NEW.collector_attestation_algorithm IS DISTINCT FROM OLD.collector_attestation_algorithm
        OR NEW.collector_key_id IS DISTINCT FROM OLD.collector_key_id
        OR NEW.collector_public_key_spki_base64 IS DISTINCT FROM OLD.collector_public_key_spki_base64
        OR NEW.collector_payload_canonical IS DISTINCT FROM OLD.collector_payload_canonical
        OR NEW.collector_payload_sha256 IS DISTINCT FROM OLD.collector_payload_sha256
        OR NEW.collector_signature IS DISTINCT FROM OLD.collector_signature
        OR NEW.collector_response_sha256 IS DISTINCT FROM OLD.collector_response_sha256
        OR NEW.collector_requested_ids_sha256 IS DISTINCT FROM OLD.collector_requested_ids_sha256
        OR NEW.collector_build IS DISTINCT FROM OLD.collector_build
        OR (
            OLD.views_primeras_3h IS NOT NULL
            AND (
                NEW.youtube_video_id IS DISTINCT FROM OLD.youtube_video_id
                OR NEW.id IS DISTINCT FROM OLD.id
            )
        )
    ) THEN
        RAISE EXCEPTION 'prd_capture_write_denied: capture, attestation and captured identity are immutable'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$guard$;

REVOKE ALL ON FUNCTION public.pr_d_guard_capture_fields()
    FROM PUBLIC, anon, authenticated, service_role;

DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);
DROP FUNCTION IF EXISTS pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);

CREATE FUNCTION pr_d_internal.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $capture$
DECLARE
    v_claims jsonb;
    v_updated integer;
    v_lease_live boolean;
    v_key_registered boolean;
    v_payload jsonb;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_capture_role_denied: service_role JWT claim required'
            USING ERRCODE = '42501';
    END IF;

    IF p_views IS NULL OR p_views < 0 OR p_views > 18446744073709551615
       OR p_views <> trunc(p_views) OR p_published_at IS NULL OR p_sync_captured_at IS NULL
       OR p_run_id IS NULL OR p_fencing_token IS NULL OR p_fencing_token <= 0
       OR p_attestation_version IS DISTINCT FROM 'e12-observation-attestation/v1'
       OR p_attestation_algorithm IS DISTINCT FROM 'Ed25519'
       OR p_collector_key_id IS NULL
       OR p_collector_public_key_spki_base64 !~ '^[A-Za-z0-9+/]{59}=$'
       OR length(decode(p_collector_public_key_spki_base64, 'base64')) <> 44
       OR p_collector_payload_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_signature !~ '^[A-Za-z0-9+/]{86}==$'
       OR length(decode(p_collector_signature, 'base64')) <> 64
       OR p_collector_response_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_requested_ids_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_build !~ '^[A-Za-z0-9._+/-]{1,96}$'
       OR p_collector_payload_canonical IS NULL
       OR length(p_collector_payload_canonical) > 4096
       OR p_sync_captured_at < p_published_at + interval '2 hours 55 minutes'
       OR p_sync_captured_at > p_published_at + interval '3 hours 5 minutes' THEN
        RETURN false;
    END IF;

    BEGIN
        v_payload := p_collector_payload_canonical::jsonb;
    EXCEPTION WHEN others THEN
        RETURN false;
    END;

    IF jsonb_typeof(v_payload) <> 'array'
       OR jsonb_array_length(v_payload) <> 12
       OR v_payload ->> 0 IS DISTINCT FROM p_attestation_version
       OR v_payload ->> 1 IS DISTINCT FROM p_collector_key_id
       OR v_payload ->> 2 IS DISTINCT FROM p_run_id::text
       OR v_payload ->> 3 IS DISTINCT FROM p_fencing_token::text
       OR v_payload ->> 4 IS DISTINCT FROM p_row_id::text
       OR v_payload ->> 5 IS DISTINCT FROM p_youtube_video_id
       OR (v_payload ->> 6)::timestamptz IS DISTINCT FROM p_published_at
       OR v_payload ->> 7 IS DISTINCT FROM p_views::text
       OR (v_payload ->> 8)::timestamptz IS DISTINCT FROM p_sync_captured_at
       OR v_payload ->> 9 IS DISTINCT FROM p_collector_response_sha256
       OR v_payload ->> 10 IS DISTINCT FROM p_collector_requested_ids_sha256
       OR v_payload ->> 11 IS DISTINCT FROM p_collector_build THEN
        RETURN false;
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM pr_d_internal.e12_collector_key_registry
         WHERE key_id = p_collector_key_id
           AND algorithm = p_attestation_algorithm
           AND public_key_spki_base64 = p_collector_public_key_spki_base64
           AND status = 'active'
           AND revoked_at IS NULL
    ) INTO v_key_registered;
    IF NOT v_key_registered THEN RETURN false; END IF;

    -- Lock the lease row through the CAS transaction. A takeover cannot race
    -- between this authorization check and the protected write.
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
           elapsed_seconds_e12 = EXTRACT(EPOCH FROM (p_sync_captured_at - p_published_at)),
           e12_capture_run_id = p_run_id,
           e12_fencing_token = p_fencing_token,
           collector_attestation_version = p_attestation_version,
           collector_attestation_algorithm = p_attestation_algorithm,
           collector_key_id = p_collector_key_id,
           collector_public_key_spki_base64 = p_collector_public_key_spki_base64,
           collector_payload_canonical = p_collector_payload_canonical,
           collector_payload_sha256 = p_collector_payload_sha256,
           collector_signature = p_collector_signature,
           collector_response_sha256 = p_collector_response_sha256,
           collector_requested_ids_sha256 = p_collector_requested_ids_sha256,
           collector_build = p_collector_build
     WHERE id = p_row_id AND youtube_video_id = p_youtube_video_id
       AND views_primeras_3h IS NULL AND published_at IS NULL
       AND sync_captured_at IS NULL AND elapsed_seconds_e12 IS NULL
       AND hs_al_publicar_al_sync IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$capture$;

ALTER FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) OWNER TO pr_d_capture_owner;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

CREATE FUNCTION public.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $wrapper$
    SELECT pr_d_internal.pr_d_capture_views_once(
        p_row_id, p_youtube_video_id, p_views, p_published_at,
        p_sync_captured_at, p_run_id, p_fencing_token,
        p_attestation_version, p_attestation_algorithm, p_collector_key_id,
        p_collector_public_key_spki_base64, p_collector_payload_canonical,
        p_collector_payload_sha256, p_collector_signature,
        p_collector_response_sha256, p_collector_requested_ids_sha256,
        p_collector_build
    );
$wrapper$;

REVOKE ALL ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

            AND collector_requested_ids_sha256 ~ '^[a-f0-9]{64}

CREATE OR REPLACE FUNCTION public.pr_d_guard_capture_fields()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            NEW.views_primeras_3h IS NOT NULL
            OR NEW.published_at IS NOT NULL
            OR NEW.sync_captured_at IS NOT NULL
            OR NEW.elapsed_seconds_e12 IS NOT NULL
            OR NEW.hs_al_publicar_al_sync IS NOT NULL
            OR NEW.e12_capture_run_id IS NOT NULL
            OR NEW.e12_fencing_token IS NOT NULL
            OR NEW.collector_attestation_version IS NOT NULL
            OR NEW.collector_attestation_algorithm IS NOT NULL
            OR NEW.collector_key_id IS NOT NULL
            OR NEW.collector_public_key_spki_base64 IS NOT NULL
            OR NEW.collector_payload_canonical IS NOT NULL
            OR NEW.collector_payload_sha256 IS NOT NULL
            OR NEW.collector_signature IS NOT NULL
            OR NEW.collector_response_sha256 IS NOT NULL
            OR NEW.collector_requested_ids_sha256 IS NOT NULL
            OR NEW.collector_build IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_write_denied: populated capture/attestation fields require controlled CAS'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            OLD.views_primeras_3h IS NOT NULL
            OR OLD.published_at IS NOT NULL
            OR OLD.sync_captured_at IS NOT NULL
            OR OLD.elapsed_seconds_e12 IS NOT NULL
            OR OLD.hs_al_publicar_al_sync IS NOT NULL
            OR OLD.e12_capture_run_id IS NOT NULL
            OR OLD.e12_fencing_token IS NOT NULL
            OR OLD.collector_signature IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_delete_denied: captured outcome rows are immutable'
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;

    IF current_user <> 'pr_d_capture_owner' AND (
        NEW.views_primeras_3h IS DISTINCT FROM OLD.views_primeras_3h
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
        OR NEW.sync_captured_at IS DISTINCT FROM OLD.sync_captured_at
        OR NEW.elapsed_seconds_e12 IS DISTINCT FROM OLD.elapsed_seconds_e12
        OR NEW.hs_al_publicar_al_sync IS DISTINCT FROM OLD.hs_al_publicar_al_sync
        OR NEW.e12_capture_run_id IS DISTINCT FROM OLD.e12_capture_run_id
        OR NEW.e12_fencing_token IS DISTINCT FROM OLD.e12_fencing_token
        OR NEW.collector_attestation_version IS DISTINCT FROM OLD.collector_attestation_version
        OR NEW.collector_attestation_algorithm IS DISTINCT FROM OLD.collector_attestation_algorithm
        OR NEW.collector_key_id IS DISTINCT FROM OLD.collector_key_id
        OR NEW.collector_public_key_spki_base64 IS DISTINCT FROM OLD.collector_public_key_spki_base64
        OR NEW.collector_payload_canonical IS DISTINCT FROM OLD.collector_payload_canonical
        OR NEW.collector_payload_sha256 IS DISTINCT FROM OLD.collector_payload_sha256
        OR NEW.collector_signature IS DISTINCT FROM OLD.collector_signature
        OR NEW.collector_response_sha256 IS DISTINCT FROM OLD.collector_response_sha256
        OR NEW.collector_requested_ids_sha256 IS DISTINCT FROM OLD.collector_requested_ids_sha256
        OR NEW.collector_build IS DISTINCT FROM OLD.collector_build
        OR (
            OLD.views_primeras_3h IS NOT NULL
            AND (
                NEW.youtube_video_id IS DISTINCT FROM OLD.youtube_video_id
                OR NEW.id IS DISTINCT FROM OLD.id
            )
        )
    ) THEN
        RAISE EXCEPTION 'prd_capture_write_denied: capture, attestation and captured identity are immutable'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$guard$;

REVOKE ALL ON FUNCTION public.pr_d_guard_capture_fields()
    FROM PUBLIC, anon, authenticated, service_role;

DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);
DROP FUNCTION IF EXISTS pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);

CREATE FUNCTION pr_d_internal.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $capture$
DECLARE
    v_claims jsonb;
    v_updated integer;
    v_lease_live boolean;
    v_key_registered boolean;
    v_payload jsonb;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_capture_role_denied: service_role JWT claim required'
            USING ERRCODE = '42501';
    END IF;

    IF p_views IS NULL OR p_views < 0 OR p_views > 18446744073709551615
       OR p_views <> trunc(p_views) OR p_published_at IS NULL OR p_sync_captured_at IS NULL
       OR p_run_id IS NULL OR p_fencing_token IS NULL OR p_fencing_token <= 0
       OR p_attestation_version IS DISTINCT FROM 'e12-observation-attestation/v1'
       OR p_attestation_algorithm IS DISTINCT FROM 'Ed25519'
       OR p_collector_key_id IS NULL
       OR p_collector_public_key_spki_base64 !~ '^[A-Za-z0-9+/]{59}=$'
       OR length(decode(p_collector_public_key_spki_base64, 'base64')) <> 44
       OR p_collector_payload_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_signature !~ '^[A-Za-z0-9+/]{86}==$'
       OR length(decode(p_collector_signature, 'base64')) <> 64
       OR p_collector_response_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_requested_ids_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_build !~ '^[A-Za-z0-9._+/-]{1,96}$'
       OR p_collector_payload_canonical IS NULL
       OR length(p_collector_payload_canonical) > 4096
       OR p_sync_captured_at < p_published_at + interval '2 hours 55 minutes'
       OR p_sync_captured_at > p_published_at + interval '3 hours 5 minutes' THEN
        RETURN false;
    END IF;

    BEGIN
        v_payload := p_collector_payload_canonical::jsonb;
    EXCEPTION WHEN others THEN
        RETURN false;
    END;

    IF jsonb_typeof(v_payload) <> 'array'
       OR jsonb_array_length(v_payload) <> 12
       OR v_payload ->> 0 IS DISTINCT FROM p_attestation_version
       OR v_payload ->> 1 IS DISTINCT FROM p_collector_key_id
       OR v_payload ->> 2 IS DISTINCT FROM p_run_id::text
       OR v_payload ->> 3 IS DISTINCT FROM p_fencing_token::text
       OR v_payload ->> 4 IS DISTINCT FROM p_row_id::text
       OR v_payload ->> 5 IS DISTINCT FROM p_youtube_video_id
       OR (v_payload ->> 6)::timestamptz IS DISTINCT FROM p_published_at
       OR v_payload ->> 7 IS DISTINCT FROM p_views::text
       OR (v_payload ->> 8)::timestamptz IS DISTINCT FROM p_sync_captured_at
       OR v_payload ->> 9 IS DISTINCT FROM p_collector_response_sha256
       OR v_payload ->> 10 IS DISTINCT FROM p_collector_requested_ids_sha256
       OR v_payload ->> 11 IS DISTINCT FROM p_collector_build THEN
        RETURN false;
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM pr_d_internal.e12_collector_key_registry
         WHERE key_id = p_collector_key_id
           AND algorithm = p_attestation_algorithm
           AND public_key_spki_base64 = p_collector_public_key_spki_base64
           AND status = 'active'
           AND revoked_at IS NULL
    ) INTO v_key_registered;
    IF NOT v_key_registered THEN RETURN false; END IF;

    -- Lock the lease row through the CAS transaction. A takeover cannot race
    -- between this authorization check and the protected write.
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
           elapsed_seconds_e12 = EXTRACT(EPOCH FROM (p_sync_captured_at - p_published_at)),
           e12_capture_run_id = p_run_id,
           e12_fencing_token = p_fencing_token,
           collector_attestation_version = p_attestation_version,
           collector_attestation_algorithm = p_attestation_algorithm,
           collector_key_id = p_collector_key_id,
           collector_public_key_spki_base64 = p_collector_public_key_spki_base64,
           collector_payload_canonical = p_collector_payload_canonical,
           collector_payload_sha256 = p_collector_payload_sha256,
           collector_signature = p_collector_signature,
           collector_response_sha256 = p_collector_response_sha256,
           collector_requested_ids_sha256 = p_collector_requested_ids_sha256,
           collector_build = p_collector_build
     WHERE id = p_row_id AND youtube_video_id = p_youtube_video_id
       AND views_primeras_3h IS NULL AND published_at IS NULL
       AND sync_captured_at IS NULL AND elapsed_seconds_e12 IS NULL
       AND hs_al_publicar_al_sync IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$capture$;

ALTER FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) OWNER TO pr_d_capture_owner;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

CREATE FUNCTION public.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $wrapper$
    SELECT pr_d_internal.pr_d_capture_views_once(
        p_row_id, p_youtube_video_id, p_views, p_published_at,
        p_sync_captured_at, p_run_id, p_fencing_token,
        p_attestation_version, p_attestation_algorithm, p_collector_key_id,
        p_collector_public_key_spki_base64, p_collector_payload_canonical,
        p_collector_payload_sha256, p_collector_signature,
        p_collector_response_sha256, p_collector_requested_ids_sha256,
        p_collector_build
    );
$wrapper$;

REVOKE ALL ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

            AND collector_build ~ '^[A-Za-z0-9._+/-]{1,96}

CREATE OR REPLACE FUNCTION public.pr_d_guard_capture_fields()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            NEW.views_primeras_3h IS NOT NULL
            OR NEW.published_at IS NOT NULL
            OR NEW.sync_captured_at IS NOT NULL
            OR NEW.elapsed_seconds_e12 IS NOT NULL
            OR NEW.hs_al_publicar_al_sync IS NOT NULL
            OR NEW.e12_capture_run_id IS NOT NULL
            OR NEW.e12_fencing_token IS NOT NULL
            OR NEW.collector_attestation_version IS NOT NULL
            OR NEW.collector_attestation_algorithm IS NOT NULL
            OR NEW.collector_key_id IS NOT NULL
            OR NEW.collector_public_key_spki_base64 IS NOT NULL
            OR NEW.collector_payload_canonical IS NOT NULL
            OR NEW.collector_payload_sha256 IS NOT NULL
            OR NEW.collector_signature IS NOT NULL
            OR NEW.collector_response_sha256 IS NOT NULL
            OR NEW.collector_requested_ids_sha256 IS NOT NULL
            OR NEW.collector_build IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_write_denied: populated capture/attestation fields require controlled CAS'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            OLD.views_primeras_3h IS NOT NULL
            OR OLD.published_at IS NOT NULL
            OR OLD.sync_captured_at IS NOT NULL
            OR OLD.elapsed_seconds_e12 IS NOT NULL
            OR OLD.hs_al_publicar_al_sync IS NOT NULL
            OR OLD.e12_capture_run_id IS NOT NULL
            OR OLD.e12_fencing_token IS NOT NULL
            OR OLD.collector_signature IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_delete_denied: captured outcome rows are immutable'
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;

    IF current_user <> 'pr_d_capture_owner' AND (
        NEW.views_primeras_3h IS DISTINCT FROM OLD.views_primeras_3h
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
        OR NEW.sync_captured_at IS DISTINCT FROM OLD.sync_captured_at
        OR NEW.elapsed_seconds_e12 IS DISTINCT FROM OLD.elapsed_seconds_e12
        OR NEW.hs_al_publicar_al_sync IS DISTINCT FROM OLD.hs_al_publicar_al_sync
        OR NEW.e12_capture_run_id IS DISTINCT FROM OLD.e12_capture_run_id
        OR NEW.e12_fencing_token IS DISTINCT FROM OLD.e12_fencing_token
        OR NEW.collector_attestation_version IS DISTINCT FROM OLD.collector_attestation_version
        OR NEW.collector_attestation_algorithm IS DISTINCT FROM OLD.collector_attestation_algorithm
        OR NEW.collector_key_id IS DISTINCT FROM OLD.collector_key_id
        OR NEW.collector_public_key_spki_base64 IS DISTINCT FROM OLD.collector_public_key_spki_base64
        OR NEW.collector_payload_canonical IS DISTINCT FROM OLD.collector_payload_canonical
        OR NEW.collector_payload_sha256 IS DISTINCT FROM OLD.collector_payload_sha256
        OR NEW.collector_signature IS DISTINCT FROM OLD.collector_signature
        OR NEW.collector_response_sha256 IS DISTINCT FROM OLD.collector_response_sha256
        OR NEW.collector_requested_ids_sha256 IS DISTINCT FROM OLD.collector_requested_ids_sha256
        OR NEW.collector_build IS DISTINCT FROM OLD.collector_build
        OR (
            OLD.views_primeras_3h IS NOT NULL
            AND (
                NEW.youtube_video_id IS DISTINCT FROM OLD.youtube_video_id
                OR NEW.id IS DISTINCT FROM OLD.id
            )
        )
    ) THEN
        RAISE EXCEPTION 'prd_capture_write_denied: capture, attestation and captured identity are immutable'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$guard$;

REVOKE ALL ON FUNCTION public.pr_d_guard_capture_fields()
    FROM PUBLIC, anon, authenticated, service_role;

DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);
DROP FUNCTION IF EXISTS pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);

CREATE FUNCTION pr_d_internal.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $capture$
DECLARE
    v_claims jsonb;
    v_updated integer;
    v_lease_live boolean;
    v_key_registered boolean;
    v_payload jsonb;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_capture_role_denied: service_role JWT claim required'
            USING ERRCODE = '42501';
    END IF;

    IF p_views IS NULL OR p_views < 0 OR p_views > 18446744073709551615
       OR p_views <> trunc(p_views) OR p_published_at IS NULL OR p_sync_captured_at IS NULL
       OR p_run_id IS NULL OR p_fencing_token IS NULL OR p_fencing_token <= 0
       OR p_attestation_version IS DISTINCT FROM 'e12-observation-attestation/v1'
       OR p_attestation_algorithm IS DISTINCT FROM 'Ed25519'
       OR p_collector_key_id IS NULL
       OR p_collector_public_key_spki_base64 !~ '^[A-Za-z0-9+/]{59}=$'
       OR length(decode(p_collector_public_key_spki_base64, 'base64')) <> 44
       OR p_collector_payload_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_signature !~ '^[A-Za-z0-9+/]{86}==$'
       OR length(decode(p_collector_signature, 'base64')) <> 64
       OR p_collector_response_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_requested_ids_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_build !~ '^[A-Za-z0-9._+/-]{1,96}$'
       OR p_collector_payload_canonical IS NULL
       OR length(p_collector_payload_canonical) > 4096
       OR p_sync_captured_at < p_published_at + interval '2 hours 55 minutes'
       OR p_sync_captured_at > p_published_at + interval '3 hours 5 minutes' THEN
        RETURN false;
    END IF;

    BEGIN
        v_payload := p_collector_payload_canonical::jsonb;
    EXCEPTION WHEN others THEN
        RETURN false;
    END;

    IF jsonb_typeof(v_payload) <> 'array'
       OR jsonb_array_length(v_payload) <> 12
       OR v_payload ->> 0 IS DISTINCT FROM p_attestation_version
       OR v_payload ->> 1 IS DISTINCT FROM p_collector_key_id
       OR v_payload ->> 2 IS DISTINCT FROM p_run_id::text
       OR v_payload ->> 3 IS DISTINCT FROM p_fencing_token::text
       OR v_payload ->> 4 IS DISTINCT FROM p_row_id::text
       OR v_payload ->> 5 IS DISTINCT FROM p_youtube_video_id
       OR (v_payload ->> 6)::timestamptz IS DISTINCT FROM p_published_at
       OR v_payload ->> 7 IS DISTINCT FROM p_views::text
       OR (v_payload ->> 8)::timestamptz IS DISTINCT FROM p_sync_captured_at
       OR v_payload ->> 9 IS DISTINCT FROM p_collector_response_sha256
       OR v_payload ->> 10 IS DISTINCT FROM p_collector_requested_ids_sha256
       OR v_payload ->> 11 IS DISTINCT FROM p_collector_build THEN
        RETURN false;
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM pr_d_internal.e12_collector_key_registry
         WHERE key_id = p_collector_key_id
           AND algorithm = p_attestation_algorithm
           AND public_key_spki_base64 = p_collector_public_key_spki_base64
           AND status = 'active'
           AND revoked_at IS NULL
    ) INTO v_key_registered;
    IF NOT v_key_registered THEN RETURN false; END IF;

    -- Lock the lease row through the CAS transaction. A takeover cannot race
    -- between this authorization check and the protected write.
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
           elapsed_seconds_e12 = EXTRACT(EPOCH FROM (p_sync_captured_at - p_published_at)),
           e12_capture_run_id = p_run_id,
           e12_fencing_token = p_fencing_token,
           collector_attestation_version = p_attestation_version,
           collector_attestation_algorithm = p_attestation_algorithm,
           collector_key_id = p_collector_key_id,
           collector_public_key_spki_base64 = p_collector_public_key_spki_base64,
           collector_payload_canonical = p_collector_payload_canonical,
           collector_payload_sha256 = p_collector_payload_sha256,
           collector_signature = p_collector_signature,
           collector_response_sha256 = p_collector_response_sha256,
           collector_requested_ids_sha256 = p_collector_requested_ids_sha256,
           collector_build = p_collector_build
     WHERE id = p_row_id AND youtube_video_id = p_youtube_video_id
       AND views_primeras_3h IS NULL AND published_at IS NULL
       AND sync_captured_at IS NULL AND elapsed_seconds_e12 IS NULL
       AND hs_al_publicar_al_sync IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$capture$;

ALTER FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) OWNER TO pr_d_capture_owner;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

CREATE FUNCTION public.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $wrapper$
    SELECT pr_d_internal.pr_d_capture_views_once(
        p_row_id, p_youtube_video_id, p_views, p_published_at,
        p_sync_captured_at, p_run_id, p_fencing_token,
        p_attestation_version, p_attestation_algorithm, p_collector_key_id,
        p_collector_public_key_spki_base64, p_collector_payload_canonical,
        p_collector_payload_sha256, p_collector_signature,
        p_collector_response_sha256, p_collector_requested_ids_sha256,
        p_collector_build
    );
$wrapper$;

REVOKE ALL ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

        )
    );

CREATE OR REPLACE FUNCTION public.pr_d_guard_capture_fields()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            NEW.views_primeras_3h IS NOT NULL
            OR NEW.published_at IS NOT NULL
            OR NEW.sync_captured_at IS NOT NULL
            OR NEW.elapsed_seconds_e12 IS NOT NULL
            OR NEW.hs_al_publicar_al_sync IS NOT NULL
            OR NEW.e12_capture_run_id IS NOT NULL
            OR NEW.e12_fencing_token IS NOT NULL
            OR NEW.collector_attestation_version IS NOT NULL
            OR NEW.collector_attestation_algorithm IS NOT NULL
            OR NEW.collector_key_id IS NOT NULL
            OR NEW.collector_public_key_spki_base64 IS NOT NULL
            OR NEW.collector_payload_canonical IS NOT NULL
            OR NEW.collector_payload_sha256 IS NOT NULL
            OR NEW.collector_signature IS NOT NULL
            OR NEW.collector_response_sha256 IS NOT NULL
            OR NEW.collector_requested_ids_sha256 IS NOT NULL
            OR NEW.collector_build IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_write_denied: populated capture/attestation fields require controlled CAS'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF current_user <> 'pr_d_capture_owner' AND (
            OLD.views_primeras_3h IS NOT NULL
            OR OLD.published_at IS NOT NULL
            OR OLD.sync_captured_at IS NOT NULL
            OR OLD.elapsed_seconds_e12 IS NOT NULL
            OR OLD.hs_al_publicar_al_sync IS NOT NULL
            OR OLD.e12_capture_run_id IS NOT NULL
            OR OLD.e12_fencing_token IS NOT NULL
            OR OLD.collector_signature IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'prd_capture_delete_denied: captured outcome rows are immutable'
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;

    IF current_user <> 'pr_d_capture_owner' AND (
        NEW.views_primeras_3h IS DISTINCT FROM OLD.views_primeras_3h
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
        OR NEW.sync_captured_at IS DISTINCT FROM OLD.sync_captured_at
        OR NEW.elapsed_seconds_e12 IS DISTINCT FROM OLD.elapsed_seconds_e12
        OR NEW.hs_al_publicar_al_sync IS DISTINCT FROM OLD.hs_al_publicar_al_sync
        OR NEW.e12_capture_run_id IS DISTINCT FROM OLD.e12_capture_run_id
        OR NEW.e12_fencing_token IS DISTINCT FROM OLD.e12_fencing_token
        OR NEW.collector_attestation_version IS DISTINCT FROM OLD.collector_attestation_version
        OR NEW.collector_attestation_algorithm IS DISTINCT FROM OLD.collector_attestation_algorithm
        OR NEW.collector_key_id IS DISTINCT FROM OLD.collector_key_id
        OR NEW.collector_public_key_spki_base64 IS DISTINCT FROM OLD.collector_public_key_spki_base64
        OR NEW.collector_payload_canonical IS DISTINCT FROM OLD.collector_payload_canonical
        OR NEW.collector_payload_sha256 IS DISTINCT FROM OLD.collector_payload_sha256
        OR NEW.collector_signature IS DISTINCT FROM OLD.collector_signature
        OR NEW.collector_response_sha256 IS DISTINCT FROM OLD.collector_response_sha256
        OR NEW.collector_requested_ids_sha256 IS DISTINCT FROM OLD.collector_requested_ids_sha256
        OR NEW.collector_build IS DISTINCT FROM OLD.collector_build
        OR (
            OLD.views_primeras_3h IS NOT NULL
            AND (
                NEW.youtube_video_id IS DISTINCT FROM OLD.youtube_video_id
                OR NEW.id IS DISTINCT FROM OLD.id
            )
        )
    ) THEN
        RAISE EXCEPTION 'prd_capture_write_denied: capture, attestation and captured identity are immutable'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$guard$;

REVOKE ALL ON FUNCTION public.pr_d_guard_capture_fields()
    FROM PUBLIC, anon, authenticated, service_role;

DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);
DROP FUNCTION IF EXISTS pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint
);

CREATE FUNCTION pr_d_internal.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $capture$
DECLARE
    v_claims jsonb;
    v_updated integer;
    v_lease_live boolean;
    v_key_registered boolean;
    v_payload jsonb;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_capture_role_denied: service_role JWT claim required'
            USING ERRCODE = '42501';
    END IF;

    IF p_views IS NULL OR p_views < 0 OR p_views > 18446744073709551615
       OR p_views <> trunc(p_views) OR p_published_at IS NULL OR p_sync_captured_at IS NULL
       OR p_run_id IS NULL OR p_fencing_token IS NULL OR p_fencing_token <= 0
       OR p_attestation_version IS DISTINCT FROM 'e12-observation-attestation/v1'
       OR p_attestation_algorithm IS DISTINCT FROM 'Ed25519'
       OR p_collector_key_id IS NULL
       OR p_collector_public_key_spki_base64 !~ '^[A-Za-z0-9+/]{59}=$'
       OR length(decode(p_collector_public_key_spki_base64, 'base64')) <> 44
       OR p_collector_payload_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_signature !~ '^[A-Za-z0-9+/]{86}==$'
       OR length(decode(p_collector_signature, 'base64')) <> 64
       OR p_collector_response_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_requested_ids_sha256 !~ '^[a-f0-9]{64}$'
       OR p_collector_build !~ '^[A-Za-z0-9._+/-]{1,96}$'
       OR p_collector_payload_canonical IS NULL
       OR length(p_collector_payload_canonical) > 4096
       OR p_sync_captured_at < p_published_at + interval '2 hours 55 minutes'
       OR p_sync_captured_at > p_published_at + interval '3 hours 5 minutes' THEN
        RETURN false;
    END IF;

    BEGIN
        v_payload := p_collector_payload_canonical::jsonb;
    EXCEPTION WHEN others THEN
        RETURN false;
    END;

    IF jsonb_typeof(v_payload) <> 'array'
       OR jsonb_array_length(v_payload) <> 12
       OR v_payload ->> 0 IS DISTINCT FROM p_attestation_version
       OR v_payload ->> 1 IS DISTINCT FROM p_collector_key_id
       OR v_payload ->> 2 IS DISTINCT FROM p_run_id::text
       OR v_payload ->> 3 IS DISTINCT FROM p_fencing_token::text
       OR v_payload ->> 4 IS DISTINCT FROM p_row_id::text
       OR v_payload ->> 5 IS DISTINCT FROM p_youtube_video_id
       OR (v_payload ->> 6)::timestamptz IS DISTINCT FROM p_published_at
       OR v_payload ->> 7 IS DISTINCT FROM p_views::text
       OR (v_payload ->> 8)::timestamptz IS DISTINCT FROM p_sync_captured_at
       OR v_payload ->> 9 IS DISTINCT FROM p_collector_response_sha256
       OR v_payload ->> 10 IS DISTINCT FROM p_collector_requested_ids_sha256
       OR v_payload ->> 11 IS DISTINCT FROM p_collector_build THEN
        RETURN false;
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM pr_d_internal.e12_collector_key_registry
         WHERE key_id = p_collector_key_id
           AND algorithm = p_attestation_algorithm
           AND public_key_spki_base64 = p_collector_public_key_spki_base64
           AND status = 'active'
           AND revoked_at IS NULL
    ) INTO v_key_registered;
    IF NOT v_key_registered THEN RETURN false; END IF;

    -- Lock the lease row through the CAS transaction. A takeover cannot race
    -- between this authorization check and the protected write.
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
           elapsed_seconds_e12 = EXTRACT(EPOCH FROM (p_sync_captured_at - p_published_at)),
           e12_capture_run_id = p_run_id,
           e12_fencing_token = p_fencing_token,
           collector_attestation_version = p_attestation_version,
           collector_attestation_algorithm = p_attestation_algorithm,
           collector_key_id = p_collector_key_id,
           collector_public_key_spki_base64 = p_collector_public_key_spki_base64,
           collector_payload_canonical = p_collector_payload_canonical,
           collector_payload_sha256 = p_collector_payload_sha256,
           collector_signature = p_collector_signature,
           collector_response_sha256 = p_collector_response_sha256,
           collector_requested_ids_sha256 = p_collector_requested_ids_sha256,
           collector_build = p_collector_build
     WHERE id = p_row_id AND youtube_video_id = p_youtube_video_id
       AND views_primeras_3h IS NULL AND published_at IS NULL
       AND sync_captured_at IS NULL AND elapsed_seconds_e12 IS NULL
       AND hs_al_publicar_al_sync IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$capture$;

ALTER FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) OWNER TO pr_d_capture_owner;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;

CREATE FUNCTION public.pr_d_capture_views_once(
    p_row_id bigint,
    p_youtube_video_id text,
    p_views numeric,
    p_published_at timestamptz,
    p_sync_captured_at timestamptz,
    p_run_id uuid,
    p_fencing_token bigint,
    p_attestation_version text,
    p_attestation_algorithm text,
    p_collector_key_id text,
    p_collector_public_key_spki_base64 text,
    p_collector_payload_canonical text,
    p_collector_payload_sha256 text,
    p_collector_signature text,
    p_collector_response_sha256 text,
    p_collector_requested_ids_sha256 text,
    p_collector_build text
)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $wrapper$
    SELECT pr_d_internal.pr_d_capture_views_once(
        p_row_id, p_youtube_video_id, p_views, p_published_at,
        p_sync_captured_at, p_run_id, p_fencing_token,
        p_attestation_version, p_attestation_algorithm, p_collector_key_id,
        p_collector_public_key_spki_base64, p_collector_payload_canonical,
        p_collector_payload_sha256, p_collector_signature,
        p_collector_response_sha256, p_collector_requested_ids_sha256,
        p_collector_build
    );
$wrapper$;

REVOKE ALL ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, numeric, timestamptz, timestamptz, uuid, bigint,
    text, text, text, text, text, text, text, text, text, text
) TO service_role;
