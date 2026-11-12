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
        conn.execute(migration)
    yield DATABASE_URL


def insert_video(dsn, video_id="yt-fixture-001"):
    with psycopg.connect(dsn) as conn:
        return conn.execute(
            "INSERT INTO pr_d_test.youtube_shorts_log (youtube_video_id) VALUES (%s) RETURNING id",
            (video_id,),
        ).fetchone()[0]


def _cas(dsn, row_id, video_id, views):
    with psycopg.connect(dsn) as conn:
        return conn.execute("""
            SELECT pr_d_test.pr_d_capture_views_once(
                %s, %s, %s, %s::timestamptz, %s::timestamptz
            )
        """, (row_id, video_id, views, "2026-10-30T02:30:00Z", "2026-10-30T06:30:00Z")).fetchone()[0]


def test_schema_types_and_legacy_rows(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        columns = dict(conn.execute("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'pr_d_test' AND table_name = 'youtube_shorts_log'
        """).fetchall())
        row_id = conn.execute("""
            INSERT INTO pr_d_test.youtube_shorts_log (youtube_video_id, views_primeras_3h)
            VALUES ('legacy-fixture', 123) RETURNING id
        """).fetchone()[0]
        stored = conn.execute("""
            SELECT views_primeras_3h, published_at, sync_captured_at
            FROM pr_d_test.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()
    assert columns["id"] == "bigint"
    assert columns["youtube_video_id"] == "text"
    assert columns["published_at"] == "timestamp with time zone"
    assert columns["sync_captured_at"] == "timestamp with time zone"
    assert stored == (123, None, None)


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


def test_check_rejects_out_of_window_and_timestamps_without_metric(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("""
                INSERT INTO pr_d_test.youtube_shorts_log
                    (youtube_video_id, views_primeras_3h, published_at, sync_captured_at)
                VALUES ('out-of-window', 10, '2026-10-30T02:30:00Z', '2026-10-30T08:30:01Z')
            """)
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("""
                INSERT INTO pr_d_test.youtube_shorts_log
                    (youtube_video_id, published_at, sync_captured_at)
                VALUES ('metric-missing', '2026-10-30T02:30:00Z', '2026-10-30T06:30:00Z')
            """)


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
                  "2026-10-30T02:30:00Z", "2026-10-30T06:30:00Z")).fetchone()[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, (100, 200)))
    assert sum(results) == 1
    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute("""
            SELECT views_primeras_3h FROM pr_d_test.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()[0]
    assert stored in (100, 200)
