"""Fail-closed Gate 0 for the legacy single-hypothesis workflow."""
from __future__ import annotations

import argparse
import re
import sys

from labs.pr_d_manifest import ManifestError, load_and_validate_manifest

HYPOTHESIS_ID = re.compile(r"^H[0-9]{3,}(?:_[A-Z0-9]+)*$")


def validate_single_run(manifest: dict, hypothesis_id: str) -> None:
    """Allow a single run only after explicit approval and frozen-ID membership."""
    if not isinstance(hypothesis_id, str) or not HYPOTHESIS_ID.fullmatch(hypothesis_id):
        raise ValueError("hypothesis_id_invalid")
    if manifest.get("execution_status") != "approved":
        raise PermissionError("manifest_not_approved")
    frozen_ids = {
        hypothesis_id
        for family in manifest.get("families", [])
        for hypothesis_id in family.get("hypothesis_ids", [])
    }
    if hypothesis_id not in frozen_ids:
        raise PermissionError("hypothesis_not_in_frozen_manifest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="docs/manifest.json")
    parser.add_argument("--hypothesis-id", required=True)
    args = parser.parse_args(argv)
    try:
        manifest = load_and_validate_manifest(args.manifest)
        validate_single_run(manifest, args.hypothesis_id)
    except (ManifestError, ValueError, PermissionError) as exc:
        print(f"PR-D-SINGLE-RUN-GATE: BLOCKED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            f"PR-D-SINGLE-RUN-GATE: BLOCKED: unexpected error ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    print(f"PR-D-SINGLE-RUN-GATE: VALID: hypothesis_id={args.hypothesis_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
