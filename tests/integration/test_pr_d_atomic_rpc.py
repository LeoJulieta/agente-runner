import os
from concurrent.futures import ThreadPoolExecutor

import psycopg


MIGRATION = "supabase/migrations/004_pr_d_v2_atomic_persistence.sql"


def connect():
    return psycopg.connect(os.environ["TEST_DATABASE_URL"])


def call_rpc(conn, lab_id, run_id, baseline=3.5, fail_evidence=False, gen=0):
    return conn.execute(
        """
        SELECT public.rpc_insert_baseline_and_evidence(
            %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s, %s, %s
        )
        """,
        (
            lab_id,
            gen,
            str(baseline) if baseline is not None else None,
            "fixture",
            '{"record_type":"evidence","fixture":true}',
            '{"sample_size":10,"passed":true}',
            "VERIFICADO",
            False,
            run_id,
        ),
    ).fetchone()[0]


def setup_database(apply_migration=True):
    with connect() as conn:
        conn.execute("""
            DROP TABLE IF EXISTS public.lab_results CASCADE;
            CREATE TABLE public.lab_results (
                id bigserial PRIMARY KEY,
                lab_id text NOT NULL,
                gen integer DEFAULT 0,
                params jsonb,
                metrics jsonb,
                status text CHECK (status IN ('PROMETE','VERIFICADO','STALE','CADUCADO')),
                evidence_count integer DEFAULT 0,
                reproducible boolean DEFAULT false,
                last_test timestamptz,
                creado_en timestamptz DEFAULT now()
            );
        """)
        if apply_migration:
            with open(MIGRATION, encoding="utf-8") as migration_file:
                conn.execute(migration_file.read())


def install_failure_trigger(conn):
    conn.execute("""
        CREATE OR REPLACE FUNCTION public.test_fail_evidence_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.params ->> 'record_type' = 'evidence' THEN
            RAISE EXCEPTION 'injected_evidence_failure';
          END IF;
          RETURN NEW;
        END;
        $$;
        CREATE TRIGGER test_fail_evidence
        BEFORE INSERT ON public.lab_results
        FOR EACH ROW EXECUTE FUNCTION public.test_fail_evidence_insert();
    """)


def test_failure_after_baseline_rolls_back_everything():
    setup_database()
    with connect() as conn:
        install_failure_trigger(conn)
        try:
            call_rpc(conn, "atomic-rollback", "rollback-run")
            raise AssertionError("RPC unexpectedly succeeded")
        except psycopg.Error as exc:
            assert "injected_evidence_failure" in str(exc)
        conn.rollback()
        assert conn.execute(
            "SELECT count(*) FROM public.lab_results WHERE lab_id=%s",
            ("atomic-rollback",),
        ).fetchone()[0] == 0


def test_retry_is_idempotent_and_does_not_duplicate_rows():
    setup_database()
    with connect() as conn:
        first = call_rpc(conn, "idempotent", "same-run")
        second = call_rpc(conn, "idempotent", "same-run")
        assert first["id"] == second["id"]
        assert second["idempotent_replay"] is True
        assert conn.execute(
            "SELECT count(*) FROM public.lab_results WHERE lab_id=%s AND params->>'record_type'='baseline'",
            ("idempotent",),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM public.lab_results WHERE lab_id=%s AND params->>'record_type'='evidence'",
            ("idempotent",),
        ).fetchone()[0] == 1


def test_concurrent_same_run_id_creates_one_evidence():
    setup_database()

    def run():
        with connect() as conn:
            return call_rpc(conn, "concurrent", "one-logical-run")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results[0]["id"] == results[1]["id"]
    with connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM public.lab_results WHERE lab_id=%s AND params->>'record_type'='evidence'",
            ("concurrent",),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM public.lab_results WHERE lab_id=%s AND params->>'record_type'='baseline'",
            ("concurrent",),
        ).fetchone()[0] == 1



def test_baseline_is_isolated_by_generation():
    setup_database()
    with connect() as conn:
        gen0 = call_rpc(conn, "H990", "run-gen-0", baseline=3.5, gen=0)
        gen1 = call_rpc(conn, "H990", "run-gen-1", baseline=8.25, gen=1)
        assert gen0["baseline_created"] is True
        assert gen1["baseline_created"] is True
        rows = conn.execute(
            """
            SELECT gen, params->>'baseline' AS baseline
            FROM public.lab_results
            WHERE lab_id=%s AND params->>'record_type'='baseline'
            ORDER BY gen
            """,
            ("H990",),
        ).fetchall()
        assert rows == [(0, "3.5"), (1, "8.25")]


def test_same_generation_does_not_accept_provisional_baseline_after_race():
    setup_database()
    with connect() as conn:
        call_rpc(conn, "H990", "first-run", baseline=3.5, gen=0)
        conn.commit()  # Keep the first successful transaction when the retry fails.
        try:
            call_rpc(conn, "H990", "stale-provisional-run", baseline=9.0, gen=0)
            raise AssertionError("RPC accepted evidence computed against a provisional baseline")
        except psycopg.Error as exc:
            assert "prd_atomic_baseline_race_retry" in str(exc)
        conn.rollback()
        assert conn.execute(
            "SELECT count(*) FROM public.lab_results WHERE lab_id=%s AND params->>'record_type'='evidence'",
            ("H990",),
        ).fetchone()[0] == 1



def test_migration_fails_safely_when_historical_baselines_are_duplicated():
    setup_database(apply_migration=False)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO public.lab_results (lab_id, gen, params, metrics, status)
            VALUES
              ('H-HIST', 0, '{"record_type":"baseline","baseline":3.5,"baseline_frozen":true}', '{}', 'PROMETE'),
              ('H-HIST', 0, '{"record_type":"baseline","baseline":4.5,"baseline_frozen":true}', '{}', 'PROMETE')
            """
        )
        conn.commit()

        try:
            with open(MIGRATION, encoding="utf-8") as migration_file:
                conn.execute(migration_file.read())
            raise AssertionError("Migration unexpectedly accepted duplicate historical baselines")
        except psycopg.Error as exc:
            assert "prd_atomic_migration_preflight_failed" in str(exc)
        conn.rollback()

        # The migration must not delete, rewrite, or partially constrain historical rows.
        assert conn.execute(
            "SELECT count(*) FROM public.lab_results WHERE lab_id='H-HIST'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND indexname='uq_lab_results_prd_baseline_generation'"
        ).fetchone()[0] == 0
