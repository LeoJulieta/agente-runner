from __future__ import annotations

import base64
import importlib.util
import os
from pathlib import Path

import psycopg
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    module_path = root / "tests" / "e12" / "test_worker_lease_fencing.py"
    spec = importlib.util.spec_from_file_location("e12_worker_test_support", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load E12 PostgreSQL test support")
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)

    support.bootstrap()
    support.apply_sql_file(support.LEASE_MIGRATION)
    support.apply_sql_file(support.ATTESTATION_MIGRATION)
    support.apply_sql_file(support.BATCH_MIGRATION)

    # Ephemeral key material exists only in this disposable CI database/job.
    key_id = "e12-postgrest-e2e-key"
    private_key = Ed25519PrivateKey.generate()
    private_key_b64 = base64.b64encode(private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )).decode("ascii")
    public_key_b64 = base64.b64encode(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )).decode("ascii")
    hmac_secret = bytes([11]) * 32
    hmac_secret_b64 = base64.b64encode(hmac_secret).decode("ascii")

    with psycopg.connect(support.DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO pr_d_internal.e12_collector_key_registry(
                key_id, algorithm, public_key_spki_base64, hmac_secret, status
            ) VALUES (%s, 'Ed25519', %s, %s, 'active')
            """,
            (key_id, public_key_b64, hmac_secret),
        )
        # The companion HTTP RPC contract test uses its own deterministic
        # fixture identity/HMAC. Register it separately from the worker E2E key.
        conn.execute(
            """
            INSERT INTO pr_d_internal.e12_collector_key_registry(
                key_id, algorithm, public_key_spki_base64, hmac_secret, status
            ) VALUES (%s, 'Ed25519', %s, %s, 'active')
            """,
            (support.KEY_ID, support.PUBLIC_KEY, support.HMAC_SECRET),
        )
        conn.execute(
            """
            INSERT INTO public.youtube_shorts_log(id, youtube_video_id, status, created_at)
            VALUES (4, 'e12-postgrest-e2e-video', 'published', clock_timestamp())
            """
        )
        # This idempotency slot is a test-only stand-in for the pre-existing
        # worker-slot RPC. It is deliberately confined to the disposable DB.
        conn.execute(
            """
            CREATE TABLE public.e12_worker_slot_test (
                minute_bucket timestamptz PRIMARY KEY
            )
            """
        )
        conn.execute(
            """
            CREATE FUNCTION public.pr_d_claim_e12_worker_slot(p_minute_bucket timestamptz)
            RETURNS boolean
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $slot$
            DECLARE
                v_claims jsonb;
                v_inserted integer;
            BEGIN
                v_claims := NULLIF(current_setting('request.jwt.claims', true), '')::jsonb;
                IF v_claims ->> 'role' IS DISTINCT FROM 'service_role' THEN
                    RAISE EXCEPTION 'test_worker_slot_role_denied' USING ERRCODE = '42501';
                END IF;
                INSERT INTO public.e12_worker_slot_test(minute_bucket)
                VALUES (p_minute_bucket)
                ON CONFLICT DO NOTHING;
                GET DIAGNOSTICS v_inserted = ROW_COUNT;
                RETURN v_inserted = 1;
            END;
            $slot$
            """
        )
        conn.execute(
            "REVOKE ALL ON FUNCTION public.pr_d_claim_e12_worker_slot(timestamptz) FROM PUBLIC, anon, authenticated"
        )
        conn.execute(
            "GRANT EXECUTE ON FUNCTION public.pr_d_claim_e12_worker_slot(timestamptz) TO service_role"
        )
        conn.execute(
            "CREATE ROLE authenticator LOGIN NOINHERIT PASSWORD 'e12-ci-authenticator-only'"
        )
        conn.execute(
            "GRANT anon, authenticated, service_role TO authenticator"
        )
        conn.execute("GRANT USAGE ON SCHEMA public TO authenticator")
        conn.execute("NOTIFY pgrst, 'reload schema'")

    if len(os.environ["PGRST_JWT_SECRET"].encode("utf-8")) < 32:
        raise RuntimeError("test JWT secret must contain at least 32 bytes")

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        ephemeral_values = {
            "E12_TEST_CRON_SECRET": "e12-disposable-cron-hmac-secret-32-bytes-min",
            "E12_TEST_PRIVATE_KEY_PKCS8_B64": private_key_b64,
            "E12_TEST_PUBLIC_KEY_SPKI_B64": public_key_b64,
            "E12_TEST_HMAC_SECRET_B64": hmac_secret_b64,
        }
        # Mask ephemeral credentials before GitHub Actions prints later step environments.
        for value in ephemeral_values.values():
            print(f"::add-mask::{value}", flush=True)
        with open(github_env, "a", encoding="utf-8") as output:
            for name, value in ephemeral_values.items():
                output.write(f"{name}={value}\n")


if __name__ == "__main__":
    main()
