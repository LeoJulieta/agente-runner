from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import psycopg


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

    with psycopg.connect(support.DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO pr_d_internal.e12_collector_key_registry(
                key_id, algorithm, public_key_spki_base64, hmac_secret, status
            ) VALUES (%s, 'Ed25519', %s, %s, 'active')
            """,
            (support.KEY_ID, support.PUBLIC_KEY, support.HMAC_SECRET),
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


if __name__ == "__main__":
    main()
