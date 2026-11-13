-- SANDBOX CANDIDATE ONLY.
-- Depends on the E12 lease/fencing and collector-attestation migrations.
-- Batch transport only: each observation is still authorized by the existing
-- single-row CAS, including HMAC, canonical payload, key status and fencing.
-- A false CAS result is a per-item first-write-wins conflict. SQL exceptions
-- abort the RPC transaction and roll back every write in this batch.

DO $preflight$
BEGIN
    IF to_regprocedure('pr_d_internal.pr_d_capture_views_once(bigint,text,numeric,timestamp with time zone,timestamp with time zone,uuid,bigint,text,text,text,text,text,text,text,text,text,text,text)') IS NULL THEN
        RAISE EXCEPTION 'prd_e12_batch_preflight_failed: attested single-row CAS missing';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pr_d_capture_owner') THEN
        RAISE EXCEPTION 'prd_e12_batch_preflight_failed: capture owner role missing';
    END IF;
END;
$preflight$;

CREATE FUNCTION pr_d_internal.pr_d_capture_views_batch(p_items jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pr_d_internal
SET statement_timeout = '10s'
SET lock_timeout = '5s'
AS $batch$
DECLARE
    v_claims jsonb;
    v_item jsonb;
    v_row_id bigint;
    v_captured boolean;
    v_results jsonb := '[]'::jsonb;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'prd_capture_role_denied: service_role JWT claim required'
            USING ERRCODE = '42501';
    END IF;

    IF jsonb_typeof(p_items) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'prd_e12_batch_invalid_size: expected a JSON array'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_array_length(p_items) < 1 OR jsonb_array_length(p_items) > 50 THEN
        RAISE EXCEPTION 'prd_e12_batch_invalid_size: expected 1..50 items'
            USING ERRCODE = '22023';
    END IF;

    FOR v_item IN SELECT value FROM jsonb_array_elements(p_items)
    LOOP
        IF jsonb_typeof(v_item) IS DISTINCT FROM 'object'
           OR NOT (v_item ?& ARRAY[
               'p_row_id', 'p_youtube_video_id', 'p_views', 'p_published_at',
               'p_sync_captured_at', 'p_run_id', 'p_fencing_token',
               'p_attestation_version', 'p_attestation_algorithm',
               'p_collector_key_id', 'p_collector_public_key_spki_base64',
               'p_collector_payload_canonical', 'p_collector_payload_sha256',
               'p_collector_signature', 'p_collector_hmac_signature',
               'p_collector_response_sha256', 'p_collector_requested_ids_sha256',
               'p_collector_build'
           ]) THEN
            RAISE EXCEPTION 'prd_e12_batch_invalid_item: required fields missing'
                USING ERRCODE = '22023';
        END IF;

        -- Explicit casts preserve decimal uint64 counts and reject malformed
        -- identities/timestamps. Any cast error aborts and rolls back the RPC.
        v_row_id := (v_item ->> 'p_row_id')::bigint;
        v_captured := pr_d_internal.pr_d_capture_views_once(
            v_row_id,
            v_item ->> 'p_youtube_video_id',
            (v_item ->> 'p_views')::numeric,
            (v_item ->> 'p_published_at')::timestamptz,
            (v_item ->> 'p_sync_captured_at')::timestamptz,
            (v_item ->> 'p_run_id')::uuid,
            (v_item ->> 'p_fencing_token')::bigint,
            v_item ->> 'p_attestation_version',
            v_item ->> 'p_attestation_algorithm',
            v_item ->> 'p_collector_key_id',
            v_item ->> 'p_collector_public_key_spki_base64',
            v_item ->> 'p_collector_payload_canonical',
            v_item ->> 'p_collector_payload_sha256',
            v_item ->> 'p_collector_signature',
            v_item ->> 'p_collector_hmac_signature',
            v_item ->> 'p_collector_response_sha256',
            v_item ->> 'p_collector_requested_ids_sha256',
            v_item ->> 'p_collector_build'
        );

        v_results := v_results || jsonb_build_array(
            jsonb_build_object('row_id', v_row_id::text, 'captured', v_captured)
        );
    END LOOP;

    RETURN v_results;
END;
$batch$;

ALTER FUNCTION pr_d_internal.pr_d_capture_views_batch(jsonb)
    OWNER TO pr_d_capture_owner;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_capture_views_batch(jsonb)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_capture_views_batch(jsonb)
    TO service_role;

CREATE FUNCTION public.pr_d_capture_views_batch(p_items jsonb)
RETURNS jsonb
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog
AS $wrapper$
    SELECT pr_d_internal.pr_d_capture_views_batch(p_items);
$wrapper$;

REVOKE ALL ON FUNCTION public.pr_d_capture_views_batch(jsonb)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_batch(jsonb)
    TO service_role;
