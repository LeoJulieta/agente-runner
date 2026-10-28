"""Synthetic acceptance tests for E11 abort-artifact durability and retry identity."""
import json
import tempfile
import unittest
from pathlib import Path

from labs.pr_d_abort_record import (
    build_abort_record,
    build_retry_abort_record,
    read_abort_record,
    write_abort_record,
)


class PRDAbortRecordE11Tests(unittest.TestCase):
    def make_record(self, execution_id="exec-a"):
        return build_abort_record(
            batch_id="batch-fixture-1",
            execution_id=execution_id,
            contract_sha256="synthetic-contract-sha256",
            manifest_ref="fixture-commit-or-sha",
            failure_code="DATA_READ_FAILURE",
            failure_phase="data_read",
            diagnostic_ref="ci-artifact://synthetic/log-a",
            timestamp="2026-01-01T00:00:00+00:00",
        )

    def test_abort_record_is_recoverable_after_writer_returns(self):
        with tempfile.TemporaryDirectory() as temp:
            record = self.make_record()
            path = write_abort_record(record, temp)
            self.assertTrue(path.is_file())
            recovered = read_abort_record(path)
            self.assertEqual(recovered, record)
            self.assertEqual(recovered["status"], "ABORTED")
            self.assertIs(recovered["completed"], False)
            self.assertEqual(recovered["failure_code"], "DATA_READ_FAILURE")
            self.assertEqual(recovered["failure_phase"], "data_read")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), record)

    def test_retry_gets_new_execution_id_and_preserves_prior_abort(self):
        with tempfile.TemporaryDirectory() as temp:
            first = self.make_record("exec-a")
            first_path = write_abort_record(first, temp)
            retry = build_retry_abort_record(
                first,
                execution_id="exec-b",
                failure_code="UNEXPECTED_ERROR",
                failure_phase="analysis",
                diagnostic_ref="ci-artifact://synthetic/log-b",
                timestamp="2026-01-01T00:01:00+00:00",
            )
            retry_path = write_abort_record(retry, temp)
            self.assertNotEqual(first["execution_id"], retry["execution_id"])
            self.assertEqual(retry["previous_execution_id"], first["execution_id"])
            self.assertEqual(read_abort_record(first_path), first)
            self.assertEqual(read_abort_record(retry_path), retry)
            self.assertEqual(len(list(Path(temp).glob("abort-*.json"))), 2)
            self.assertIs(read_abort_record(first_path)["completed"], False)

    def test_same_execution_id_retry_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "retry_execution_id_must_be_new"):
            build_retry_abort_record(
                self.make_record("exec-a"),
                execution_id="exec-a",
                failure_code="DATA_READ_FAILURE",
                failure_phase="data_read",
                diagnostic_ref="ci-artifact://synthetic/log-b",
            )

    def test_unknown_failure_labels_map_to_closed_catalog(self):
        record = build_abort_record(
            batch_id="batch-fixture-1", execution_id="exec-x",
            contract_sha256="synthetic-contract-sha256",
            manifest_ref="fixture-commit-or-sha",
            failure_code="unregistered-secret-or-dynamic-label",
            failure_phase="unregistered-phase",
            diagnostic_ref="ci-artifact://synthetic/log-x",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        self.assertEqual(record["failure_code"], "UNEXPECTED_ERROR")
        self.assertEqual(record["failure_phase"], "finalization")

    def test_incomplete_or_success_marked_abort_record_is_rejected(self):
        record = self.make_record()
        invalid = dict(record)
        invalid["completed"] = True
        with self.assertRaisesRegex(ValueError, "abort_record_completion_invariant_failed"):
            write_abort_record(invalid, tempfile.gettempdir())


if __name__ == "__main__":
    unittest.main()
