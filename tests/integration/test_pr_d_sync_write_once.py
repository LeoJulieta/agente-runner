"""Disposable PostgreSQL tests for first-valid-write-wins capture semantics.

The CI service is a local ephemeral PostgreSQL instance. No Supabase URL,
credentials, production rows, or persistent database are used.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import psycopg


TABLE = "public.prd_sync_capture_fixture"


def connect():
    return psycopg.connect(os.environ["TEST_DATABASE_URL"])


def setup_database():
    with connect() as conn:
        conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
        conn.execute(f"""
            CREATE TABLE {TABLE} (
                video_id text PRIMARY KEY,
                published_at timestamptz NOT NULL,
                views_primeras_3h integer NULL,
                sync_captured_at timestamptz NULL,
                CHECK (
                    (views_primeras_3h IS NULL AND sync_captured_at IS NULL)
                    OR
                    (views_primeras_3h IS NOT NULL AND sync_captured_at IS NOT NULL)
                )
            )
        """)
        conn.execute(
            f"INSERT INTO {TABLE} (video_id, published_at) VALUES (%s, %s)",
            ("fixture-video", datetime(2026, 10, 30, 2, 30, tzinfo=timezone.utc)),
        )


def conditional_write(video_id, views, captured_at, barrier=None):
    if barrier is not None:
        barrier.wait(timeout=10)
    with connect() as conn:
        row = conn.execute(
            f"""
            UPDATE {TABLE}
            SET views_primeras_3h = %s, sync_captured_at = %s
            WHERE video_id = %s
              AND views_primeras_3h IS NULL
              AND %s >= published_at + INTERVAL '3 hours'
              AND %s <= published_at + INTERVAL '6 hours'
            RETURNING video_id
            """,
            (views, captured_at, video_id, captured_at, captured_at),
        ).fetchone()
        return row is not None


def read_capture(video_id):
    with connect() as conn:
        return conn.execute(
            f"SELECT views_primeras_3h, sync_captured_at FROM {TABLE} WHERE video_id=%s",
            (video_id,),
        ).fetchone()


def test_sync_t32_first_confirmed_atomic_write_wins_and_later_write_cannot_overwrite():
    setup_database()
    first_time = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
    second_time = datetime(2026, 10, 30, 6, 30, tzinfo=timezone.utc)

    assert conditional_write("fixture-video", 101, first_time) is True
    assert conditional_write("fixture-video", 999, second_time) is False
    assert read_capture("fixture-video") == (101, first_time)


def test_sync_t33_concurrent_writers_produce_exactly_one_winner_and_one_atomic_pair():
    setup_database()
    barrier = Barrier(2)
    first_time = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
    second_time = datetime(2026, 10, 30, 6, 15, tzinfo=timezone.utc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda args: conditional_write("fixture-video", args[0], args[1], barrier),
            [(201, first_time), (202, second_time)],
        ))

    assert sorted(results) == [False, True]
    stored = read_capture("fixture-video")
    assert stored in {(201, first_time), (202, second_time)}


def test_sync_t34_database_guard_rejects_out_of_window_capture_even_when_unwritten():
    setup_database()
    too_early = datetime(2026, 10, 30, 5, 29, 59, tzinfo=timezone.utc)
    too_late = datetime(2026, 10, 30, 8, 30, 1, tzinfo=timezone.utc)

    assert conditional_write("fixture-video", 301, too_early) is False
    assert conditional_write("fixture-video", 302, too_late) is False
    assert read_capture("fixture-video") == (None, None)
