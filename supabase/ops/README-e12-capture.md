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

The worker uses `created_at` only as a coarse candidate filter (last six hours); it never derives the outcome elapsed time from that field. It fetches `snippet.publishedAt`, `statistics.viewCount`, and `status.privacyStatus` from YouTube, records response-receipt time after the full body is read, validates the public video and uint64 count, and persists only through `pr_d_capture_views_once`.

The SQL CAS remains the final first-write-wins authority. Legacy `hs_al_publicar_al_sync` is never updated.

## Not yet done

- No Edge Function deployed.
- No Vault secret created or read.
- No Cron job created.
- No pg_net ACL changed.
- No production DDL/DML or RPC write executed.
- The worker integration branch in `agente-autonomo` must pass its own CI and remain unmerged until the complete pipeline is audited.

## Replay control

Before reading candidates or calling YouTube, the worker calls the service-role-only RPC `pr_d_claim_e12_worker_slot`. Its private singleton table allows one successful claim per signed UTC minute, rejects older replays, and is not exposed through PostgREST. This is minute-level replay idempotency, not a distributed execution lease: a worker lasting longer than one minute can overlap the next minute's worker. A lease with owner, expiry, renewal, and crash recovery remains required before scheduling. The CAS still protects each row independently.

The HMAC signature remains visible in the pg_net queue and is valid for at most 120 seconds. Replaying it cannot cause a second worker run for the same minute; a first valid invocation simply triggers the same bounded worker. This does not replace the need to audit pg_net ACLs and existing jobs before deployment.

The worker asks PostgREST for an exact candidate count and caps one cycle at 500 rows. If the result would be truncated, it fails closed before calling YouTube rather than silently skipping older candidates. A larger backlog requires an explicit pagination/quota design.

## Modern Supabase API key contract

The worker uses the modern opaque `sb_secret_...` key from the platform-provided `SUPABASE_SECRET_KEYS` JSON map. It prefers the `e12-capture` named key, then `default`, and sends it in `apikey` only. It does not send an opaque secret key as `Authorization: Bearer`, because the new keys are not JWTs.

Supabase's hosted API Gateway resolves a secret key to the built-in PostgreSQL `service_role` role. A standalone PostgREST container does not implement that gateway translation; the E2E test therefore asserts the outbound `apikey` contract and uses a clearly marked test adapter to translate the disposable key into a test JWT. This is not proof against the hosted gateway itself.

References (checked 2026-11-14):
- https://supabase.com/docs/guides/getting-started/api-keys
- https://supabase.com/docs/guides/getting-started/migrating-to-new-api-keys
- https://supabase.com/docs/guides/functions/auth-headers
