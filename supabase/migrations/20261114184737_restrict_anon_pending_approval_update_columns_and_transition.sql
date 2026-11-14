-- Applied to the connected production project as migration 20261114184737.
-- Anonymous approval writes are restricted to the two columns used by the
-- existing dashboard. A pending row can transition only to approved/rejected,
-- and the resolution timestamp is mandatory.
-- Anonymous SELECT remains temporarily enabled until Auth + reviewer allowlist
-- replaces the current dashboard path.

REVOKE UPDATE ON TABLE public.pending_approvals FROM anon;
GRANT UPDATE (status, resolved_at) ON TABLE public.pending_approvals TO anon;

DROP POLICY IF EXISTS "Permitir update anon" ON public.pending_approvals;
CREATE POLICY "anon_review_pending_approvals"
ON public.pending_approvals
FOR UPDATE
TO anon
USING (status = 'pending')
WITH CHECK (
  status IN ('approved', 'rejected')
  AND resolved_at IS NOT NULL
);
