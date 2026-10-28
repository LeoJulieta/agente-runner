-- PR D v2 / Rule 15.3
-- One PostgreSQL function call commits baseline (if absent) and evidence together.
-- This migration is applied only through the normal reviewed migration process.
-- It does not run against any database from CI.

CREATE UNIQUE INDEX IF NOT EXISTS uq_lab_results_prd_run
    ON public.lab_results (lab_id, (params ->> 'run_id'))
    WHERE params ->> 'record_type' = 'evidence'
      AND params ? 'run_id';

CREATE OR REPLACE FUNCTION public.rpc_insert_baseline_and_evidence(
    p_lab_id text,
    p_gen integer,
    p_baseline_value jsonb,
    p_baseline_type text,
    p_evidence_params jsonb,
    p_evidence_metrics jsonb,
    p_status text,
    p_reproducible boolean,
    p_run_id text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_existing jsonb;
    v_baseline_created boolean := false;
    v_evidence_id bigint;
    v_evidence_count integer;
    v_params jsonb;
BEGIN
    IF p_lab_id IS NULL OR btrim(p_lab_id) = '' OR
       p_run_id IS NULL OR btrim(p_run_id) = '' OR
       p_evidence_params IS NULL OR p_evidence_metrics IS NULL OR
       p_status NOT IN ('PROMETE', 'VERIFICADO') THEN
        RAISE EXCEPTION 'prd_atomic_invalid_arguments'
            USING ERRCODE = '22023';
    END IF;

    -- Serialize baseline selection and evidence numbering per hypothesis/generation.
    PERFORM pg_advisory_xact_lock(hashtextextended(p_lab_id || ':' || p_gen::text, 0));

    -- Idempotent retry: return the previously committed evidence record.
    SELECT jsonb_build_object(
        'id', id,
        'evidence_count', evidence_count,
        'baseline_created', false,
        'idempotent_replay', true
    )
    INTO v_existing
    FROM public.lab_results
    WHERE lab_id = p_lab_id
      AND params ->> 'record_type' = 'evidence'
      AND params ->> 'run_id' = p_run_id
    ORDER BY id
    LIMIT 1;

    IF v_existing IS NOT NULL THEN
        RETURN v_existing;
    END IF;

    -- Only freeze a baseline if one does not already exist.
    PERFORM 1
    FROM public.lab_results
    WHERE lab_id = p_lab_id
      AND gen = p_gen
      AND status = 'PROMETE'
      AND (
        params ->> 'record_type' = 'baseline'
        OR params ->> 'baseline_frozen' = 'true'
        OR (params ? 'baseline' AND jsonb_typeof(params -> 'baseline') <> 'object')
      )
    ORDER BY id
    LIMIT 1;

    IF NOT FOUND THEN
        IF p_baseline_value IS NULL THEN
            RAISE EXCEPTION 'prd_atomic_baseline_required'
                USING ERRCODE = '23502';
        END IF;

        INSERT INTO public.lab_results (
            lab_id, gen, params, metrics, status, evidence_count,
            reproducible, last_test
        ) VALUES (
            p_lab_id, p_gen,
            jsonb_build_object(
                'baseline', p_baseline_value,
                'baseline_type', COALESCE(p_baseline_type, 'unknown'),
                'baseline_frozen', true,
                'record_type', 'baseline'
            ),
            '{}'::jsonb, 'PROMETE', 0, false, now()
        );
        v_baseline_created := true;
    END IF;

    SELECT COALESCE(MAX(evidence_count), 0) + 1
    INTO v_evidence_count
    FROM public.lab_results
    WHERE lab_id = p_lab_id;

    v_params := p_evidence_params || jsonb_build_object(
        'record_type', 'evidence',
        'run_id', p_run_id
    );

    INSERT INTO public.lab_results (
        lab_id, gen, params, metrics, status, evidence_count,
        reproducible, last_test
    ) VALUES (
        p_lab_id, p_gen, v_params, p_evidence_metrics, p_status,
        v_evidence_count, COALESCE(p_reproducible, false), now()
    )
    RETURNING id INTO v_evidence_id;

    RETURN jsonb_build_object(
        'id', v_evidence_id,
        'evidence_count', v_evidence_count,
        'baseline_created', v_baseline_created,
        'idempotent_replay', false
    );
END;
$$;

COMMENT ON FUNCTION public.rpc_insert_baseline_and_evidence(
    text, integer, jsonb, text, jsonb, jsonb, text, boolean, text
) IS 'PR D v2: atomically freeze baseline if absent and persist one idempotent evidence record.';
