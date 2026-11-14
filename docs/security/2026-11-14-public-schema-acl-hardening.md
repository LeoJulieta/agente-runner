# Public schema ACL hardening — 2026-11-14

These migrations were applied to the connected Supabase project and verified through effective privilege queries.

## Applied migrations

- 20261114184047_harden_public_table_truncate_and_defaults.sql
  - Removes TRUNCATE from anon and authenticated on all existing public tables.
  - Removes all default table privileges for anon/authenticated on future public tables created by postgres.
- 20261114184123_revoke_client_dml_except_pending_approval_update.sql
  - Removes INSERT, UPDATE, DELETE, REFERENCES and TRIGGER from anon/authenticated on all existing public tables.
  - Re-grants only UPDATE on pending_approvals to anon, temporarily preserving the existing approval dashboard path.
- 20261114184737_restrict_anon_pending_approval_update_columns_and_transition.sql
  - Revokes table-level UPDATE from anon and grants only column-level UPDATE on status and resolved_at.
  - Replaces the permissive policy with a pending → approved/rejected transition requiring resolved_at.
- 20261114184737_restrict_anon_pending_approval_update_columns_and_transition.sql
  - Restricts anonymous UPDATE to status and resolved_at columns only.
  - Replaces the open policy with a pending → approved/rejected transition and requires resolved_at.

## Verification after application

- Public tables: 34.
- anon: INSERT on 0 tables; table-level UPDATE on 0 tables but column-level UPDATE only on status and resolved_at in pending_approvals; DELETE on 0; TRUNCATE on 0.
- authenticated: INSERT/UPDATE/DELETE/TRUNCATE on 0 tables.
- service_role: DML privileges preserved on 34/34 tables and TRUNCATE on 34/34.
- No rows, RLS policies, table definitions, functions, secrets, cron jobs or webhooks were changed.

## Residual risk

- pending_approvals still allows anon SELECT and UPDATE under permissive policies; replace with Supabase Auth + reviewer allowlist + atomic review RPC before revoking that temporary path.
- Several public SELECT policies use USING(true) on content-bearing tables. Review column-level exposure and replace with narrow views/projections where appropriate.
- The default ACL for supabase_admin in public remains unchanged. All 34 current application tables were verified to be owned by postgres; review the supabase_admin residual before creating public application tables under that role.
- RLS is enabled on all 34 public tables. Five have no policies; do not assume public access merely from table grants because RLS denies rows absent a policy, but verify grants, views and functions.

## Operational rules

- Never restore anonymous TRUNCATE as rollback.
- Do not revoke pending_approvals SELECT/UPDATE until authenticated reviewer flow is deployed and tested; otherwise the current dashboard stops working.
- Keep service_role server-side only.
