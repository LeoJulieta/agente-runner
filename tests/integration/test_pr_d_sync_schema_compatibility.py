"""PostgreSQL integration tests for the E12 CAS boundary.

The DSN is validated before connecting. All DDL/DML is confined to a dedicated
loopback database and schema. The test starts from the audited legacy int4
column type and exercises both permitted and forbidden write paths.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
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
PUBLISHED_AT = "2026-10-30T02:30:00Z"
CAPTURED_AT = "2026-10-30T05:30:00Z"
SERVICE_CLAIMS = '{"role":"service_role"}'


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


def _as_service_role(conn):
    conn.execute("SET ROLE service_role")
    conn.execute(
        "SELECT set_config('request.jwt.claims', %s, true)",
        (SERVICE_CLAIMS,),
    )


@pytest.fixture(scope="module")
def disposable_database():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL absent; disposable PostgreSQL is required")
    _assert_disposable_database(DATABASE_URL)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        # This workflow runs in a newly created disposable PostgreSQL service.
        # Clean only the named test schema and the dedicated test-only role.
        conn.execute("DROP SCHEMA IF EXISTS pr_d_test CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS pr_d_internal CASCADE")
        conn.execute("DROP ROLE IF EXISTS pr_d_capture_owner")
        conn.execute("CREATE SCHEMA pr_d_test")
        conn.execute(SCHEMA.read_text(encoding="utf-8"))

        # Insert a historical int4 row BEFORE the candidate migration. Its
        # metric and pre-existing elapsed value must survive widening unchanged.
        conn.execute("""
            INSERT INTO pr_d_test.youtube_shorts_log
                (youtube_video_id, views_primeras_3h, hs_al_publicar_al_sync)
            VALUES ('legacy-fixture', 123, 2.75)
        """)

        migration = MIGRATION.read_text(encoding="utf-8")
        migration = migration.replace(
            "public.youtube_shorts_log", "pr_d_test.youtube_shorts_log"
        )
        migration = migration.replace(
            "public.pr_d_capture_views_once", "pr_d_test.pr_d_capture_views_once"
        )
        migration = migration.replace(
            "public.pr_d_guard_capture_fields", "pr_d_test.pr_d_guard_capture_fields"
        )
        migration = migration.replace(
            "ON SCHEMA public TO pr_d_capture_owner",
            "ON SCHEMA pr_d_test TO pr_d_capture_owner",
        )
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
    published_at=PUBLISHED_AT,
    captured_at=CAPTURED_AT,
):
    with psycopg.connect(dsn) as conn:
        _as_service_role(conn)
        return conn.execute(
            """
            SELECT pr_d_test.pr_d_capture_views_once(
                %s, %s, %s, %s::timestamptz, %s::timestamptz
            )
            """,
            (row_id, video_id, views, published_at, captured_at),
        ).fetchone()[0]


def test_schema_widens_legacy_int4_and_preserves_existing_rows(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        columns = dict(conn.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'pr_d_test' AND table_name = 'youtube_shorts_log'
        """).fetchall())
        stored = conn.execute("""
            SELECT views_primeras_3h, hs_al_publicar_al_sync,
                   published_at, sync_captured_at
            FROM pr_d_test.youtube_shorts_log
            WHERE youtube_video_id = 'legacy-fixture'
        """).fetchone()

    assert columns["id"] == "bigint"
    assert columns["youtube_video_id"] == "text"
    assert columns["views_primeras_3h"] == "numeric"
    assert columns["hs_al_publicar_al_sync"] == "numeric"
    assert columns["published_at"] == "timestamp with time zone"
    assert columns["sync_captured_at"] == "timestamp with time zone"
    assert stored == (123, Decimal("2.75"), None, None)


