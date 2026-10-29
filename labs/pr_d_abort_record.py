"""Synthetic-only durable operational abort records for PR D E11.

Records are written as separate JSON artifacts outside the scientific result
store. This module does not connect to databases or any production service.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FAILURE_CODES = frozenset({
    "SCHEMA_INCOMPATIBLE", "WINDOW_INVALID", "METHOD_FINGERPRINT_MISMATCH",
    "DATA_READ_FAILURE", "CONNECTION_FAILURE", "UNEXPECTED_ERROR",
})
FAILURE_PHASES = frozenset({
    "preflight", "data_read", "validation", "analysis", "aggregation",
    "persistence", "finalization",
})


def new_execution_id() -> str:
    """Return a fresh opaque ID for one execution attempt."""
    return str(uuid.uuid4())


def build_abort_record(
    *,
    batch_id: str,
    execution_id: str,
    contract_sha256: str,
    manifest_ref: str,
    failure_code: str,
    failure_phase: str,
    diagnostic_ref: str,
    previous_execution_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build an E11 record; invalid/unknown failure labels are rejected."""
    required = {
        "batch_id": batch_id,
        "execution_id": execution_id,
        "contract_sha256": contract_sha256,
        "manifest_ref": manifest_ref,
        "diagnostic_ref": diagnostic_ref,
    }
    if any(not isinstance(v, str) or not v.strip() for v in required.values()):
        raise ValueError("abort_record_required_field_missing")
    if failure_code not in FAILURE_CODES:
        failure_code = "UNEXPECTED_ERROR"
    if failure_phase not in FAILURE_PHASES:
        failure_phase = "finalization"
    if previous_execution_id is not None:
        if not isinstance(previous_execution_id, str) or not previous_execution_id.strip():
            raise ValueError("previous_execution_id_invalid")
        if previous_execution_id == execution_id:
            raise ValueError("retry_execution_id_must_be_new")
    stamp = timestamp or datetime.now(timezone.utc).isoformat()
    if not isinstance(stamp, str) or not stamp.strip():
        raise ValueError("abort_record_timestamp_invalid")
    return {
        "batch_id": batch_id,
        "execution_id": execution_id,
        "previous_execution_id": previous_execution_id,
        "contract_sha256": contract_sha256,
        "manifest_ref": manifest_ref,
        "failure_code": failure_code,
        "failure_phase": failure_phase,
        "status": "ABORTED",
        "completed": False,
        "timestamp": stamp,
        "diagnostic_ref": diagnostic_ref,
    }


def write_abort_record(record: dict[str, Any], artifact_dir: str | Path) -> Path:
    """Atomically persist one JSON record and fsync the file and directory."""
    validate_abort_record(record)
    root = Path(artifact_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"abort-{record['execution_id']}.json"
    fd, temp_name = tempfile.mkstemp(prefix=".abort-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
        dir_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return target


def read_abort_record(path: str | Path) -> dict[str, Any]:
    """Recover and validate a record after the writer has exited."""
    with Path(path).open("r", encoding="utf-8") as stream:
        record = json.load(stream)
    validate_abort_record(record)
    return record


def validate_abort_record(record: dict[str, Any]) -> None:
    """Enforce E11's closed fields and abort invariants."""
    required = (
        "batch_id", "execution_id", "contract_sha256", "manifest_ref",
        "failure_code", "failure_phase", "status", "completed", "timestamp",
        "diagnostic_ref",
    )
    if not isinstance(record, dict) or any(k not in record for k in required):
        raise ValueError("abort_record_required_field_missing")
    if record["status"] != "ABORTED" or record["completed"] is not False:
        raise ValueError("abort_record_completion_invariant_failed")
    if record["failure_code"] not in FAILURE_CODES:
        raise ValueError("abort_record_failure_code_invalid")
    if record["failure_phase"] not in FAILURE_PHASES:
        raise ValueError("abort_record_failure_phase_invalid")
    if not all(isinstance(record[k], str) and record[k].strip() for k in required if k not in {"completed"}):
        raise ValueError("abort_record_required_field_missing")
    previous = record.get("previous_execution_id")
    if previous is not None and previous == record["execution_id"]:
        raise ValueError("retry_execution_id_must_be_new")


def build_retry_abort_record(
    previous: dict[str, Any],
    *,
    execution_id: str,
    failure_code: str,
    failure_phase: str,
    diagnostic_ref: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create a distinct retry record linked to, but never overwriting, its predecessor."""
    validate_abort_record(previous)
    if execution_id == previous["execution_id"]:
        raise ValueError("retry_execution_id_must_be_new")
    return build_abort_record(
        batch_id=previous["batch_id"],
        execution_id=execution_id,
        previous_execution_id=previous["execution_id"],
        contract_sha256=previous["contract_sha256"],
        manifest_ref=previous["manifest_ref"],
        failure_code=failure_code,
        failure_phase=failure_phase,
        diagnostic_ref=diagnostic_ref,
        timestamp=timestamp,
    )
