"""Disposable PostgreSQL compatibility tests for the audited production shape.

This test is destructive only inside an explicitly opted-in, local, disposable
database. It fails closed for every other connection configuration.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import os

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "tests/fixtures/pr_d_youtube_shorts_log_schema.sql"
MIGRATION = ROOT / "supabase/migrations/20261112160000_pr_d_sync_capture_provenance_candidate.sql"
DATABASE_URL = os.getenv("DATABASE_URL")
DISPOSABLE_OPT_IN = os.getenv("PR_D_DISPOSABLE_DATABASE") == "1"
ALLOWED_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _assert_disposable_database(dsn: str) -> None:
    """Reject arbitrary DSNs before opening a connection or executing DDL."""
    try:
        params = conninfo_to_dict(dsn)
    except (TypeError, ValueError):
        pytest.fail("unsafe_database_url: DATABASE_URL is not valid libpq conninfo")

    host = params.get("host", "")
    hosts = host.split(",") if host else []
    database = params.get("dbname", "")
    user = params.get("user", "")

    if not DISPOSABLE_OPT_IN:
        pytest.fail("unsafe_database_url: PR_D_DISPOSABLE_DATABASE=1 is required")
    if not hosts or any(item.strip().lower() not in ALLOWED_LOCAL_HOSTS for item in hosts):
        pytest.fail("unsafe_database_url: only loopback PostgreSQL hosts are allowed")
    if database != "prd_test" or user != "prd_test":
        pytest.fail("unsafe_database_url: database/user must both be prd_test")


@pytest.fixture(scope="module")
def disposable_database():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL absent; integration test requires disposable PostgreSQL")
    _assert_disposable_database(DATABASE_URL)

    # Deliberately no CASCADE: unexpected dependencies must stop the test,
    # never be removed as a side effect.
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("DROP TABLE IF EXISTS public.youtube_shorts_log")
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.execute(MIGRATION.read_text(encoding="utf-8"))
    yield DATABASE_URL


def insert_video(dsn, video_id="yt-fixture-001"):
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "INSERT INTO public.youtube_shorts_log (youtube_video_id) VALUES (%s) RETURNING id",
            (video_id,),
        ).fetchone()
        return row[0]


def test_schema_uses_bigint_row_id_and_text_youtube_identifier(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        columns = dict(conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'youtube_shorts_log'
            """
        ).fetchall())
    assert columns["id"] == "bigint"
    assert columns["youtube_video_id"] == "text"
    assert columns["published_at"] == "timestamp with time zone"
    assert columns["sync_captured_at"] == "timestamp with time zone"


def test_legacy_metric_row_without_new_timestamps_remains_valid(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        row_id = conn.execute(
            """
            INSERT INTO public.youtube_shorts_log
                (youtube_video_id, views_primeras_3h)
            VALUES ('legacy-fixture', 123)
            RETURNING id
            """
        ).fetchone()[0]
        stored = conn.execute(
            """
            SELECT views_primeras_3h, published_at, sync_captured_at
            FROM public.youtube_shorts_log WHERE id = %s
            """,
            (row_id,),
        ).fetchone()
    assert stored == (123, None, None)


def test_cas_binds_bigint_id_and_youtube_video_id_and_writes_once(disposable_database):
    row_id = insert_video(disposable_database)
    sql = """
        UPDATE public.youtube_shorts_log
        SET views_primeras_3h = %s,
            published_at = %s,
            sync_captured_at = %s
        WHERE id = %s
          AND youtube_video_id = %s
          AND views_primeras_3h IS NULL
          AND published_at IS NULL
          AND sync_captured_at IS NULL
        RETURNING id
    """
    values = (456, "2026-10-30T02:30:00Z", "2026-10-30T06:30:00Z", row_id, "yt-fixture-001")
    with psycopg.connect(disposable_database) as conn:
        first = conn.execute(sql, values).fetchone()
        second = conn.execute(sql, values).fetchone()
        stored = conn.execute(
            "SELECT views_primeras_3h, published_at, sync_captured_at FROM public.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()
    assert first == (row_id,)
    assert second is None
    assert stored[0] == 456


def test_wrong_youtube_id_cannot_update_another_row(disposable_database):
    row_id = insert_video(disposable_database, "correct-video")
    with psycopg.connect(disposable_database) as conn:
        updated = conn.execute(
            """
            UPDATE public.youtube_shorts_log
            SET views_primeras_3h = 9,
                published_at = '2026-10-30T02:30:00Z',
                sync_captured_at = '2026-10-30T06:30:00Z'
            WHERE id = %s AND youtube_video_id = 'wrong-video'
              AND views_primeras_3h IS NULL
            RETURNING id
            """,
            (row_id,),
        ).fetchone()
    assert updated is None


def test_database_rejects_capture_outside_three_to_six_hour_window(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                """
                INSERT INTO public.youtube_shorts_log
                    (youtube_video_id, views_primeras_3h, published_at, sync_captured_at)
                VALUES (
                    'out-of-window',
                    10,
                    '2026-10-30T02:30:00Z',
                    '2026-10-30T08:30:01Z'
                )
                """
            )


def test_two_concurrent_cas_writers_have_exactly_one_winner(disposable_database):
    row_id = insert_video(disposable_database, "concurrent-video")
    barrier = Barrier(2)
    sql = """
        UPDATE public.youtube_shorts_log
        SET views_primeras_3h = %s,
            published_at = '2026-10-30T02:30:00Z',
            sync_captured_at = '2026-10-30T06:30:00Z'
        WHERE id = %s
          AND youtube_video_id = 'concurrent-video'
          AND views_primeras_3h IS NULL
          AND published_at IS NULL
          AND sync_captured_at IS NULL
        RETURNING id
    """

    def writer(metric):
        with psycopg.connect(disposable_database) as conn:
            barrier.wait(timeout=10)
            result = conn.execute(sql, (metric, row_id)).fetchone()
            return result is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, (100, 200)))
    assert sum(results) == 1
    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute(
            "SELECT views_primeras_3h FROM public.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()[0]
    assert stored in (100, 200)
