"""Synthetic acceptance tests for isolated PR D v2 inference corrections."""
import unittest
import numpy as np
from labs.pr_d_v2_inference_candidate import (
    fit_logistic_mle_v2, fit_ols_log_positive_hc3_v2, adjust_bh_frozen_family
)

class InferenceCorrections(unittest.TestCase):
    def test_logistic_low_n_is_insufficient_power_not_exception(self):
        x=np.column_stack([np.ones(12),np.arange(12,dtype=float)])
        r=fit_logistic_mle_v2(np.arange(12)%2,x,coefficient_index=1,min_n_eff=30)
        self.assertEqual(r["status"],"INSUFFICIENT_POWER")
        self.assertEqual(r["metrics"]["non_estimability_reason"],"n_eff_below_minimum")
        self.assertIsNone(r["metrics"]["p_empirical"])
        self.assertEqual(r["bh_input_p"],1.0)

    def test_logistic_effect_and_ci_use_same_beta_scale(self):
        x=np.tile(np.arange(10,dtype=float),4)
        y=np.array([0,0,0,1,0,1,1,0,1,1]*4)
        r=fit_logistic_mle_v2(y,np.column_stack([np.ones(40),x]),coefficient_index=1)
        self.assertEqual(r["status"],"ESTIMABLE")
        m=r["metrics"]
        self.assertEqual(m["effect_scale"],m["ci_scale"])
        self.assertLessEqual(m["ci_low"],m["effect_size"])
        self.assertLessEqual(m["effect_size"],m["ci_high"])
        self.assertAlmostEqual(m["odds_ratio"],np.exp(m["effect_size"]))

    def test_family_ii_separates_eligible_n_eff_from_positive_events(self):
        y=np.array([0.,0.,*np.exp(np.linspace(.1,1.5,40))])
        x=np.column_stack([np.ones(42),np.arange(42,dtype=float)])
        r=fit_ols_log_positive_hc3_v2(y,x,coefficient_index=1,min_n_eff=30)
        self.assertEqual(r["status"],"ESTIMABLE")
        self.assertEqual(r["metrics"]["n_eff"],42)
        self.assertEqual(r["metrics"]["n_events"],40)

    def test_family_ii_eligible_n_gate_is_not_positive_count_gate(self):
        y=np.array([0.,0.,*np.exp(np.linspace(.1,1.5,10))])
        x=np.column_stack([np.ones(12),np.arange(12,dtype=float)])
        r=fit_ols_log_positive_hc3_v2(y,x,coefficient_index=1,min_n_eff=30)
        self.assertEqual(r["status"],"INSUFFICIENT_POWER")
        self.assertEqual(r["metrics"]["n_eff"],12)
        self.assertEqual(r["metrics"]["n_events"],10)

    def test_bh_keeps_invalid_member_and_uses_adjustment_p_one(self):
        rows=[{"hypothesis_id":"H1","status":"ESTIMABLE","p_empirical":.01},
              {"hypothesis_id":"H2","status":"INVALID","p_empirical":None},
              {"hypothesis_id":"H3","status":"INSUFFICIENT_POWER","p_empirical":None}]
        out=adjust_bh_frozen_family(rows,frozen_hypothesis_ids=["H1","H2","H3"])
        self.assertEqual(len(out),3)
        self.assertEqual(out[1]["bh_input_p"],1.0)
        self.assertEqual(out[2]["bh_input_p"],1.0)
        self.assertTrue(all(r["family_m"]==3 for r in out))

    def test_bh_rejects_omitted_or_injected_family_members(self):
        rows=[{"hypothesis_id":"H1","status":"ESTIMABLE","p_empirical":.01}]
        with self.assertRaisesRegex(ValueError,"fdr_family_membership_mismatch"):
            adjust_bh_frozen_family(rows,frozen_hypothesis_ids=["H1","H2"])

if __name__=="__main__":
    unittest.main()
