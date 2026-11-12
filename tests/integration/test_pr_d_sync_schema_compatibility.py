"""PostgreSQL integration tests isolated to an opted-in disposable schema.

The DSN is validated before connecting. Only schema pr_d_test is dropped;
the test never drops or truncates objects in public or other schemas.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import os

import pytest
import psycopg
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "tests/fixtures/pr_d_youtube_shorts_log_schema.sql"
MIGRATION = ROOT / "supabase/migrations/20261112160000_pr_d_sync_capture_provenance_candidate.sql"
DATABASE_URL = os.getenv("DATABASE_URL")
ALLOWED_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _assert_disposable_database(dsn):
    try:
        params = conninfo_to_dict(dsn)
    except (TypeError, ValueError):
        pytest.fail("unsafe_database_url: invalid libpq connection string")
    hosts = params.get("host", "").split(",")
    if os.getenv("PR_D_DISPOSABLE_DATABASE") != "1":
        pytest.fail("unsafe_database_url: explicit disposable opt-in required")
    if not hosts or any(host.strip().strip("[]").lower() not in ALLOWED_LOCAL_HOSTS for host in hosts):
        pytest.fail("unsafe_database_url: only loopback hosts are allowed")
    if params.get("dbname") != "prd_test" or params.get("user") != "prd_test":
        pytest.fail("unsafe_database_url: database and user must both be prd_test")


@pytest.fixture(scope="module")
def disposable_database():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL absent; disposable PostgreSQL is required")
    _assert_disposable_database(DATABASE_URL)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        # Scope all destructive setup to a dedicated schema, not public.
        conn.execute("DROP SCHEMA IF EXISTS pr_d_test CASCADE")
        conn.execute("CREATE SCHEMA pr_d_test")
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        migration = MIGRATION.read_text(encoding="utf-8")
        migration = migration.replace("public.youtube_shorts_log", "pr_d_test.youtube_shorts_log")
        migration = migration.replace("public.pr_d_capture_views_once", "pr_d_test.pr_d_capture_views_once")
        migration = migration.replace("public.pr_d_guard_capture_write", "pr_d_test.pr_d_guard_capture_write")
        migration = migration.replace("ON SCHEMA public", "ON SCHEMA pr_d_test")
        conn.execute(migration)
    yield DATABASE_URL


def insert_video(dsn, video_id="yt-fixture-001"):
    with psycopg.connect(dsn) as conn:
        return conn.execute(
            "INSERT INTO pr_d_test.youtube_shorts_log (youtube_video_id) VALUES (%s) RETURNING id",
            (video_id,),
        ).fetchone()[0]


def _cas(
    dsn,
    row_id,
    video_id,
    views,
    published_at="2026-10-30T02:30:00Z",
    captured_at="2026-10-30T05:30:00Z",
):
    with psycopg.connect(dsn) as conn:
        return conn.execute("""
            SELECT pr_d_test.pr_d_capture_views_once(
                %s, %s, %s, %s::timestamptz, %s::timestamptz
            )
        """, (row_id, video_id, views, published_at, captured_at)).fetchone()[0]


def test_schema_types_and_legacy_rows(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        columns = dict(conn.execute("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'pr_d_test' AND table_name = 'youtube_shorts_log'
        """).fetchall())
        stored = conn.execute("""
            SELECT views_primeras_3h, published_at, sync_captured_at
            FROM pr_d_test.youtube_shorts_log WHERE youtube_video_id = 'legacy-fixture'
        """).fetchone()
    assert columns["id"] == "bigint"
    assert columns["youtube_video_id"] == "text"
    assert columns["views_primeras_3h"] == "numeric"
    assert columns["published_at"] == "timestamp with time zone"
    assert columns["sync_captured_at"] == "timestamp with time zone"
    assert stored == (123, None, None)


