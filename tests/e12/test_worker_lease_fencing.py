import hashlib
import hmac
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

DATABASE_URL = os.environ["TEST_DATABASE_URL"]
LEASE_MIGRATION = os.environ["E12_LEASE_SQL_PATH"]
ATTESTATION_MIGRATION = os.environ["E12_ATTESTATION_SQL_PATH"]
BATCH_MIGRATION = os.environ["E12_BATCH_SQL_PATH"]
RUN_A = uuid.UUID("11111111-2222-4333-8444-555555555555")
RUN_B = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
PUBLISHED = "2026-10-30T02:30:00Z"
CAPTURED = "2026-10-30T05:30:00.123456Z"
PUBLIC_KEY = "MCowBQYDK2VwAyEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
SIGNATURE = "A" * 86 + "=="
PAYLOAD_SHA = "c" * 64
RESPONSE_SHA = "a" * 64
REQUESTED_IDS_SHA = "b" * 64
COLLECTOR_BUILD = "e12-collector/0.1.0"
HMAC_SECRET = bytes([7]) * 32
KEY_ID = "e12-test-key"


def connect():
    conn = psycopg.connect(DATABASE_URL)
    conn.execute("SET request.jwt.claims = '{\"role\":\"service_role\"}'")
    return conn


def bootstrap():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA extensions")
        conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions")
        conn.execute("DO $role$ BEGIN CREATE ROLE anon NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $role$;")
        conn.execute("DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
        conn.execute("DO $$ BEGIN CREATE ROLE service_role NOLOGIN BYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
        conn.execute("ALTER ROLE service_role BYPASSRLS")
        conn.execute("""
            CREATE TABLE public.youtube_shorts_log (
                id bigint PRIMARY KEY, youtube_video_id text NOT NULL,
                status text NOT NULL DEFAULT 'published', created_at timestamptz NOT NULL DEFAULT now(),
                views_primeras_3h numeric(20,0), hs_al_publicar_al_sync numeric,
                published_at timestamptz, sync_captured_at timestamptz,
                elapsed_seconds_e12 numeric(20,6)
            )
        """)
        conn.execute("""
            ALTER TABLE public.youtube_shorts_log
            ADD CONSTRAINT youtube_shorts_log_sync_capture_window_ck
            CHECK (
                (published_at IS NULL AND sync_captured_at IS NULL AND elapsed_seconds_e12 IS NULL)
                OR (
                    published_at IS NOT NULL AND sync_captured_at IS NOT NULL
                    AND views_primeras_3h IS NOT NULL AND views_primeras_3h >= 0
                    AND elapsed_seconds_e12 = EXTRACT(EPOCH FROM (sync_captured_at - published_at))
                    AND sync_captured_at >= published_at + interval '2 hours 55 minutes'
                    AND sync_captured_at <= published_at + interval '3 hours 5 minutes'
                )
            )
        """)
        conn.execute("""
            INSERT INTO public.youtube_shorts_log(
                id, youtube_video_id, views_primeras_3h, published_at, sync_captured_at, elapsed_seconds_e12
            ) VALUES (3, 'video-legacy', 50, %s, %s, 10800.123456)
        """, (PUBLISHED, CAPTURED))
        conn.execute("ALTER TABLE public.youtube_shorts_log ENABLE ROW LEVEL SECURITY")
        conn.execute("""
            CREATE ROLE pr_d_capture_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS
        """)
        conn.execute("CREATE SCHEMA pr_d_internal AUTHORIZATION pr_d_capture_owner")
        conn.execute("GRANT USAGE ON SCHEMA public TO pr_d_capture_owner")
        conn.execute("GRANT USAGE ON SCHEMA pr_d_internal TO service_role")
        conn.execute("GRANT SELECT ON public.youtube_shorts_log TO pr_d_capture_owner")
        conn.execute("GRANT UPDATE (views_primeras_3h,published_at,sync_captured_at,elapsed_seconds_e12) ON public.youtube_shorts_log TO pr_d_capture_owner")
        conn.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.youtube_shorts_log TO service_role")
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
        conn.execute("INSERT INTO public.youtube_shorts_log(id,youtube_video_id) VALUES (1,'video-1'),(2,'video-2')")
        conn.execute("""
            CREATE FUNCTION pr_d_internal.pr_d_capture_views_once(
              bigint,text,numeric,timestamptz,timestamptz
            ) RETURNS boolean LANGUAGE sql AS 'SELECT false'
        """)
        conn.execute("ALTER FUNCTION pr_d_internal.pr_d_capture_views_once(bigint,text,numeric,timestamptz,timestamptz) OWNER TO pr_d_capture_owner")


def apply_sql_file(path):
    with open(path, encoding="utf-8") as source:
        sql = source.read()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute(sql)


def canonical_payload(run_id, token, row_id, video_id, views="123"):
    values = [
        "e12-observation-attestation/v1",
        KEY_ID,
        str(run_id),
        str(token),
        str(row_id),
        video_id,
        PUBLISHED,
        views,
        CAPTURED,
        RESPONSE_SHA,
        REQUESTED_IDS_SHA,
        COLLECTOR_BUILD,
    ]
    return json.dumps(values, separators=(",", ":"), ensure_ascii=False)


@pytest.fixture(scope="module", autouse=True)
def prepared_database():
    bootstrap()
    apply_sql_file(LEASE_MIGRATION)
    apply_sql_file(ATTESTATION_MIGRATION)
    apply_sql_file(BATCH_MIGRATION)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("""
            INSERT INTO pr_d_internal.e12_collector_key_registry(
                key_id, algorithm, public_key_spki_base64, hmac_secret, status
            ) VALUES (%s, 'Ed25519', %s, %s, 'active')
        """, (KEY_ID, PUBLIC_KEY, HMAC_SECRET))


def claim(run_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM public.pr_d_claim_e12_worker_lease(%s, 90)", (run_id,)).fetchone()


def renew(run_id, token):
    with connect() as conn:
        return conn.execute("SELECT public.pr_d_renew_e12_worker_lease(%s, %s, 90)", (run_id, token)).fetchone()[0]


def release(run_id, token):
    with connect() as conn:
        return conn.execute("SELECT public.pr_d_release_e12_worker_lease(%s, %s)", (run_id, token)).fetchone()[0]


def capture(run_id, token, row_id=1, video_id="video-1", hmac_override=None):
    canonical = canonical_payload(run_id, token, row_id, video_id)
    payload_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    hmac_signature = hmac_override or hmac.new(HMAC_SECRET, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    with connect() as conn:
        return conn.execute(
            """SELECT public.pr_d_capture_views_once(
                %s,%s,123,%s,%s,%s,%s,
                'e12-observation-attestation/v1','Ed25519',%s,%s,%s,%s,%s,%s,%s,%s,%s
            )""",
            (
                row_id, video_id, PUBLISHED, CAPTURED, run_id, token,
                KEY_ID, PUBLIC_KEY, canonical, payload_sha, SIGNATURE,
                hmac_signature, RESPONSE_SHA, REQUESTED_IDS_SHA, COLLECTOR_BUILD,
            ),
        ).fetchone()[0]


def batch_item(run_id, token, row_id, video_id, views="123", hmac_override=None):
    canonical = canonical_payload(run_id, token, row_id, video_id, views)
    payload_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    hmac_signature = hmac_override or hmac.new(
        HMAC_SECRET, canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        "p_row_id": str(row_id),
        "p_youtube_video_id": video_id,
        "p_views": views,
        "p_published_at": PUBLISHED,
        "p_sync_captured_at": CAPTURED,
        "p_run_id": str(run_id),
        "p_fencing_token": str(token),
        "p_attestation_version": "e12-observation-attestation/v1",
        "p_attestation_algorithm": "Ed25519",
        "p_collector_key_id": KEY_ID,
        "p_collector_public_key_spki_base64": PUBLIC_KEY,
        "p_collector_payload_canonical": canonical,
        "p_collector_payload_sha256": payload_sha,
        "p_collector_signature": SIGNATURE,
        "p_collector_hmac_signature": hmac_signature,
        "p_collector_response_sha256": RESPONSE_SHA,
        "p_collector_requested_ids_sha256": REQUESTED_IDS_SHA,
        "p_collector_build": COLLECTOR_BUILD,
    }


def capture_batch(items):
    with connect() as conn:
        return conn.execute(
            "SELECT public.pr_d_capture_views_batch(%s::jsonb)",
            (json.dumps(items),),
        ).fetchone()[0]


def test_batch_cas_preserves_per_row_attestation_and_first_write_wins():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE pr_d_internal.e12_worker_lease")
    lease = claim(RUN_A)
    token = int(lease[1])
    items = [
        batch_item(RUN_A, token, 1, "video-1", "123"),
        batch_item(RUN_A, token, 2, "video-2", "456"),
        batch_item(RUN_A, token, 1, "video-1", "789"),
    ]
    result = capture_batch(items)
    assert result == [
        {"row_id": "1", "captured": True},
        {"row_id": "2", "captured": True},
        {"row_id": "1", "captured": False},
    ]
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, youtube_video_id, views_primeras_3h, collector_hmac_signature "
            "FROM public.youtube_shorts_log WHERE id IN (1,2) ORDER BY id"
        ).fetchall()
        assert rows[0][:3] == (1, "video-1", 123)
        assert rows[1][:3] == (2, "video-2", 456)
        assert rows[0][3] == items[0]["p_collector_hmac_signature"]
        assert rows[1][3] == items[1]["p_collector_hmac_signature"]


def test_batch_sql_exception_rolls_back_all_prior_items():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE pr_d_internal.e12_worker_lease")
    lease = claim(RUN_A)
    token = int(lease[1])
    items = [
        batch_item(RUN_A, token, 1, "video-1"),
        batch_item(RUN_A, token, 2, "video-2"),
    ]
    items[1]["p_row_id"] = "not-a-bigint"
    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        capture_batch(items)
    with connect() as conn:
        values = conn.execute(
            "SELECT views_primeras_3h FROM public.youtube_shorts_log WHERE id IN (1,2) ORDER BY id"
        ).fetchall()
        assert values == [(None,), (None,)]


def test_batch_bad_hmac_is_rejected_per_item_without_weakening_valid_item():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE pr_d_internal.e12_worker_lease")
    lease = claim(RUN_A)
    token = int(lease[1])
    items = [
        batch_item(RUN_A, token, 1, "video-1"),
        batch_item(RUN_A, token, 2, "video-2", hmac_override="0" * 64),
    ]
    assert capture_batch(items) == [
        {"row_id": "1", "captured": True},
        {"row_id": "2", "captured": False},
    ]


def test_concurrent_batch_calls_have_exactly_one_first_write_winner():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE pr_d_internal.e12_worker_lease")
    lease = claim(RUN_A)
    token = int(lease[1])
    item = batch_item(RUN_A, token, 1, "video-1")
    barrier = threading.Barrier(2)

    def contender():
        barrier.wait(timeout=10)
        return capture_batch([item])[0]["captured"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: contender(), range(2)))
    assert sorted(outcomes) == [False, True]


def test_batch_missing_required_field_is_rejected():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE pr_d_internal.e12_worker_lease")
    lease = claim(RUN_A)
    item = batch_item(RUN_A, int(lease[1]), 1, "video-1")
    del item["p_collector_hmac_signature"]
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        capture_batch([item])
    with connect() as conn:
        assert conn.execute(
            "SELECT views_primeras_3h FROM public.youtube_shorts_log WHERE id=1"
        ).fetchone()[0] is None


def test_batch_rejects_empty_oversized_and_non_array_payloads():
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        capture_batch([])
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        capture_batch([{}] * 51)
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with connect() as conn:
            conn.execute("SELECT public.pr_d_capture_views_batch(%s::jsonb)", ('{"not":"array"}',))


def test_batch_stale_fencing_token_cannot_write_after_takeover():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE pr_d_internal.e12_worker_lease")
    first = claim(RUN_A)
    old_token = int(first[1])
    assert release(RUN_A, old_token) is True
    second = claim(RUN_B)
    new_token = int(second[1])
    assert new_token == old_token + 1
    assert capture_batch([batch_item(RUN_A, old_token, 1, "video-1")]) == [
        {"row_id": "1", "captured": False}
    ]
    assert capture_batch([batch_item(RUN_B, new_token, 1, "video-1")]) == [
        {"row_id": "1", "captured": True}
    ]


def test_legacy_capture_row_survives_attestation_upgrade():
    with connect() as conn:
        row = conn.execute("""
            SELECT views_primeras_3h, published_at, sync_captured_at,
                   collector_signature, collector_hmac_signature
            FROM public.youtube_shorts_log WHERE id=3
        """).fetchone()
        assert row[0] == 50
        assert row[1] is not None and row[2] is not None
        assert row[3] is None and row[4] is None

    with connect() as conn:
        conn.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE public.youtube_shorts_log SET youtube_video_id='rewritten' WHERE id=3")
        conn.rollback()


def test_exclusive_claim_renew_takeover_and_stale_owner_rejection():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE pr_d_internal.e12_worker_lease")
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
    assert capture(RUN_A, token_a) is False
    assert capture(RUN_B, token_b) is True

    with connect() as conn:
        row = conn.execute("""
            SELECT views_primeras_3h, e12_capture_run_id, e12_fencing_token,
                   collector_key_id, collector_signature, collector_payload_canonical, collector_payload_sha256
            FROM public.youtube_shorts_log WHERE id=1
        """).fetchone()
        assert row == (123, RUN_B, token_b, KEY_ID, SIGNATURE, canonical_payload(RUN_B, token_b, 1, "video-1"), hashlib.sha256(canonical_payload(RUN_B, token_b, 1, "video-1").encode("utf-8")).hexdigest())


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
        current = conn.execute(
            "SELECT owner_run_id, fencing_token FROM pr_d_internal.e12_worker_lease WHERE singleton"
        ).fetchone()
        assert current is not None
        conn.execute("UPDATE pr_d_internal.e12_worker_lease SET lease_expires_at = clock_timestamp() - interval '1 second'")
    assert renew(current[0], current[1]) is False
    takeover = claim(RUN_A if current[0] != RUN_A else RUN_B)
    assert takeover[0] is True
    assert int(takeover[1]) == int(current[1]) + 1


def test_revoked_key_is_rejected_and_attestation_columns_are_immutable():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE pr_d_internal.e12_worker_lease")
        conn.execute("UPDATE pr_d_internal.e12_collector_key_registry SET status='revoked', revoked_at=clock_timestamp() WHERE key_id=%s", (KEY_ID,))
    lease = claim(RUN_A)
    token = int(lease[1])
    assert capture(RUN_A, token, row_id=2, video_id="video-2") is False

    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("UPDATE pr_d_internal.e12_collector_key_registry SET status='active', revoked_at=NULL WHERE key_id=%s", (KEY_ID,))
    assert capture(RUN_A, token, row_id=2, video_id="video-2", hmac_override="0" * 64) is False
    assert capture(RUN_A, token, row_id=2, video_id="video-2") is True

    with connect() as conn:
        conn.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT hmac_secret FROM pr_d_internal.e12_collector_key_registry")
        conn.rollback()
        conn.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE public.youtube_shorts_log SET collector_signature=%s WHERE id=2", ("B" * 86 + "==",))
        conn.rollback()
        conn.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM public.youtube_shorts_log WHERE id=2")


def test_old_unfenced_and_unattested_cas_signatures_are_removed():
    with psycopg.connect(DATABASE_URL) as conn:
        old_five = conn.execute("""
            SELECT to_regprocedure(
              'public.pr_d_capture_views_once(bigint,text,numeric,timestamp with time zone,timestamp with time zone)'
            )
        """).fetchone()[0]
        old_seven = conn.execute("""
            SELECT to_regprocedure(
              'public.pr_d_capture_views_once(bigint,text,numeric,timestamp with time zone,timestamp with time zone,uuid,bigint)'
            )
        """).fetchone()[0]
        assert old_five is None
        assert old_seven is None
