from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg

DATABASE_URL = os.environ["TEST_DATABASE_URL"]
ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = [
    "20261112160000_pr_d_sync_capture_provenance_candidate.sql",
    "20261112180000_pr_d_e12_worker_run_slot.sql",
    "20261112231203_e12_worker_lease_fencing.sql",
    "20261112232558_e12_collector_attestation.sql",
    "20261113090000_e12_capture_batch_cas.sql",
]


def main() -> None:
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("""
            DO $$ BEGIN
                CREATE ROLE anon NOLOGIN;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)
        conn.execute("""
            DO $$ BEGIN
                CREATE ROLE authenticated NOLOGIN;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)
        conn.execute("""
            DO $$ BEGIN
                CREATE ROLE service_role NOLOGIN BYPASSRLS;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)
        conn.execute("ALTER ROLE service_role BYPASSRLS")
        conn.execute("""
            CREATE TABLE public.youtube_shorts_log (
                id bigint PRIMARY KEY,
                youtube_video_id text NOT NULL,
                status text NOT NULL DEFAULT 'published',
                created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                views_primeras_3h numeric,
                hs_al_publicar_al_sync numeric
            )
        """)
        conn.execute("ALTER TABLE public.youtube_shorts_log ENABLE ROW LEVEL SECURITY")
        conn.execute("""
            GRANT SELECT, INSERT, UPDATE, DELETE
            ON public.youtube_shorts_log TO service_role
        """)
        conn.execute("""
            INSERT INTO public.youtube_shorts_log(
                id, youtube_video_id, views_primeras_3h, hs_al_publicar_al_sync
            ) VALUES (7, 'legacy-migration-chain-row', 12345, 3.25)
        """)

        for filename in MIGRATIONS:
            sql = (ROOT / "supabase" / "migrations" / filename).read_text(encoding="utf-8")
            conn.execute(sql)
            print(f"APPLIED {filename} ({len(sql)} bytes)", flush=True)

        expected = [
            "public.pr_d_claim_e12_worker_slot(timestamptz)",
            "public.pr_d_claim_e12_worker_lease(uuid,integer)",
            "public.pr_d_renew_e12_worker_lease(uuid,bigint,integer)",
            "public.pr_d_release_e12_worker_lease(uuid,bigint)",
            "public.pr_d_capture_views_batch(jsonb)",
        ]
        for signature in expected:
            exists = conn.execute(
                "SELECT to_regprocedure(%s) IS NOT NULL", (signature,)
            ).fetchone()[0]
            assert exists, f"missing function after migration chain: {signature}"

        assert conn.execute("""
            SELECT relrowsecurity
            FROM pg_class
            WHERE oid = 'public.youtube_shorts_log'::regclass
        """).fetchone()[0] is True
        assert conn.execute("""
            SELECT n.nspowner = r.oid
            FROM pg_namespace n
            JOIN pg_roles r ON r.rolname = 'pr_d_capture_owner'
            WHERE n.nspname = 'pr_d_internal'
        """).fetchone()[0] is True

        legacy = conn.execute("""
            SELECT youtube_video_id, views_primeras_3h, hs_al_publicar_al_sync,
                   published_at, sync_captured_at, elapsed_seconds_e12
            FROM public.youtube_shorts_log WHERE id = 7
        """).fetchone()
        assert legacy == ("legacy-migration-chain-row", 12345, 3.25, None, None, None), legacy

        for signature in (
            "public.pr_d_claim_e12_worker_slot(timestamptz)",
            "public.pr_d_claim_e12_worker_lease(uuid,integer)",
            "public.pr_d_capture_views_batch(jsonb)",
        ):
            anon_exec = conn.execute(
                "SELECT has_function_privilege('anon', %s, 'EXECUTE')", (signature,)
            ).fetchone()[0]
            service_exec = conn.execute(
                "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (signature,)
            ).fetchone()[0]
            assert anon_exec is False, f"anon unexpectedly has EXECUTE on {signature}"
            assert service_exec is True, f"service_role lacks EXECUTE on {signature}"

        conn.execute("SET request.jwt.claims = '{\"role\":\"service_role\"}'")
        minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        first_slot = conn.execute(
            "SELECT public.pr_d_claim_e12_worker_slot(%s)", (minute,)
        ).fetchone()[0]
        duplicate_slot = conn.execute(
            "SELECT public.pr_d_claim_e12_worker_slot(%s)", (minute,)
        ).fetchone()[0]
        assert first_slot is True
        assert duplicate_slot is False

        lease = conn.execute("""
            SELECT * FROM public.pr_d_claim_e12_worker_lease(
                '11111111-2222-4333-8444-555555555555'::uuid, 90
            )
        """).fetchone()
        assert lease is not None and lease[0] is True, lease

        print("PASS: five E12 migrations applied in order on a synthetic legacy baseline", flush=True)
        print("PASS: legacy capture row preserved unchanged", flush=True)
        print("PASS: internal schema ownership and RLS verified", flush=True)
        print("PASS: anon denied and service_role granted on E12 RPCs", flush=True)
        print("PASS: versioned run-slot migration enforces same-minute replay rejection", flush=True)
        print("PASS: versioned lease migration creates an active lease", flush=True)


if __name__ == "__main__":
    main()
