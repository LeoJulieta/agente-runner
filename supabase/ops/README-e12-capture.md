# E12 scheduled capture — sandbox candidate

This directory contains an **unapplied operational candidate**. Nothing here creates a production job unless an operator explicitly executes the SQL.

## Required Edge Function secrets

- `SUPABASE_URL`
- `SUPABASE_SECRET_KEYS` (Supabase-managed JSON map; prefer a dedicated key named `e12-capture`, with `default` as fallback)
- Transitional only: `SUPABASE_SERVICE_ROLE_KEY` is the legacy JWT-based key; do not place a modern `sb_secret_` key in this variable
- `YOUTUBE_API_KEY`
- `E12_CRON_HMAC_SECRET` (at least 32 random bytes)

Store the HMAC secret and the function URL in Supabase Vault under exactly:

- `e12_cron_hmac_secret`
- `e12_capture_function_url`

The modern secret key is read from Supabase's injected `SUPABASE_SECRET_KEYS` JSON map and sent only as the `apikey` header on outbound Data API calls. The worker prefers the component-specific `e12-capture` key, then `default`. It uses the legacy `SUPABASE_SERVICE_ROLE_KEY` only as a transitional fallback when the modern map is absent. **Never place either key in pg_net headers, queue rows, cron SQL, request bodies, logs, or source control.** The project's pg_net queue tables have broad PUBLIC ACLs.

## Request authentication

The Cron SQL signs a canonical request with HMAC-SHA256: HTTP method, exact pathname, Unix timestamp, and SHA-256 digest of the exact request body. The queue stores only the timestamp and signature (plus ordinary request metadata); it never stores the service-role key. The Edge Function rejects timestamps outside a 120-second skew window and accepts only an empty body or `{}`. The request cannot provide a video ID, view count, publication time, or row ID.

## Candidate discovery and evidence

The worker uses `created_at` only as a coarse candidate filter (last six hours); it never derives the outcome elapsed time from that field. It fetches `snippet.publishedAt`, `statistics.viewCount`, and `status.privacyStatus` from YouTube, records response-receipt time after the full body is read, validates the public video and uint64 count, and persists only through the fenced batch RPC `public.pr_d_capture_views_batch(jsonb)`, which delegates each row to the internal first-write-wins CAS routine.

The SQL CAS remains the final first-write-wins authority. Legacy `hs_al_publicar_al_sync` is never updated.

## Not yet done

- No Edge Function deployed.
- No Vault secret created or read.
- No Cron job created.
- No pg_net ACL changed.
- No production DDL/DML or RPC write executed.
- The implementation remains on the isolated `sandbox/e12-postgrest-contract-2026-11-13` branch in `LeoJulieta/agente-runner`; it has not been merged or deployed.

## Replay control, lease and fencing

The worker first calls the service-role-only `pr_d_claim_e12_worker_slot` RPC. Its versioned singleton slot permits one successful invocation per signed UTC minute and rejects replays of the same minute. The slot is not the execution lease.

The worker then claims a singleton lease with owner/run ID, expiration and a monotonically increasing fencing token. It renews the lease before each YouTube batch and again if the remaining TTL margin is insufficient; it releases the lease on exit. A crashed worker becomes replaceable after expiry. Any stale worker that wakes after takeover is rejected by the fencing token. The batch CAS validates the active lease and token for every observation.

CI #99 exercised eight simultaneous contenders for the same lease and eight simultaneous writes to the same observation: exactly one lease owner and exactly one first-write winner. It also tested takeover after forced expiry and rejection of stale renewal, release and write operations. This proves contention safety for the singleton resource, not eight workers doing useful work concurrently.

The HMAC signature remains visible in the pg_net queue and is valid for at most 120 seconds. Replaying it cannot cause a second worker run for the same minute. This does not replace the need to audit pg_net ACLs and existing jobs before deployment.

The worker caps one cycle at 500 candidates and sends CAS writes in batches of 1–50. If the result would be truncated, it fails closed before calling YouTube rather than silently skipping older candidates. A larger backlog requires an explicit pagination/quota design.

## Modern Supabase API key contract

The worker uses the modern opaque `sb_secret_...` key from the platform-provided `SUPABASE_SECRET_KEYS` JSON map. It prefers the `e12-capture` named key, then `default`, and sends it in `apikey` only. It does not send an opaque secret key as `Authorization: Bearer`, because the new keys are not JWTs.

Supabase's hosted API Gateway resolves a secret key to the built-in PostgreSQL `service_role` role. A standalone PostgREST container does not implement that gateway translation; the E2E test therefore asserts the outbound `apikey` contract and uses a clearly marked test adapter to translate the disposable key into a test JWT. This is not proof against the hosted gateway itself.

References (checked 2026-11-14):
- https://supabase.com/docs/guides/getting-started/api-keys
- https://supabase.com/docs/guides/getting-started/migrating-to-new-api-keys
- https://supabase.com/docs/guides/functions/auth-headers

## Current evidence and limits

- CI #78: batch CAS, Deno 31 and PostgreSQL 13 tests passed.
- CI #79: PostgREST HTTP contract passed.
- CI #98: all five E12 migrations applied in order on a synthetic legacy baseline.
- CI #99: eight-way lease contention, eight-way CAS contention and expired-lease takeover passed.
- CI #104: modern Supabase key resolver and legacy-key boundary passed.
- CI #110: local Supabase API Gateway end-to-end test was added; check its final result before claiming the hosted-gateway contract verified.

The current PostgREST standalone test uses a test adapter to translate the disposable modern key into a JWT for bare PostgREST. It does not represent the hosted gateway. The new local Supabase stack test is intended to close that gap.

**Privilege warning:** a modern `sb_secret_...` key resolves to PostgreSQL `service_role` and has broad elevated access. A per-component key helps rotate/revoke independently but does not provide fine-grained SQL privileges. Do not distribute it to autonomous agents. Before production, design and verify a narrower execution identity or ensure a single tightly controlled executor is the only custodian.
