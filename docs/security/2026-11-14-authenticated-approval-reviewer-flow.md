# Authenticated approval reviewer flow — candidate

Date: 2026-11-14  
Status: sandbox candidate only; **not applied to production**

## Why

The production dashboard currently relies on anonymous SELECT and UPDATE on pending_approvals. The latest ACL migrations constrained anonymous UPDATE to status/resolved_at and a one-way pending → approved/rejected transition, but anyone holding the public anon key can still approve/reject pending rows and read the approval payload.

This candidate replaces that path with Supabase Auth + a reviewer allowlist + one atomic RPC.

## Migration behavior

File: 20261114190000_authenticated_approval_reviewer_flow.sql

- Creates approval_reviewers with user_id referencing auth.users and an active flag.
- Enables RLS and permits an authenticated user to read only their own active reviewer row.
- Removes all anon/authenticated table privileges from pending_approvals, then grants SELECT only to authenticated.
- Removes the anonymous SELECT/UPDATE policies.
- Grants pending row SELECT only when auth.uid() is in the active reviewer allowlist.
- Creates review_pending_approval(text,text), SECURITY DEFINER with a fixed search_path.
- The RPC checks auth.uid(), active allowlist membership, and decision ∈ {approved,rejected}; it performs a single UPDATE WHERE status='pending' and returns whether exactly one row changed.
- Grants RPC execution to authenticated only; anon and PUBLIC cannot execute it.
- Direct UPDATE is not granted to authenticated; all review transitions go through the RPC.

## Reviewer enrollment

The migration intentionally does not invent or hardcode a reviewer identity. After the reviewer has a confirmed Supabase Auth account, an administrator must add that Auth user UUID:

\`\`\`sql
INSERT INTO public.approval_reviewers(user_id, active)
VALUES ('<AUTH_USER_UUID>'::uuid, true)
ON CONFLICT (user_id) DO UPDATE SET active = true;
\`\`\`

Do not put a service_role key in the dashboard or share it with agents.

## Dashboard integration still required

- Replace the anonymous-key login with Supabase Auth sign-in (password or OTP).
- Keep the publishable key in the apikey header; keep the short-lived access token in memory and send it as Authorization: Bearer.
- Load pending_approvals only after authentication; the RLS policy returns rows only for active reviewers.
- Replace direct PATCH with POST /rest/v1/rpc/review_pending_approval and the exact RPC args.
- Display a clear "not authorized" state for authenticated but non-allowlisted users.
- Do not persist service credentials in localStorage.

The existing dashboard currently sends reviewed_at, while the real table column is resolved_at. The sandbox dashboard branch was corrected to resolved_at, but it is not merged/deployed.

## Tests and limits

A PostgreSQL 17 integration test creates disposable roles/auth schema, applies this migration, and verifies:

- anonymous access denied;
- authenticated non-reviewer sees zero rows and cannot call the RPC;
- allowlisted reviewer can read and approve once;
- second transition returns false;
- status/resolved_at are updated atomically;
- direct UPDATE is not granted;
- function is SECURITY DEFINER with fixed search_path;
- service_role retains backend update capability.

These tests do not yet prove Supabase Auth JWT validation through a live PostgREST Gateway. That E2E test is a required next gate.

## Rollout and rollback

Do not apply this migration until the dashboard Auth integration is ready. Applying it immediately disables the current anonymous dashboard path by design.

Before production:
1. verify Auth email/OTP settings and reviewer account;
2. test actual JWT claims through local Supabase/PostgREST;
3. test non-allowlisted denial and duplicate review races;
4. backup and verify restore;
5. deploy dashboard Auth code and migration in a controlled order;
6. insert the reviewer UUID;
7. verify anon cannot SELECT, UPDATE or execute the RPC;
8. verify reviewer can approve/reject only pending rows.

Rollback must not restore anonymous read/write access. If the authenticated UI fails, keep approvals disabled while fixing the authenticated path.
