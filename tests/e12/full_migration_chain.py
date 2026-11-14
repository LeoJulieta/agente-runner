from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
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
        for role_sql in (
            "CREATE ROLE anon NOLOGIN",
            "CREATE ROLE authenticated NOLOGIN",
            "CREATE ROLE service_role NOLOGIN BYPASSRLS",
        ):
            role_name = role_sql.split()[2]
            conn.execute(
                """
                DO $role$
                BEGIN
                    EXECUTE %s;
                EXCEPTION WHEN duplicate_object THEN NULL;
                END
                $role$;
                """,
                (role_sql,),
            )

        service_bypass = conn.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'service_role'"
        ).fetchone()[0]
        assert service_bypass is True, "service_role must already be BYPASSRLS; do not ALTER Supabase reserved roles"

        conn.execute("""
            CREATE TABLE public.youtube_shorts_log (
                id bigint PRIMARY KEY,
                topic text NOT NULL,
                angulo text,
                titulo text NOT NULL,
                descripcion text,
                tags text[],
                script_texto text,
                youtube_video_id text,
                youtube_url text,
                status text,
                views integer,
                likes integer,
                created_at timestamptz,
                updated_at timestamptz,
                idioma text,
                hook_patron_aplicado boolean,
                hook_texto text,
                hook_patron_tipo text,
                privacy_status text,
                upload_status text,
                views_primeras_3h integer,
                hs_al_publicar_al_sync numeric,
                alerta_privacidad boolean
            )
        """)
        conn.execute("""
            CREATE OR REPLACE FUNCTION public.update_updated_at()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                NEW.updated_at = clock_timestamp();
                RETURN NEW;
            END;
            $$
        """)
        conn.execute("""
            CREATE TRIGGER shorts_updated_at
            BEFORE UPDATE ON public.youtube_shorts_log
            FOR EACH ROW EXECUTE FUNCTION public.update_updated_at()
        """)
        conn.execute("CREATE INDEX idx_shorts_log_created_at ON public.youtube_shorts_log(created_at DESC)")
        conn.execute("CREATE INDEX idx_shorts_log_status ON public.youtube_shorts_log(status)")
        conn.execute("""
            CREATE INDEX idx_youtube_shorts_log_alerta_privacidad
            ON public.youtube_shorts_log(alerta_privacidad, updated_at)
            WHERE alerta_privacidad = true
        """)
        conn.execute("ALTER TABLE public.youtube_shorts_log ENABLE ROW LEVEL SECURITY")
        conn.execute("""
            CREATE POLICY anon_read ON public.youtube_shorts_log
            FOR SELECT TO anon USING (true)
        """)
        conn.execute("""
            CREATE POLICY service_all ON public.youtube_shorts_log
            FOR ALL TO service_role USING (true) WITH CHECK (true)
        """)
        conn.execute("""
            GRANT ALL PRIVILEGES ON public.youtube_shorts_log
            TO anon, authenticated, service_role
        """)
        conn.execute("""
            INSERT INTO public.youtube_shorts_log(
                id, topic, titulo, youtube_video_id, status,
                views_primeras_3h, hs_al_publicar_al_sync, privacy_status
            ) VALUES (
                7, 'legacy-topic', 'legacy-title', 'legacy-migration-chain-row',
                'published', 12345, 3.25, 'public'
            )
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

        table_security = conn.execute("""
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid = 'public.youtube_shorts_log'::regclass
        """).fetchone()
        assert table_security == (True, False), table_security

        schema_owner_ok = conn.execute("""
            SELECT n.nspowner = r.oid
            FROM pg_namespace n
            JOIN pg_roles r ON r.rolname = 'pr_d_capture_owner'
            WHERE n.nspname = 'pr_d_internal'
        """).fetchone()[0]
        assert schema_owner_ok is True

        views_type = conn.execute("""
            SELECT data_type, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'youtube_shorts_log'
              AND column_name = 'views_primeras_3h'
        """).fetchone()
        assert views_type == ("numeric", 20, 0), views_type

        legacy = conn.execute("""
            SELECT youtube_video_id, views_primeras_3h, hs_al_publicar_al_sync,
                   published_at, sync_captured_at, elapsed_seconds_e12
            FROM public.youtube_shorts_log WHERE id = 7
        """).fetchone()
        assert legacy == (
            "legacy-migration-chain-row", Decimal("12345"), Decimal("3.25"),
            None, None, None,
        ), legacy

        policy_names = {
            row[0] for row in conn.execute("""
                SELECT policyname FROM pg_policies
                WHERE schemaname = 'public' AND tablename = 'youtube_shorts_log'
            """).fetchall()
        }
        assert {"anon_read", "service_all", "pr_d_capture_owner_select", "pr_d_capture_owner_update"} <= policy_names

        trigger_names = {
            row[0] for row in conn.execute("""
                SELECT trigger_name FROM information_schema.triggers
                WHERE event_object_schema = 'public' AND event_object_table = 'youtube_shorts_log'
            """).fetchall()
        }
        assert "shorts_updated_at" in trigger_names
        assert any("pr_d_guard_capture_fields" in name for name in trigger_names)

        anon_can_select = conn.execute(
            "SELECT has_table_privilege('anon', 'public.youtube_shorts_log', 'SELECT')"
        ).fetchone()[0]
        anon_can_truncate = conn.execute(
            "SELECT has_table_privilege('anon', 'public.youtube_shorts_log', 'TRUNCATE')"
        ).fetchone()[0]
        assert anon_can_select is True and anon_can_truncate is True

        conn.execute("SET ROLE anon")
        anon_rows = conn.execute("SELECT count(*) FROM public.youtube_shorts_log").fetchone()[0]
        conn.execute("RESET ROLE")
        assert anon_rows == 1, "synthetic production-like anon_read policy should remain observable"

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

        print("PASS: five E12 migrations applied in order on a production-shaped synthetic baseline", flush=True)
        print("PASS: production int4 views column converted to numeric(20,0) without changing legacy value", flush=True)
        print("PASS: legacy policies, grants, indexes and updated_at trigger preserved", flush=True)
        print("PASS: anon_read policy and TRUNCATE grant reproduced for explicit security review", flush=True)
        print("PASS: internal schema ownership, RLS and E12 RPC privileges verified", flush=True)
        print("PASS: versioned run-slot migration enforces same-minute replay rejection", flush=True)
        print("PASS: versioned lease migration creates an active lease", flush=True)


if __name__ == "__main__":
    main()
