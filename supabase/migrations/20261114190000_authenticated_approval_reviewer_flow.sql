-- Candidate only: not applied to production.
-- Replace anonymous approval access with an authenticated reviewer allowlist.

CREATE TABLE IF NOT EXISTS public.approval_reviewers (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

ALTER TABLE public.approval_reviewers ENABLE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE public.approval_reviewers FROM anon, authenticated;
GRANT SELECT ON TABLE public.approval_reviewers TO authenticated;

DROP POLICY IF EXISTS approval_reviewers_self_read
ON public.approval_reviewers;

CREATE POLICY approval_reviewers_self_read
ON public.approval_reviewers
FOR SELECT
TO authenticated
USING (user_id = auth.uid() AND active);

-- Remove all direct anonymous/authenticated access to approval rows.
REVOKE ALL PRIVILEGES ON TABLE public.pending_approvals FROM anon, authenticated;
REVOKE UPDATE (status, resolved_at) ON TABLE public.pending_approvals FROM anon;

GRANT SELECT ON TABLE public.pending_approvals TO authenticated;

DROP POLICY IF EXISTS "Permitir lectura anon" ON public.pending_approvals;
DROP POLICY IF EXISTS "Permitir update anon" ON public.pending_approvals;
DROP POLICY IF EXISTS anon_review_pending_approvals ON public.pending_approvals;
DROP POLICY IF EXISTS approval_reviewer_read_pending ON public.pending_approvals;

CREATE POLICY approval_reviewer_read_pending
ON public.pending_approvals
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.approval_reviewers AS reviewer
        WHERE reviewer.user_id = auth.uid()
          AND reviewer.active
    )
);

CREATE OR REPLACE FUNCTION public.review_pending_approval(
    p_approval_id text,
    p_decision text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, auth
AS $function$
DECLARE
    v_user_id uuid := auth.uid();
    v_updated integer;
BEGIN
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'authenticated reviewer required'
            USING ERRCODE = '42501';
    END IF;

    IF p_decision IS NULL OR p_decision NOT IN ('approved', 'rejected') THEN
        RAISE EXCEPTION 'decision must be approved or rejected'
            USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.approval_reviewers AS reviewer
        WHERE reviewer.user_id = v_user_id
          AND reviewer.active
    ) THEN
        RAISE EXCEPTION 'reviewer is not allowlisted'
            USING ERRCODE = '42501';
    END IF;

    UPDATE public.pending_approvals
       SET status = p_decision,
           resolved_at = clock_timestamp()
     WHERE id = p_approval_id
       AND status = 'pending';

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$function$;

REVOKE ALL ON FUNCTION public.review_pending_approval(text, text)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.review_pending_approval(text, text)
TO authenticated;
