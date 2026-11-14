-- SANDBOX CANDIDATE ONLY. Never apply to a live project from this branch.
-- One successful E12 worker invocation per signed cron minute. This makes
-- replay of a visible pg_net request signature idempotent before any YouTube
-- quota is consumed.
DO $preflight$
DECLARE
    v_owner oid;
BEGIN
    SELECT oid INTO v_owner FROM pg_roles WHERE rolname = 'pr_d_capture_owner';
    IF v_owner IS NULL THEN
        RAISE EXCEPTION 'prd_e12_slot_preflight_failed: pr_d_capture_owner missing';
    END IF;
    IF (SELECT nspowner FROM pg_namespace WHERE nspname = 'pr_d_internal') <> v_owner THEN
        RAISE EXCEPTION 'prd_e12_slot_preflight_failed: pr_d_internal owner mismatch';
    END IF;
END;
$preflight$;

CREATE TABLE IF NOT EXISTS pr_d_internal.e12_worker_run_slot (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    last_claimed_minute timestamptz NOT NULL
);
ALTER TABLE pr_d_internal.e12_worker_run_slot OWNER TO pr_d_capture_owner;
SET ROLE pr_d_capture_owner;
REVOKE ALL ON TABLE pr_d_internal.e12_worker_run_slot
    FROM PUBLIC, anon, authenticated, service_role;

COMMENT ON TABLE pr_d_internal.e12_worker_run_slot IS
    'Singleton idempotency slot: at most one E12 worker execution for each signed UTC cron minute.';

CREATE OR REPLACE FUNCTION pr_d_internal.pr_d_claim_e12_worker_slot(
    p_minute_bucket timestamptz
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pr_d_internal
AS $claim$
DECLARE
    v_claims jsonb;
    v_now_minute timestamptz;
    v_claimed boolean;
BEGIN
    v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
    IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION
            'prd_e12_slot_role_denied: service_role JWT claim required'
            USING ERRCODE = '42501';
    END IF;

    IF p_minute_bucket IS NULL
       OR p_minute_bucket IS DISTINCT FROM date_trunc('minute', p_minute_bucket) THEN
        RETURN false;
    END IF;

    v_now_minute := date_trunc('minute', clock_timestamp());
    -- Permit delayed delivery of a queued request for up to two minutes,
    -- but never allow a future bucket or an old replay to claim a slot.
    IF p_minute_bucket < v_now_minute - interval '2 minutes'
       OR p_minute_bucket > v_now_minute THEN
        RETURN false;
    END IF;

    INSERT INTO pr_d_internal.e12_worker_run_slot AS slot (
        singleton,
        last_claimed_minute
    )
    VALUES (true, p_minute_bucket)
    ON CONFLICT (singleton) DO UPDATE
       SET last_claimed_minute = EXCLUDED.last_claimed_minute
     WHERE slot.last_claimed_minute < EXCLUDED.last_claimed_minute
    RETURNING true INTO v_claimed;

    RETURN COALESCE(v_claimed, false);
END;
$claim$;

ALTER FUNCTION pr_d_internal.pr_d_claim_e12_worker_slot(timestamptz)
    OWNER TO pr_d_capture_owner;
REVOKE ALL ON FUNCTION pr_d_internal.pr_d_claim_e12_worker_slot(timestamptz)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION pr_d_internal.pr_d_claim_e12_worker_slot(timestamptz)
    TO service_role;
RESET ROLE;

DROP FUNCTION IF EXISTS public.pr_d_claim_e12_worker_slot(timestamptz);
CREATE OR REPLACE FUNCTION public.pr_d_claim_e12_worker_slot(
    p_minute_bucket timestamptz
)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $wrapper$
    SELECT pr_d_internal.pr_d_claim_e12_worker_slot(p_minute_bucket);
$wrapper$;

REVOKE ALL ON FUNCTION public.pr_d_claim_e12_worker_slot(timestamptz)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_claim_e12_worker_slot(timestamptz)
    TO service_role;
