-- Applied to the connected production project as migration 20261114184123.
-- Client roles have no table DML except the temporary anonymous UPDATE path
-- on pending_approvals, which the current dashboard still depends on.
-- RLS policies remain unchanged; service_role privileges remain unchanged.

REVOKE INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
ON ALL TABLES IN SCHEMA public
FROM anon, authenticated;

GRANT UPDATE ON TABLE public.pending_approvals TO anon;
