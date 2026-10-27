import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from labs.pr_d_manifest import (
    ManifestError,
    find_missing_hypothesis_specs,
    load_and_validate_manifest,
    validate_manifest,
)


class ManifestValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        contract = self.root / "docs" / "PR-D-DESIGN.md"
        contract.parent.mkdir(parents=True)
        contract.write_text("frozen contract fixture\n", encoding="utf-8")
        digest = hashlib.sha256(contract.read_bytes()).hexdigest()
        self.manifest = {
            "schema_version": "pr-d-v2-manifest/1",
            "manifest_version": "test-1",
            "execution_status": "fixture",
            "contract_path": "docs/PR-D-DESIGN.md",
            "contract_sha256": digest,
            "families": [{
                "family_id": "family-a",
                "hypothesis_ids": ["H001", "H002"],
                "m": 2,
                "outcomes": ["views_primeras_3h"],
                "primary_contrasts": ["window_a_vs_window_b"],
                "windows": ["A", "B"],
                "method_version": "pr-d-v2",
            }],
        }
        self.path = self.root / "manifest.json"
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_accepts_valid_manifest_and_frozen_inventory(self):
        result = validate_manifest(
            self.manifest,
            repository_root=self.root,
            expected_hypothesis_ids={"H001", "H002"},
        )
        self.assertEqual(result["families"][0]["m"], 2)

    def test_accepts_suffixed_hypothesis_ids(self):
        bad = json.loads(json.dumps(self.manifest))
        bad["families"][0]["hypothesis_ids"] = ["H041_EXPR", "H042_REEX"]
        bad["families"][0]["m"] = 2
        result = validate_manifest(bad, repository_root=self.root)
        self.assertEqual(result["families"][0]["hypothesis_ids"][0], "H041_EXPR")

    def test_missing_yaml_is_classified_as_individual_failure(self):
        hypotheses = self.root / "labs" / "hypotheses"
        hypotheses.mkdir(parents=True)
        (hypotheses / "H041_EXPR.yaml").write_text("id: H041_EXPR\n", encoding="utf-8")
        missing = find_missing_hypothesis_specs(
            ["H041_EXPR", "H042_REEX"], hypotheses_dir=hypotheses
        )
        self.assertEqual(missing, {"H042_REEX": "hypothesis_spec_missing"})

    def test_missing_yaml_does_not_change_frozen_m(self):
        hypotheses = self.root / "labs" / "hypotheses"
        hypotheses.mkdir(parents=True)
        missing = find_missing_hypothesis_specs(
            ["H001", "H002"], hypotheses_dir=hypotheses
        )
        self.assertEqual(len(self.manifest["families"][0]["hypothesis_ids"]), 2)
        self.assertEqual(self.manifest["families"][0]["m"], 2)
        self.assertEqual(set(missing), {"H001", "H002"})
    def test_rejects_missing_manifest(self):
        with self.assertRaisesRegex(ManifestError, "manifest_missing"):
            load_and_validate_manifest(
                self.root / "absent.json", repository_root=self.root
            )

    def test_rejects_contract_hash_drift(self):
        (self.root / "docs" / "PR-D-DESIGN.md").write_text(
            "changed contract\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ManifestError, "manifest_contract_hash_mismatch"):
            validate_manifest(self.manifest, repository_root=self.root)

    def test_rejects_m_not_equal_to_frozen_family_size(self):
        bad = json.loads(json.dumps(self.manifest))
        bad["families"][0]["m"] = 1
        with self.assertRaisesRegex(ManifestError, "manifest_m_mismatch"):
            validate_manifest(bad, repository_root=self.root)

    def test_rejects_duplicate_hypothesis_across_families(self):
        bad = json.loads(json.dumps(self.manifest))
        second = json.loads(json.dumps(bad["families"][0]))
        second["family_id"] = "family-b"
        second["hypothesis_ids"] = ["H002"]
        second["m"] = 1
        bad["families"].append(second)
        with self.assertRaisesRegex(ManifestError, "hypothesis_appears_in_multiple_families"):
            validate_manifest(bad, repository_root=self.root)

    def test_rejects_checkout_inventory_mismatch(self):
        with self.assertRaisesRegex(ManifestError, "manifest_checkout_inventory_mismatch"):
            validate_manifest(
                self.manifest,
                repository_root=self.root,
                expected_hypothesis_ids={"H001"},
            )

    def test_rejects_corrupt_json(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "manifest_unreadable_or_corrupt"):
            load_and_validate_manifest(self.path, repository_root=self.root)


if __name__ == "__main__":
    unittest.main()