def test_capture_rpc_is_executable_only_by_service_role(disposable_database):
    row_id = insert_video(disposable_database, "service-role-video")
    signature = (
        "pr_d_test.pr_d_capture_views_once("
        "bigint,text,numeric,timestamp with time zone,timestamp with time zone)"
    )
    with psycopg.connect(disposable_database) as conn:
        privileges = conn.execute(
            """
            SELECT
                has_function_privilege('service_role', %s, 'EXECUTE'),
                has_function_privilege('anon', %s, 'EXECUTE'),
                has_function_privilege('authenticated', %s, 'EXECUTE')
            """,
            (signature, signature, signature),
        ).fetchone()
        assert privileges == (True, False, False)

        conn.execute("SET ROLE service_role")
        captured = conn.execute(
            """
            SELECT pr_d_test.pr_d_capture_views_once(
                %s, %s, %s, %s::timestamptz, %s::timestamptz
            )
            """,
            (row_id, "service-role-video", 321,
             "2026-10-30T02:30:00Z", "2026-10-30T05:30:00Z"),
        ).fetchone()[0]
        assert captured is True

    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute(
            "SELECT views_primeras_3h FROM pr_d_test.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()[0]
    assert stored == 321


def test_migration_cas_is_reusable_and_first_write_wins(disposable_database):
    row_id = insert_video(disposable_database)
    assert _cas(disposable_database, row_id, "yt-fixture-001", 456) is True
    assert _cas(disposable_database, row_id, "yt-fixture-001", 999) is False
    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute("""
            SELECT views_primeras_3h FROM pr_d_test.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()[0]
    assert stored == 456


def test_wrong_youtube_id_cannot_claim_row(disposable_database):
    row_id = insert_video(disposable_database, "correct-video")
    assert _cas(disposable_database, row_id, "wrong-video", 9) is False


def test_check_accepts_closed_tolerance_and_rejects_values_outside_it(disposable_database):
    lower_id = insert_video(disposable_database, "lower-boundary")
    upper_id = insert_video(disposable_database, "upper-boundary")
    assert _cas(
        disposable_database, lower_id, "lower-boundary", 10,
        captured_at="2026-10-30T05:25:00Z",
    ) is True
    assert _cas(
        disposable_database, upper_id, "upper-boundary", 11,
        captured_at="2026-10-30T05:35:00Z",
    ) is True

    for video_id, captured_at in (
        ("below-lower-boundary", "2026-10-30T05:24:59.999999Z"),
        ("above-upper-boundary", "2026-10-30T05:35:00.000001Z"),
    ):
        row_id = insert_video(disposable_database, video_id)
        assert _cas(
            disposable_database, row_id, video_id, 10,
            captured_at=captured_at,
        ) is False

    # Exercise the CHECK itself with triggers bypassed only inside this
    # disposable superuser-owned test transaction; production paths never do this.
    with psycopg.connect(disposable_database) as conn:
        conn.execute("SET LOCAL session_replication_role = replica")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("""
                INSERT INTO pr_d_test.youtube_shorts_log
                    (youtube_video_id, published_at, sync_captured_at)
                VALUES ('metric-missing', '2026-10-30T02:30:00Z', '2026-10-30T05:30:00Z')
            """)


def test_negative_view_count_cannot_be_captured_or_inserted(disposable_database):
    row_id = insert_video(disposable_database, "negative-cas")
    assert _cas(disposable_database, row_id, "negative-cas", -1) is False
    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute(
            "SELECT views_primeras_3h FROM pr_d_test.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()[0]
    assert stored is None

    with psycopg.connect(disposable_database) as conn:
        conn.execute("SET LOCAL session_replication_role = replica")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("""
                INSERT INTO pr_d_test.youtube_shorts_log
                    (youtube_video_id, views_primeras_3h, published_at, sync_captured_at)
                VALUES ('negative-direct-insert', -1,
                        '2026-10-30T02:30:00Z', '2026-10-30T05:30:00Z')
            """)

    # Legacy-shaped rows without provenance are still allowed when valid,
    # but the metric invariant itself must never be bypassed by omitting timestamps.
    with psycopg.connect(disposable_database) as conn:
        conn.execute("SET LOCAL session_replication_role = replica")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("""
                INSERT INTO pr_d_test.youtube_shorts_log
                    (youtube_video_id, views_primeras_3h)
                VALUES ('negative-without-provenance', -1)
            """)


def test_migration_preflight_refuses_negative_legacy_values_without_rewriting(disposable_database):
    migration = MIGRATION.read_text(encoding="utf-8")
    migration = migration.replace("public.youtube_shorts_log", "pr_d_test.youtube_shorts_log")
    migration = migration.replace("public.pr_d_capture_views_once", "pr_d_test.pr_d_capture_views_once")

    # Commit a pre-existing legacy-invalid row before attempting the migration.
    # This distinguishes preservation of existing data from rollback of test setup.
    with psycopg.connect(disposable_database) as conn:
        conn.execute("SET LOCAL session_replication_role = replica")
        conn.execute("""
            ALTER TABLE pr_d_test.youtube_shorts_log
            DROP CONSTRAINT youtube_shorts_log_views_nonnegative_ck
        """)
        conn.execute("""
            INSERT INTO pr_d_test.youtube_shorts_log
                (youtube_video_id, views_primeras_3h)
            VALUES ('negative-legacy-row', -7)
        """)
        conn.commit()

    with psycopg.connect(disposable_database) as conn:
        with pytest.raises(
            psycopg.errors.CheckViolation,
            match="prd_sync_migration_preflight_failed",
        ):
            conn.execute(migration)
        conn.rollback()

    try:
        with psycopg.connect(disposable_database) as conn:
            legacy_value = conn.execute("""
                SELECT views_primeras_3h FROM pr_d_test.youtube_shorts_log
                WHERE youtube_video_id = 'negative-legacy-row'
            """).fetchone()[0]
            constraint_exists = conn.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'youtube_shorts_log_views_nonnegative_ck'
                      AND conrelid = 'pr_d_test.youtube_shorts_log'::regclass
                )
            """).fetchone()[0]
        assert legacy_value == -7, "migration preflight must never rewrite existing legacy values"
        assert constraint_exists is False, "failed migration must not leave a partial constraint change"
    finally:
        # Restore the disposable fixture so later tests see the original invariant.
        with psycopg.connect(disposable_database) as conn:
            conn.execute("SET LOCAL session_replication_role = replica")
            conn.execute("""
                DELETE FROM pr_d_test.youtube_shorts_log
                WHERE youtube_video_id = 'negative-legacy-row'
            """)
            conn.execute("""
                ALTER TABLE pr_d_test.youtube_shorts_log
                ADD CONSTRAINT youtube_shorts_log_views_nonnegative_ck
                CHECK (views_primeras_3h IS NULL OR (views_primeras_3h >= 0 AND views_primeras_3h <= 18446744073709551615))
            """)
            conn.commit()

def test_two_concurrent_cas_writers_have_exactly_one_winner(disposable_database):
    row_id = insert_video(disposable_database, "concurrent-video")
    barrier = Barrier(2)
    def writer(metric):
        with psycopg.connect(disposable_database) as conn:
            barrier.wait(timeout=10)
            return conn.execute("""
                SELECT pr_d_test.pr_d_capture_views_once(
                    %s, %s, %s, %s::timestamptz, %s::timestamptz
                )
            """, (row_id, "concurrent-video", metric,
                  "2026-10-30T02:30:00Z", "2026-10-30T05:30:00Z")).fetchone()[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, (100, 200)))
    assert sum(results) == 1
    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute("""
            SELECT views_primeras_3h FROM pr_d_test.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()[0]
    assert stored in (100, 200)


def test_uint64_view_count_round_trips_without_integer_overflow(disposable_database):
    row_id = insert_video(disposable_database, "uint64-video")
    maximum = 18446744073709551615
    with psycopg.connect(disposable_database) as conn:
        captured = conn.execute("""
            SELECT pr_d_test.pr_d_capture_views_once(
                %s, %s, %s::numeric, %s::timestamptz, %s::timestamptz
            )
        """, (row_id, "uint64-video", str(maximum),
              "2026-10-30T02:30:00Z", "2026-10-30T05:30:00Z")).fetchone()[0]
        stored = conn.execute(
            "SELECT views_primeras_3h FROM pr_d_test.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()[0]
    assert captured is True
    assert stored == maximum


def test_view_count_above_uint64_is_rejected_by_constraint(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        conn.execute("SET LOCAL session_replication_role = replica")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("""
                INSERT INTO pr_d_test.youtube_shorts_log
                    (youtube_video_id, views_primeras_3h)
                VALUES ('above-uint64', 18446744073709551616)
            """)


def test_service_role_cannot_bypass_capture_rpc_with_direct_sql(disposable_database):
    row_id = insert_video(disposable_database, "direct-write-denied")
    with psycopg.connect(disposable_database) as conn:
        conn.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="prd_capture_write_requires_rpc"):
            conn.execute(
                "UPDATE pr_d_test.youtube_shorts_log SET views_primeras_3h = 777 WHERE id = %s",
                (row_id,),
            )

    with psycopg.connect(disposable_database) as conn:
        conn.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="prd_capture_write_requires_rpc"):
            conn.execute(
                """
                INSERT INTO pr_d_test.youtube_shorts_log
                    (youtube_video_id, views_primeras_3h)
                VALUES ('direct-insert-denied', 777)
                """
            )

    # The same service role remains allowed to create an unpopulated pending row.
    with psycopg.connect(disposable_database) as conn:
        conn.execute("SET ROLE service_role")
        conn.execute(
            "INSERT INTO pr_d_test.youtube_shorts_log (youtube_video_id) VALUES ('pending-row-allowed')"
        )


def test_capture_writer_isolated_non_login_owner(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        writer = conn.execute(
            "SELECT rolcanlogin, rolinherit, rolbypassrls FROM pg_roles WHERE rolname='pr_d_capture_writer'"
        ).fetchone()
        membership_count = conn.execute(
            """
            SELECT count(*) FROM pg_auth_members
            WHERE roleid = (SELECT oid FROM pg_roles WHERE rolname='pr_d_capture_writer')
               OR member = (SELECT oid FROM pg_roles WHERE rolname='pr_d_capture_writer')
            """
        ).fetchone()[0]
        owner = conn.execute(
            """
            SELECT pg_get_userbyid(proowner)
            FROM pg_proc
            WHERE oid = 'pr_d_test.pr_d_capture_views_once(bigint,text,numeric,timestamptz,timestamptz)'::regprocedure
            """
        ).fetchone()[0]
    assert writer == (False, False, False)
    assert membership_count == 0
    assert owner == "pr_d_capture_writer"


def test_service_role_cannot_truncate_capture_table_and_bypass_row_guards(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        allowed = conn.execute(
            "SELECT has_table_privilege('service_role', 'pr_d_test.youtube_shorts_log', 'TRUNCATE')"
        ).fetchone()[0]
        assert allowed is False
        conn.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("TRUNCATE TABLE pr_d_test.youtube_shorts_log")
