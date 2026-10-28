import os
from concurrent.futures import ThreadPoolExecutor

import psycopg


MIGRATION = "supabase/migrations/004_pr_d_v2_atomic_persistence.sql"


def connect():
    return psycopg.connect(os.environ["TEST_DATABASE_URL"])


def call_rpc(conn, lab_id, run_id, baseline=3.5, fail_evidence=False):
    return conn.execute(
        """
        SELECT public.rpc_insert_baseline_and_evidence(
            %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s, %s, %s
        )
        """,
        (
            lab_id,
            0,
            "3.5" if baseline is not None else None,
            "fixture",
            '{"record_type":"evidence","fixture":true}',
            '{"sample_size":10,"passed":true}',
            "VERIFICADO",
            False,
            run_id,
        ),
    ).fetchone()[0]


def setup_database():
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
        with open(MIGRATION, encoding="utf-8") as f:
            conn.execute(f.read())


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
