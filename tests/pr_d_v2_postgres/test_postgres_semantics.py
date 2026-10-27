"""Real PostgreSQL semantics tests using only an ephemeral CI service.

These tests prove PostgreSQL transaction/constraint behavior. They DO NOT invoke
lab_engine.py or the Supabase REST client and therefore do not prove app-level
atomicity, idempotency, or concurrency until an RPC/adapter is integrated.
"""
import os
import unittest
import uuid

import psycopg


DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "TEST_DATABASE_URL is only configured in isolated CI")
class PostgreSQLSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "prd_test_" + uuid.uuid4().hex[:12]
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute(f'CREATE SCHEMA "{cls.schema}"')
            conn.execute(
                f'''CREATE TABLE "{cls.schema}".runs (
                    id bigserial PRIMARY KEY,
                    run_key text NOT NULL,
                    record_type text NOT NULL,
                    payload jsonb NOT NULL,
                    UNIQUE (run_key, record_type)
                )'''
            )

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{cls.schema}" CASCADE')

    def setUp(self):
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute(f'DELETE FROM "{self.schema}".runs')

    def count_rows(self):
        with psycopg.connect(DATABASE_URL) as conn:
            return conn.execute(
                f'SELECT count(*) FROM "{self.schema}".runs'
            ).fetchone()[0]

    def test_one_transaction_rolls_back_baseline_when_evidence_fails(self):
        with self.assertRaisesRegex(RuntimeError, "injected evidence failure"):
            with psycopg.connect(DATABASE_URL) as conn:
                conn.execute(
                    f'INSERT INTO "{self.schema}".runs (run_key, record_type, payload) '
                    "VALUES (%s, %s, %s)",
                    ("run-atomic", "baseline", '{"value": 1}'),
                )
                raise RuntimeError("injected evidence failure")
        self.assertEqual(self.count_rows(), 0)

    def test_separate_committed_writes_can_leave_orphan_baseline(self):
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute(
                f'INSERT INTO "{self.schema}".runs (run_key, record_type, payload) '
                "VALUES (%s, %s, %s)",
                ("run-split", "baseline", '{"value": 1}'),
            )
        with self.assertRaisesRegex(RuntimeError, "injected evidence failure"):
            raise RuntimeError("injected evidence failure")
        with psycopg.connect(DATABASE_URL) as conn:
            rows = conn.execute(
                f'SELECT record_type FROM "{self.schema}".runs WHERE run_key = %s',
                ("run-split",),
            ).fetchall()
        self.assertEqual(rows, [("baseline",)])

    def test_unique_constraint_rejects_duplicate_baseline_key(self):
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute(
                f'INSERT INTO "{self.schema}".runs (run_key, record_type, payload) '
                "VALUES (%s, %s, %s)",
                ("run-idempotency", "baseline", '{"value": 1}'),
            )
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with psycopg.connect(DATABASE_URL) as conn:
                conn.execute(
                    f'INSERT INTO "{self.schema}".runs (run_key, record_type, payload) '
                    "VALUES (%s, %s, %s)",
                    ("run-idempotency", "baseline", '{"value": 1}'),
                )
        self.assertEqual(self.count_rows(), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