def test_internal_capture_role_is_least_privilege_and_rpc_is_service_only(disposable_database):
    public_signature = (
        "pr_d_test.pr_d_capture_views_once("
        "bigint,text,numeric,timestamp with time zone,timestamp with time zone)"
    )
    internal_signature = (
        "pr_d_internal.pr_d_capture_views_once("
        "bigint,text,numeric,timestamp with time zone,timestamp with time zone)"
    )
    with psycopg.connect(disposable_database) as conn:
        public_privileges = conn.execute(
            """
            SELECT
                has_function_privilege('service_role', %s, 'EXECUTE'),
                has_function_privilege('anon', %s, 'EXECUTE'),
                has_function_privilege('authenticated', %s, 'EXECUTE')
            """,
            (public_signature, public_signature, public_signature),
        ).fetchone()
        internal_privileges = conn.execute(
            """
            SELECT
                has_function_privilege('service_role', %s, 'EXECUTE'),
                has_function_privilege('anon', %s, 'EXECUTE'),
                has_function_privilege('authenticated', %s, 'EXECUTE')
            """,
            (internal_signature, internal_signature, internal_signature),
        ).fetchone()
        role = conn.execute("""
            SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                   rolinherit, rolreplication, rolbypassrls
            FROM pg_roles WHERE rolname = 'pr_d_capture_owner'
        """).fetchone()
        membership_count = conn.execute("""
            SELECT count(*) FROM pg_auth_members
            WHERE roleid = (SELECT oid FROM pg_roles WHERE rolname = 'pr_d_capture_owner')
               OR member = (SELECT oid FROM pg_roles WHERE rolname = 'pr_d_capture_owner')
        """).fetchone()[0]
        helper_privileges = conn.execute("""
            SELECT
                has_column_privilege('pr_d_capture_owner',
                    'pr_d_test.youtube_shorts_log', 'views_primeras_3h', 'UPDATE'),
                has_column_privilege('pr_d_capture_owner',
                    'pr_d_test.youtube_shorts_log', 'hs_al_publicar_al_sync', 'UPDATE'),
                has_table_privilege('pr_d_capture_owner',
                    'pr_d_test.youtube_shorts_log', 'DELETE'),
                has_table_privilege('pr_d_capture_owner',
                    'pr_d_test.youtube_shorts_log', 'INSERT')
        """).fetchone()

    assert public_privileges == (True, False, False)
    assert internal_privileges == (True, False, False)
    assert role == (False, False, False, False, False, False, False)
    assert membership_count == 0
    assert helper_privileges == (True, True, False, False)


