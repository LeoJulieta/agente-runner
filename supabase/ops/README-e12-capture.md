# E12 scheduled capture — sandbox candidate

This directory contains an **unapplied operational candidate**. Nothing here creates a production job unless an operator explicitly executes the SQL.

## Required Edge Function secrets

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (the current `sb_secret_` key may be stored as this Edge Function secret)
- `YOUTUBE_API_KEY`
- `E12_CRON_HMAC_SECRET` (at least 32 random bytes)

Store the HMAC secret and the function URL in Supabase Vault under exactly:

- `e12_cron_hmac_secret`
- `e12_capture_function_url`

The service-role key belongs only in the Edge Function environment. **Never place it in pg_net headers, queue rows, cron SQL, or request bodies.** The current project's pg_net queue tables have broad PUBLIC ACLs.

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

Before reading candidates or calling YouTube, the worker calls the service-role-only RPC `pr_d_claim_e12_worker_slot`. Its private singleton table allows one successful claim per signed UTC minute, rejects older replays, and is not exposed through PostgREST. The CAS still protects each row independently.

The HMAC signature remains visible in the pg_net queue and is valid for at most 120 seconds. Replaying it cannot cause a second worker run for the same minute; a first valid invocation simply triggers the same bounded worker. This does not replace the need to audit pg_net ACLs and existing jobs before deployment.

The worker asks PostgREST for an exact candidate count and caps one cycle at 500 rows. If the result would be truncated, it fails closed before calling YouTube rather than silently skipping older candidates. A larger backlog requires an explicit pagination/quota design.
