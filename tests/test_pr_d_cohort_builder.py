"""Synthetic deterministic tests for the isolated PR D cohort builder."""
import unittest

from labs.pr_d_cohort_builder import (
    MISSING_EXCLUDE,
    MISSING_RAISE,
    CohortInputError,
    SyncWindow,
    build_preregistered_cohort,
)
from labs.pr_d_family_ii import fit_ols_log_positive_hc3


def inclusive_example_window(missing_policy=MISSING_EXCLUDE):
    # Synthetic configuration only; not a contractual decision on endpoints.
    return SyncWindow(
        lower_seconds=3 * 60 * 60,
        upper_seconds=6 * 60 * 60,
        lower_inclusive=True,
        upper_inclusive=True,
        missing_policy=missing_policy,
    )


def candidate(candidate_id, elapsed, outcome, predictor):
    return {
        "candidate_id": candidate_id,
        "sync_elapsed_seconds": elapsed,
        "outcome": outcome,
        "predictor": predictor,
    }


class PRDCohortBuilderTests(unittest.TestCase):
    def build(self, rows, **kwargs):
        return build_preregistered_cohort(
            rows,
            candidate_id_field="candidate_id",
            outcome_field="outcome",
            predictor_fields=("predictor",),
            sync_elapsed_seconds_field="sync_elapsed_seconds",
            sync_window=inclusive_example_window(),
            preregistered_masks={},
            **kwargs,
        )

    def test_inclusive_synthetic_boundaries_and_null_are_explicitly_classified(self):
        rows = [
            candidate("before", 2 * 60 * 60 + 59 * 60 + 59, 9, 0),
            candidate("lower", 3 * 60 * 60, 0, 1),
            candidate("upper", 6 * 60 * 60, 5, 2),
            candidate("after", 6 * 60 * 60 + 1, 4, 3),
            candidate("missing", None, 7, 4),
        ]
        result = self.build(rows)

        self.assertEqual(result["candidate_ids"], ["before", "lower", "upper", "after", "missing"])
        self.assertEqual(result["eligible_mask"], [False, True, True, False, False])
        self.assertEqual(result["eligible_candidate_ids"], ["lower", "upper"])
        self.assertEqual(
            result["excluded"],
            [
                {"candidate_id": "before", "reasons": ["outside_sync_window"]},
                {"candidate_id": "after", "reasons": ["outside_sync_window"]},
                {"candidate_id": "missing", "reasons": ["missing_sync_elapsed"]},
            ],
        )
        self.assertEqual(result["n_total"], 5)
        self.assertEqual(result["n_eff"], 2)
        self.assertEqual(result["n_events"], 1)
        self.assertEqual(len(result["outcomes"]), len(result["design_matrix"]))
        self.assertEqual(len(result["design_matrix"]), len(result["eligible_mask"]))
        self.assertEqual(result["outcomes"], [9.0, 0.0, 5.0, 4.0, 7.0])
        self.assertEqual(result["design_matrix"], [[0.0], [1.0], [2.0], [3.0], [4.0]])
        self.assertEqual(
            result["filter_provenance"]["temporal_anchor"],
            "externally_preregistered_not_inferred",
        )

    def test_exclusive_endpoint_configuration_excludes_exact_boundaries(self):
        window = SyncWindow(
            lower_seconds=10800,
            upper_seconds=21600,
            lower_inclusive=False,
            upper_inclusive=False,
            missing_policy=MISSING_EXCLUDE,
        )
        result = build_preregistered_cohort(
            [candidate("at-lower", 10800, 1, 0), candidate("inside", 10801, 1, 1),
             candidate("at-upper", 21600, 1, 2)],
            candidate_id_field="candidate_id",
            outcome_field="outcome",
            predictor_fields=("predictor",),
            sync_elapsed_seconds_field="sync_elapsed_seconds",
            sync_window=window,
            preregistered_masks={},
        )
        self.assertEqual(result["eligible_mask"], [False, True, False])
        self.assertEqual((result["n_total"], result["n_eff"], result["n_events"]), (3, 1, 1))

    def test_missing_elapsed_policy_can_fail_closed(self):
        with self.assertRaisesRegex(CohortInputError, "sync_elapsed_missing"):
            build_preregistered_cohort(
                [candidate("null-time", None, 1, 0)],
                candidate_id_field="candidate_id",
                outcome_field="outcome",
                predictor_fields=("predictor",),
                sync_elapsed_seconds_field="sync_elapsed_seconds",
                sync_window=inclusive_example_window(MISSING_RAISE),
                preregistered_masks={},
            )

    def test_all_preregistered_masks_are_combined_before_n_eff(self):
        rows = [
            candidate("a", 10800, 1, 0),
            candidate("b", 12000, 0, 1),
            candidate("c", 21600, 2, 2),
        ]
        result = build_preregistered_cohort(
            rows,
            candidate_id_field="candidate_id",
            outcome_field="outcome",
            predictor_fields=("predictor",),
            sync_elapsed_seconds_field="sync_elapsed_seconds",
            sync_window=inclusive_example_window(),
            preregistered_masks={"declared_population": [True, False, True]},
        )
        self.assertEqual(result["eligible_mask"], [True, False, True])
        self.assertEqual(result["excluded"], [
            {"candidate_id": "b", "reasons": ["preregistered_filter:declared_population"]}
        ])
        self.assertEqual(result["n_total"], 3)
        self.assertEqual(result["n_eff"], 2)
        self.assertEqual(result["n_events"], 2)
        self.assertEqual(
            result["filter_provenance"]["additional_preregistered_filters"],
            ["declared_population"],
        )

    def test_misaligned_preregistered_mask_is_rejected(self):
        with self.assertRaisesRegex(CohortInputError, "preregistered_filter_mask_alignment_invalid"):
            build_preregistered_cohort(
                [candidate("a", 10800, 1, 0), candidate("b", 12000, 2, 1)],
                candidate_id_field="candidate_id",
                outcome_field="outcome",
                predictor_fields=("predictor",),
                sync_elapsed_seconds_field="sync_elapsed_seconds",
                sync_window=inclusive_example_window(),
                preregistered_masks={"population": [True]},
            )

    def test_n_eff_and_n_events_are_counted_at_contractual_floor_edges(self):
        rows = [candidate(f"row-{i}", 10800, 1 if i < 5 else 0, i) for i in range(31)]
        below = build_preregistered_cohort(
            rows,
            candidate_id_field="candidate_id",
            outcome_field="outcome",
            predictor_fields=("predictor",),
            sync_elapsed_seconds_field="sync_elapsed_seconds",
            sync_window=inclusive_example_window(),
            preregistered_masks={"candidate_window": [True] * 29 + [False, False]},
        )
        at_floor = build_preregistered_cohort(
            rows,
            candidate_id_field="candidate_id",
            outcome_field="outcome",
            predictor_fields=("predictor",),
            sync_elapsed_seconds_field="sync_elapsed_seconds",
            sync_window=inclusive_example_window(),
            preregistered_masks={"candidate_window": [True] * 30 + [False]},
        )
        self.assertEqual((below["n_total"], below["n_eff"], below["n_events"]), (31, 29, 5))
        self.assertEqual((at_floor["n_total"], at_floor["n_eff"], at_floor["n_events"]), (31, 30, 5))

    def test_cohort_counts_and_mask_feed_family_ii_without_reordering(self):
        rows = [
            candidate("excluded-a", 10799, 8, 0),
            candidate("eligible-zero", 10800, 0, 1),
            candidate("eligible-positive", 10801, 3, 2),
            candidate("excluded-b", 21601, 4, 3),
        ]
        cohort = self.build(rows)
        result = fit_ols_log_positive_hc3(
            cohort["outcomes"],
            cohort["design_matrix"],
            coefficient_index=0,
            eligible_mask=cohort["eligible_mask"],
            min_n_eff=30,
        )
        self.assertEqual(result["status"], "INSUFFICIENT_POWER")
        self.assertEqual(result["metrics"]["n_total"], cohort["n_total"])
        self.assertEqual(result["metrics"]["n_eff"], cohort["n_eff"])
        self.assertEqual(result["metrics"]["n_events"], cohort["n_events"])
        self.assertEqual((cohort["n_total"], cohort["n_eff"], cohort["n_events"]), (4, 2, 1))

    def test_duplicate_candidate_identity_is_rejected(self):
        with self.assertRaisesRegex(CohortInputError, "candidate_id_duplicate"):
            self.build([
                candidate("same", 10800, 1, 0),
                candidate("same", 10801, 1, 1),
            ])

    def test_nonfinite_elapsed_and_implicit_endpoint_policy_are_rejected(self):
        with self.assertRaisesRegex(CohortInputError, "sync_elapsed_invalid"):
            self.build([candidate("bad", float("nan"), 1, 0)])
        with self.assertRaisesRegex(CohortInputError, "sync_window_inclusivity_must_be_explicit_boolean"):
            SyncWindow(
                lower_seconds=10800,
                upper_seconds=21600,
                lower_inclusive=1,
                upper_inclusive=True,
                missing_policy=MISSING_EXCLUDE,
            )


if __name__ == "__main__":
    unittest.main()
