"""Strict validation helpers for the PR D v2 frozen manifest.

This module is deliberately not wired into the production workflow yet.
The manifest inventory and acceptance tests must be reviewed before activation.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "pr-d-v2-manifest/1"
CONTRACT_PATH = "docs/PR-D-DESIGN.md"
HYPOTHESIS_ID = re.compile(r"^H[0-9]{3,}$")


class ManifestError(ValueError):
    """The batch manifest cannot safely define a frozen family."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(
    manifest: Any,
    *,
    repository_root: str | Path = ".",
    expected_hypothesis_ids: set[str] | None = None,
) -> dict:
    """Validate structure, contract hash, family m, and optional checkout inventory.

    Raises ManifestError for every structural or unknown condition. This is a
    pure validation step: it never accesses Supabase and never writes data.
    """
    if not isinstance(manifest, dict):
        raise ManifestError("manifest_not_object")

    required = {
        "schema_version", "manifest_version", "contract_path",
        "contract_sha256", "families",
    }
    if set(manifest) != required:
        raise ManifestError("manifest_top_level_fields_invalid")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ManifestError("manifest_schema_version_invalid")
    if not isinstance(manifest["manifest_version"], str) or not manifest["manifest_version"].strip():
        raise ManifestError("manifest_version_invalid")
    if manifest["contract_path"] != CONTRACT_PATH:
        raise ManifestError("manifest_contract_path_invalid")

    expected_hash = manifest["contract_sha256"]
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
        raise ManifestError("manifest_contract_hash_invalid")
    contract = Path(repository_root) / CONTRACT_PATH
    if not contract.is_file():
        raise ManifestError("contract_file_missing")
    if sha256_file(contract) != expected_hash:
        raise ManifestError("manifest_contract_hash_mismatch")

    families = manifest["families"]
    if not isinstance(families, list) or not families:
        raise ManifestError("manifest_families_invalid")

    family_ids: set[str] = set()
    all_ids: list[str] = []
    required_family = {
        "family_id", "hypothesis_ids", "m", "outcomes",
        "primary_contrasts", "windows", "method_version",
    }
    for family in families:
        if not isinstance(family, dict) or set(family) != required_family:
            raise ManifestError("manifest_family_fields_invalid")
        family_id = family["family_id"]
        if not isinstance(family_id, str) or not family_id.strip() or family_id in family_ids:
            raise ManifestError("manifest_family_id_invalid_or_duplicate")
        family_ids.add(family_id)

        ids = family["hypothesis_ids"]
        if not isinstance(ids, list) or not ids:
            raise ManifestError("manifest_hypothesis_ids_invalid")
        if any(not isinstance(item, str) or not HYPOTHESIS_ID.fullmatch(item) for item in ids):
            raise ManifestError("manifest_hypothesis_id_invalid")
        if len(ids) != len(set(ids)):
            raise ManifestError("manifest_hypothesis_id_duplicate")
        if type(family["m"]) is not int or family["m"] != len(ids):
            raise ManifestError("manifest_m_mismatch")
        for key in ("outcomes", "primary_contrasts", "windows"):
            values = family[key]
            if not isinstance(values, list) or not values or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ManifestError(f"manifest_{key}_invalid")
        if not isinstance(family["method_version"], str) or not family["method_version"].strip():
            raise ManifestError("manifest_method_version_invalid")
        all_ids.extend(ids)

    if len(all_ids) != len(set(all_ids)):
        raise ManifestError("hypothesis_appears_in_multiple_families")
    if expected_hypothesis_ids is not None and set(all_ids) != expected_hypothesis_ids:
        raise ManifestError("manifest_checkout_inventory_mismatch")
    return manifest


def load_and_validate_manifest(
    manifest_path: str | Path,
    *,
    repository_root: str | Path = ".",
    expected_hypothesis_ids: set[str] | None = None,
) -> dict:
    """Read JSON and fail closed on missing, malformed, or invalid content."""
    path = Path(manifest_path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise ManifestError("manifest_missing") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest_unreadable_or_corrupt") from exc
    return validate_manifest(
        payload,
        repository_root=repository_root,
        expected_hypothesis_ids=expected_hypothesis_ids,
    )
