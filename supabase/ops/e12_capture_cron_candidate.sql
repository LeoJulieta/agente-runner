-- MANUAL ONLY: do not execute until the Edge Function is deployed,
-- the HMAC secret and function URL are provisioned in Vault, and deployment
-- has explicit approval. This file is deliberately outside supabase/migrations.
-- The Edge Function claims a private single-use slot for the signed UTC minute
-- before any YouTube request, so replay cannot repeat the worker cycle.
--
-- IMPORTANT: pg_net request queues are readable under the current project ACL.
-- This job signs method, path, timestamp and SHA-256 body digest; it never sends sb_secret/service_role.

DO $preflight$
DECLARE
  v_secret_length integer;
  v_function_url text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron')
     OR NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_net')
     OR NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto') THEN
    RAISE EXCEPTION 'E12 cron prerequisites missing: pg_cron, pg_net, pgcrypto';
  END IF;

  SELECT octet_length(decrypted_secret)
    INTO v_secret_length
    FROM vault.decrypted_secrets
   WHERE name = 'e12_cron_hmac_secret';

  IF v_secret_length IS NULL OR v_secret_length < 32 THEN
    RAISE EXCEPTION 'E12 HMAC secret missing or shorter than 32 characters';
  END IF;

  SELECT decrypted_secret
    INTO v_function_url
    FROM vault.decrypted_secrets
   WHERE name = 'e12_capture_function_url';

  IF v_function_url IS NULL
     OR v_function_url !~ '^https://[a-z0-9-]+\.supabase\.co/functions/v1/e12-capture$' THEN
    RAISE EXCEPTION 'E12 Edge Function URL missing or malformed';
  END IF;

  IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'pr-d-e12-capture-every-minute') THEN
    RAISE EXCEPTION 'E12 cron job already exists; inspect it before changing anything';
  END IF;
END
$preflight$;

SELECT cron.schedule(
  'pr-d-e12-capture-every-minute',
  '* * * * *',
  $job$
    WITH signing_secret AS (
      SELECT decrypted_secret AS secret
        FROM vault.decrypted_secrets
       WHERE name = 'e12_cron_hmac_secret'
    ),
    function_target AS (
      SELECT decrypted_secret AS url
        FROM vault.decrypted_secrets
       WHERE name = 'e12_capture_function_url'
    ),
    request_clock AS (
      SELECT floor(extract(epoch FROM clock_timestamp()))::bigint::text AS timestamp
    )
    SELECT net.http_post(
      url := function_target.url,
      body := '{}'::jsonb,
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-e12-timestamp', request_clock.timestamp,
        'x-e12-signature',
          encode(extensions.hmac(
            convert_to(
              'POST' || E'\\n' || '/functions/v1/e12-capture' || E'\\n' ||
              request_clock.timestamp || E'\\n' ||
              encode(extensions.digest(convert_to('{}', 'UTF8'), 'sha256'), 'hex'),
              'UTF8'
            ),
            signing_secret.secret,
            'sha256'
          ), 'hex')
      ),
      timeout_milliseconds := 15000
    )
    FROM signing_secret, function_target, request_clock;
  $job$
);