def test_service_role_cannot_bypass_cas_but_can_update_unrelated_columns(disposable_database):
    row_id = insert_video(disposable_database, "direct-update-bypass")
    with psycopg.connect(disposable_database) as conn:
        _as_service_role(conn)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="prd_capture_write_denied"):
            conn.execute("""
                UPDATE pr_d_test.youtube_shorts_log
                   SET views_primeras_3h = 99,
                       published_at = %s,
                       sync_captured_at = %s,
                       hs_al_publicar_al_sync = 3
                 WHERE id = %s
            """, (PUBLISHED_AT, CAPTURED_AT, row_id))

    # The guard is narrow: unrelated metadata updates keep working.
    with psycopg.connect(disposable_database) as conn:
        _as_service_role(conn)
        changed = conn.execute("""
            UPDATE pr_d_test.youtube_shorts_log
               SET status = 'published'
             WHERE id = %s
            RETURNING status
        """, (row_id,)).fetchone()[0]
        assert changed == "published"

    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute("""
            SELECT views_primeras_3h, published_at, sync_captured_at,
                   hs_al_publicar_al_sync
            FROM pr_d_test.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()
    assert stored == (None, None, None, None)


def test_service_role_cannot_insert_forged_capture_or_delete_captured_row(disposable_database):
    with psycopg.connect(disposable_database) as conn:
        _as_service_role(conn)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="prd_capture_write_denied"):
            conn.execute("""
                INSERT INTO pr_d_test.youtube_shorts_log
                    (youtube_video_id, views_primeras_3h, published_at,
                     sync_captured_at, hs_al_publicar_al_sync)
                VALUES ('forged-insert', 7, %s, %s, 3)
            """, (PUBLISHED_AT, CAPTURED_AT))

    row_id = insert_video(disposable_database, "captured-delete-bypass")
    assert _cas(disposable_database, row_id, "captured-delete-bypass", 456) is True

    with psycopg.connect(disposable_database) as conn:
        _as_service_role(conn)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="prd_capture_delete_denied"):
            conn.execute(
                "DELETE FROM pr_d_test.youtube_shorts_log WHERE id = %s",
                (row_id,),
            )

    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute(
            "SELECT views_primeras_3h FROM pr_d_test.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()[0]
    assert stored == 456


def test_captured_video_identity_cannot_be_reassigned(disposable_database):
    row_id = insert_video(disposable_database, "identity-original")
    assert _cas(disposable_database, row_id, "identity-original", 101) is True
    with psycopg.connect(disposable_database) as conn:
        _as_service_role(conn)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="prd_capture_write_denied"):
            conn.execute("""
                UPDATE pr_d_test.youtube_shorts_log
                   SET youtube_video_id = 'identity-reassigned'
                 WHERE id = %s
            """, (row_id,))


def test_capture_rpc_is_service_role_only_and_stores_exact_elapsed(disposable_database):
    row_id = insert_video(disposable_database, "service-role-video")
    assert _cas(disposable_database, row_id, "service-role-video", 321) is True

    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute("""
            SELECT views_primeras_3h, published_at, sync_captured_at,
                   hs_al_publicar_al_sync
            FROM pr_d_test.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()
    assert stored == (
        321,
        __import__("datetime").datetime.fromisoformat("2026-10-30T02:30:00+00:00"),
        __import__("datetime").datetime.fromisoformat("2026-10-30T05:30:00+00:00"),
        Decimal("3.0000000000000000"),
    )


def test_migration_cas_is_reusable_and_first_write_wins(disposable_database):
    row_id = insert_video(disposable_database)
    assert _cas(disposable_database, row_id, "yt-fixture-001", 456) is True
    assert _cas(disposable_database, row_id, "yt-fixture-001", 999) is False
    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute("""
            SELECT views_primeras_3h, hs_al_publicar_al_sync
            FROM pr_d_test.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()
    assert stored == (456, Decimal("3.0000000000000000"))


def test_wrong_youtube_id_cannot_claim_row(disposable_database):
    row_id = insert_video(disposable_database, "correct-video")
    assert _cas(disposable_database, row_id, "wrong-video", 9) is False


def test_window_boundaries_are_inclusive_and_outside_values_are_rejected(disposable_database):
    lower_id = insert_video(disposable_database, "lower-boundary")
    upper_id = insert_video(disposable_database, "upper-boundary")
    below_id = insert_video(disposable_database, "below-lower-boundary")
    above_id = insert_video(disposable_database, "above-upper-boundary")

    assert _cas(
        disposable_database, lower_id, "lower-boundary", 10,
        "2026-10-30T02:30:00Z", "2026-10-30T05:25:00Z",
    ) is True
    assert _cas(
        disposable_database, upper_id, "upper-boundary", 11,
        "2026-10-30T02:30:00Z", "2026-10-30T05:35:00Z",
    ) is True
    assert _cas(
        disposable_database, below_id, "below-lower-boundary", 12,
        "2026-10-30T02:30:00Z", "2026-10-30T05:24:59.999999Z",
    ) is False
    assert _cas(
        disposable_database, above_id, "above-upper-boundary", 13,
        "2026-10-30T02:30:00Z", "2026-10-30T05:35:00.000001Z",
    ) is False


def test_negative_view_count_cannot_be_captured_or_inserted(disposable_database):
    row_id = insert_video(disposable_database, "negative-cas")
    assert _cas(disposable_database, row_id, "negative-cas", -1) is False

    with psycopg.connect(disposable_database) as conn:
        _as_service_role(conn)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="prd_capture_write_denied"):
            conn.execute("""
                INSERT INTO pr_d_test.youtube_shorts_log
                    (youtube_video_id, views_primeras_3h)
                VALUES ('negative-direct-insert', -1)
            """)


def test_migration_preflight_refuses_negative_legacy_values_without_rewriting(disposable_database):
    migration = MIGRATION.read_text(encoding="utf-8")
    migration = migration.replace(
        "public.youtube_shorts_log", "pr_d_test.youtube_shorts_log"
    )
    migration = migration.replace(
        "public.pr_d_capture_views_once", "pr_d_test.pr_d_capture_views_once"
    )
    migration = migration.replace(
        "public.pr_d_guard_capture_fields", "pr_d_test.pr_d_guard_capture_fields"
    )
    migration = migration.replace(
        "ON SCHEMA public TO pr_d_capture_owner",
        "ON SCHEMA pr_d_test TO pr_d_capture_owner",
    )

    # Simulate a pre-existing legacy-invalid row created before the guard
    # existed. This is a disposable-only trigger disable, never production.
    with psycopg.connect(disposable_database) as conn:
        conn.execute("""
            ALTER TABLE pr_d_test.youtube_shorts_log
            DROP CONSTRAINT youtube_shorts_log_views_nonnegative_ck
        """)
        conn.execute("""
            ALTER TABLE pr_d_test.youtube_shorts_log
            DISABLE TRIGGER youtube_shorts_log_pr_d_capture_guard
        """)
        conn.execute("""
            INSERT INTO pr_d_test.youtube_shorts_log
                (youtube_video_id, views_primeras_3h)
            VALUES ('negative-legacy-row', -7)
        """)
        conn.execute("""
            ALTER TABLE pr_d_test.youtube_shorts_log
            ENABLE TRIGGER youtube_shorts_log_pr_d_capture_guard
        """)

    with psycopg.connect(disposable_database, autocommit=True) as conn:
        with pytest.raises(
            psycopg.errors.CheckViolation,
            match="prd_sync_migration_preflight_failed",
        ):
            conn.execute(migration)

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
    assert legacy_value == -7, "preflight must never rewrite invalid legacy values"
    assert constraint_exists is False, "failed preflight must not leave a partial constraint change"

    # Remove only the intentionally invalid disposable fixture row.
    with psycopg.connect(disposable_database) as conn:
        conn.execute("""
            ALTER TABLE pr_d_test.youtube_shorts_log
            DISABLE TRIGGER youtube_shorts_log_pr_d_capture_guard
        """)
        conn.execute("""
            DELETE FROM pr_d_test.youtube_shorts_log
            WHERE youtube_video_id = 'negative-legacy-row'
        """)
        conn.execute("""
            ALTER TABLE pr_d_test.youtube_shorts_log
            ENABLE TRIGGER youtube_shorts_log_pr_d_capture_guard
        """)
        conn.execute("""
            ALTER TABLE pr_d_test.youtube_shorts_log
            ADD CONSTRAINT youtube_shorts_log_views_nonnegative_ck
            CHECK (
                views_primeras_3h IS NULL OR (
                    views_primeras_3h >= 0
                    AND views_primeras_3h <= 18446744073709551615
                    AND views_primeras_3h = trunc(views_primeras_3h)
                )
            )
        """)


def test_two_concurrent_cas_writers_have_exactly_one_winner(disposable_database):
    row_id = insert_video(disposable_database, "concurrent-video")
    barrier = Barrier(2)

    def writer(metric):
        with psycopg.connect(disposable_database) as conn:
            _as_service_role(conn)
            barrier.wait(timeout=10)
            return conn.execute("""
                SELECT pr_d_test.pr_d_capture_views_once(
                    %s, %s, %s, %s::timestamptz, %s::timestamptz
                )
            """, (
                row_id, "concurrent-video", metric,
                PUBLISHED_AT, CAPTURED_AT,
            )).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, (100, 200)))
    assert sum(results) == 1
    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute("""
            SELECT views_primeras_3h, hs_al_publicar_al_sync
            FROM pr_d_test.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()
    assert stored[0] in (100, 200)
    assert stored[1] == Decimal("3.0000000000000000")


def test_uint64_view_count_round_trips_without_integer_overflow(disposable_database):
    row_id = insert_video(disposable_database, "uint64-video")
    maximum = 18446744073709551615
    assert _cas(disposable_database, row_id, "uint64-video", str(maximum)) is True
    with psycopg.connect(disposable_database) as conn:
        stored = conn.execute(
            "SELECT views_primeras_3h FROM pr_d_test.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()[0]
    assert stored == maximum


def test_view_count_above_uint64_is_rejected_by_database_constraint(disposable_database):
    row_id = insert_video(disposable_database, "above-uint64")
    with psycopg.connect(disposable_database) as conn:
        conn.execute("SET ROLE pr_d_capture_owner")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("""
                UPDATE pr_d_test.youtube_shorts_log
                   SET views_primeras_3h = 18446744073709551616,
                       published_at = %s,
                       sync_captured_at = %s,
                       hs_al_publicar_al_sync = 3
                 WHERE id = %s
            """, (PUBLISHED_AT, CAPTURED_AT, row_id))
