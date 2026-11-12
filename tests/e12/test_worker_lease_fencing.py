import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg

DATABASE_URL = os.environ["TEST_DATABASE_URL"]
MIGRATION = os.environ["E12_LEASE_SQL_PATH"]
RUN_A = uuid.UUID("11111111-2222-4333-8444-555555555555")
RUN_B = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
PUBLISHED = "2026-10-30T02:30:00Z"
CAPTURED = "2026-10-30T05:30:00Z"


def connect():
    conn = psycopg.connect(DATABASE_URL)
    conn.execute("SET request.jwt.claims = '{\"role\":\"service_role\"}'")
    return conn


def bootstrap():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        for role in ("anon", "authenticated", "service_role"):
            conn.execute(f"DO $$ BEGIN CREATE ROLE {role}; EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
        conn.execute("""
            CREATE TABLE public.youtube_shorts_log (
                id bigint PRIMARY KEY, youtube_video_id text NOT NULL,
                status text NOT NULL DEFAULT 'published', created_at timestamptz NOT NULL DEFAULT now(),
                views_primeras_3h numeric(20,0), hs_al_publicar_al_sync numeric,
                published_at timestamptz, sync_captured_at timestamptz,
                elapsed_seconds_e12 numeric(20,6)
            )
        """)
        conn.execute("ALTER TABLE public.youtube_shorts_log ENABLE ROW LEVEL SECURITY")
        conn.execute("""
            CREATE ROLE pr_d_capture_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS
        """)
        conn.execute("CREATE SCHEMA pr_d_internal AUTHORIZATION pr_d_capture_owner")
        conn.execute("GRANT USAGE ON SCHEMA public TO pr_d_capture_owner")
        conn.execute("GRANT SELECT ON public.youtube_shorts_log TO pr_d_capture_owner")
        conn.execute("GRANT UPDATE (views_primeras_3h,published_at,sync_captured_at,elapsed_seconds_e12) ON public.youtube_shorts_log TO pr_d_capture_owner")
        conn.execute("CREATE POLICY pr_d_capture_owner_select ON public.youtube_shorts_log FOR SELECT TO pr_d_capture_owner USING (true)")
        conn.execute("CREATE POLICY pr_d_capture_owner_update ON public.youtube_shorts_log FOR UPDATE TO pr_d_capture_owner USING (true) WITH CHECK (true)")
        conn.execute("""
            CREATE FUNCTION public.pr_d_guard_capture_fields()
            RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
            SET search_path = pg_catalog, public
            AS $guard$
            BEGIN
              IF TG_OP = 'INSERT' THEN RETURN NEW; END IF;
              IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
              IF current_user <> 'pr_d_capture_owner' AND (
                NEW.views_primeras_3h IS DISTINCT FROM OLD.views_primeras_3h
                OR NEW.published_at IS DISTINCT FROM OLD.published_at
                OR NEW.sync_captured_at IS DISTINCT FROM OLD.sync_captured_at
                OR NEW.elapsed_seconds_e12 IS DISTINCT FROM OLD.elapsed_seconds_e12
                OR NEW.hs_al_publicar_al_sync IS DISTINCT FROM OLD.hs_al_publicar_al_sync
              ) THEN
                RAISE EXCEPTION 'prd_capture_write_denied' USING ERRCODE='42501';
              END IF;
              RETURN NEW;
            END;
            $guard$
        """)
        conn.execute("""
            CREATE TRIGGER youtube_shorts_log_pr_d_capture_guard
            BEFORE INSERT OR UPDATE OR DELETE ON public.youtube_shorts_log
            FOR EACH ROW EXECUTE FUNCTION public.pr_d_guard_capture_fields()
        """)
        conn.execute("INSERT INTO public.youtube_shorts_log(id,youtube_video_id) VALUES (1,'video-1')")
        conn.execute("""
            CREATE FUNCTION pr_d_internal.pr_d_capture_views_once(
              bigint,text,numeric,timestamptz,timestamptz
            ) RETURNS boolean LANGUAGE sql AS 'SELECT false'
        """)
        conn.execute("ALTER FUNCTION pr_d_internal.pr_d_capture_views_once(bigint,text,numeric,timestamptz,timestamptz) OWNER TO pr_d_capture_owner")
        conn.execute("GRANT USAGE ON SCHEMA pr_d_internal TO service_role")


def apply_migration():
    with open(MIGRATION, encoding="utf-8") as source:
        sql = source.read()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute(sql)


def claim(run_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM public.pr_d_claim_e12_worker_lease(%s, 90)", (run_id,)).fetchone()


def renew(run_id, token):
    with connect() as conn:
        return conn.execute("SELECT public.pr_d_renew_e12_worker_lease(%s, %s, 90)", (run_id, token)).fetchone()[0]


def release(run_id, token):
    with connect() as conn:
        return conn.execute("SELECT public.pr_d_release_e12_worker_lease(%s, %s)", (run_id, token)).fetchone()[0]


def test_exclusive_claim_renew_takeover_and_stale_owner_rejection():
    bootstrap()
    apply_migration()
    first = claim(RUN_A)
    assert first[0] is True and int(first[1]) == 1
    token_a = int(first[1])
    assert claim(RUN_B)[0] is False
    assert renew(RUN_A, token_a) is True
    assert release(RUN_A, token_a) is True

    second = claim(RUN_B)
    assert second[0] is True and int(second[1]) == token_a + 1
    token_b = int(second[1])
    assert renew(RUN_A, token_a) is False
    assert release(RUN_A, token_a) is False

    with connect() as conn:
        stale_write = conn.execute(
            "SELECT public.pr_d_capture_views_once(1,'video-1',123,%s,%s,%s,%s)",
            (PUBLISHED, CAPTURED, RUN_A, token_a),
        ).fetchone()[0]
        assert stale_write is False
        assert conn.execute("SELECT views_primeras_3h FROM public.youtube_shorts_log WHERE id=1").fetchone()[0] is None
        current_write = conn.execute(
            "SELECT public.pr_d_capture_views_once(1,'video-1',123,%s,%s,%s,%s)",
            (PUBLISHED, CAPTURED, RUN_B, token_b),
        ).fetchone()[0]
        assert current_write is True
        assert conn.execute("SELECT views_primeras_3h FROM public.youtube_shorts_log WHERE id=1").fetchone()[0] == 123


def test_two_simultaneous_claims_have_exactly_one_winner():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE pr_d_internal.e12_worker_lease")
    barrier = threading.Barrier(2)

    def contender(run_id):
        barrier.wait(timeout=10)
        return claim(run_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, (RUN_A, RUN_B)))
    assert sum(1 for result in results if result[0] is True) == 1
    assert sum(1 for result in results if result[0] is False) == 1


def test_lease_cannot_be_renewed_after_expiry():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("UPDATE pr_d_internal.e12_worker_lease SET lease_expires_at = clock_timestamp() - interval '1 second'")
    assert renew(RUN_B, 2) is False
