-- SANDBOX CANDIDATE ONLY. Never apply to a live project from this branch.
-- Make the atomic baseline+evidence RPC the mandatory INSERT path for lab_results.
-- Existing UPDATE/DELETE protection remains unchanged; no rows are rewritten.

DO $writer_role$
DECLARE
    v_role_oid oid;
BEGIN
    SELECT oid INTO v_role_oid FROM pg_roles WHERE rolname = 'pr_d_lab_results_writer';
    IF v_role_oid IS NULL THEN
        EXECUTE 'CREATE ROLE pr_d_lab_results_writer NOLOGIN NOINHERIT BYPASSRLS';
    ELSE
        IF EXISTS (
            SELECT 1 FROM pg_roles
            WHERE oid = v_role_oid
              AND (rolcanlogin OR rolinherit OR NOT rolbypassrls)
        ) OR EXISTS (
            SELECT 1 FROM pg_auth_members
            WHERE roleid = v_role_oid OR member = v_role_oid
        ) THEN
            RAISE EXCEPTION
                'prd_lab_results_writer_role_misconfigured: dedicated role must be NOLOGIN, NOINHERIT, BYPASSRLS, and have no memberships';
        END IF;
    END IF;
END;
$writer_role$;

GRANT USAGE ON SCHEMA public TO pr_d_lab_results_writer;
GRANT SELECT, INSERT ON public.lab_results TO pr_d_lab_results_writer;
GRANT USAGE, SELECT ON SEQUENCE public.lab_results_id_seq TO pr_d_lab_results_writer;
GRANT CREATE ON SCHEMA public TO pr_d_lab_results_writer;

-- Move the existing implementation behind the new security-definer boundary.
-- The conditional rename makes replay safe while preserving the public RPC name.
DO $rename_impl$
BEGIN
    IF to_regprocedure(
        'public.pr_d_rpc_insert_baseline_and_evidence_impl(text,integer,jsonb,text,jsonb,jsonb,text,boolean,text)'
    ) IS NULL THEN
        IF to_regprocedure(
            'public.rpc_insert_baseline_and_evidence(text,integer,jsonb,text,jsonb,jsonb,text,boolean,text)'
        ) IS NULL THEN
            RAISE EXCEPTION 'prd_atomic_rpc_missing_before_write_boundary';
        END IF;
        EXECUTE 'ALTER FUNCTION public.rpc_insert_baseline_and_evidence(text,integer,jsonb,text,jsonb,jsonb,text,boolean,text) RENAME TO pr_d_rpc_insert_baseline_and_evidence_impl';
    END IF;
END;
$rename_impl$;

REVOKE ALL ON FUNCTION public.pr_d_rpc_insert_baseline_and_evidence_impl(
    text, integer, jsonb, text, jsonb, jsonb, text, boolean, text
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.pr_d_rpc_insert_baseline_and_evidence_impl(
    text, integer, jsonb, text, jsonb, jsonb, text, boolean, text
) TO pr_d_lab_results_writer;

-- A direct service_role INSERT cannot impersonate the dedicated RPC owner.
CREATE OR REPLACE FUNCTION public.pr_d_guard_lab_results_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard$
BEGIN
    IF current_user <> 'pr_d_lab_results_writer' THEN
        RAISE EXCEPTION 'prd_lab_results_insert_requires_atomic_rpc'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$guard$;

DROP TRIGGER IF EXISTS a_pr_d_lab_results_atomic_insert_guard ON public.lab_results;
CREATE TRIGGER a_pr_d_lab_results_atomic_insert_guard
    BEFORE INSERT ON public.lab_results
    FOR EACH ROW EXECUTE FUNCTION public.pr_d_guard_lab_results_insert();

-- Keep the same public PostgREST RPC name and arguments. The wrapper enters
-- the isolated writer role, then calls the original invoker implementation.
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
)
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $wrapper$
    SELECT public.pr_d_rpc_insert_baseline_and_evidence_impl(
        p_lab_id, p_gen, p_baseline_value, p_baseline_type,
        p_evidence_params, p_evidence_metrics, p_status,
        p_reproducible, p_run_id
    );
$wrapper$;

ALTER FUNCTION public.rpc_insert_baseline_and_evidence(
    text, integer, jsonb, text, jsonb, jsonb, text, boolean, text
) OWNER TO pr_d_lab_results_writer;
REVOKE CREATE ON SCHEMA public FROM pr_d_lab_results_writer;

REVOKE ALL ON FUNCTION public.rpc_insert_baseline_and_evidence(
    text, integer, jsonb, text, jsonb, jsonb, text, boolean, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_insert_baseline_and_evidence(
    text, integer, jsonb, text, jsonb, jsonb, text, boolean, text
) TO service_role;
