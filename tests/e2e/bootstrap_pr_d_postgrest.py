"""Create the PostgREST HTTP fixture only after proving the DB is disposable."""
import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.conninfo import conninfo_to_dict


ROOT = Path(__file__).resolve().parents[2]
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}


def main():
    if os.getenv("PR_D_DISPOSABLE_DATABASE") != "1":
        raise SystemExit("refusing_setup_without_disposable_opt_in")
    api_host = urlparse(os.environ.get("SUPABASE_URL", "")).hostname
    if api_host not in ALLOWED_HOSTS:
        raise SystemExit("refusing_setup_non_loopback_api")
    dsn = os.environ.get("TEST_DATABASE_URL", "")
    params = conninfo_to_dict(dsn)
    hosts = params.get("host", "").split(",")
    if not hosts or any(host.strip().strip("[]").lower() not in ALLOWED_HOSTS for host in hosts):
        raise SystemExit("refusing_setup_non_loopback_database")
    if params.get("dbname") != "prd_test" or params.get("user") != "prd_test":
        raise SystemExit("refusing_setup_database_identity_mismatch")

    bootstrap = (ROOT / "tests/fixtures/pr_d_atomic_rpc_http_bootstrap.sql").read_text(encoding="utf-8")
    migration = (ROOT / "supabase/migrations/004_pr_d_v2_atomic_persistence.sql").read_text(encoding="utf-8")
    e12_migration = (ROOT / "supabase/migrations/20261112160000_pr_d_sync_capture_provenance_candidate.sql").read_text(encoding="utf-8")
    lab_results_migration = (ROOT / "supabase/migrations/20261112170000_pr_d_lab_results_rpc_write_boundary_candidate.sql").read_text(encoding="utf-8")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(bootstrap)
        conn.execute(migration)
        conn.execute(e12_migration)
        conn.execute(lab_results_migration)


if __name__ == "__main__":
    main()
