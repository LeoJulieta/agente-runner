import pytest
from labs.pr_d_family_ii import (
    compute_d_cond,
    compute_d_init,
    fit_ols_log_positive_hc3,
)

@pytest.mark.parametrize("values", [
    (-1, None, 2, 10), (None, 10, -1, None),
    (-1, 10, None, 10), (11, 10, None, 10),
    (1, 0, None, 10), (None, 10, 1, 0),
    (True, 10, None, 10), (None, 10, 1.5, 10),
])
def test_invalid_present_counts_are_rejected_even_with_missing_peers(values):
    with pytest.raises(ValueError):
        compute_d_init(*values)

def test_valid_incomplete_counts_are_insufficient():
    assert compute_d_init(2, 10, None, 10) == {
        "d_init": None, "d_init_reason": "insufficient_data"
    }


@pytest.mark.parametrize("bad_value", [True, "1", "1.5"])
def test_ols_rejects_boolean_and_string_numeric_inputs(bad_value):
    outcomes = [10.0] * 30
    design = [[1.0, float(index)] for index in range(30)]
    outcomes[0] = bad_value
    with pytest.raises(ValueError, match="ols_input_numeric_types_invalid"):
        fit_ols_log_positive_hc3(outcomes, design, coefficient_index=1)


@pytest.mark.parametrize("bad_value", [True, "2"])
def test_ols_rejects_boolean_and_string_predictors(bad_value):
    outcomes = [10.0] * 30
    design = [[1.0, float(index)] for index in range(30)]
    design[0][1] = bad_value
    with pytest.raises(ValueError, match="ols_input_numeric_types_invalid"):
        fit_ols_log_positive_hc3(outcomes, design, coefficient_index=1)


@pytest.mark.parametrize("bad_value", [True, "3"])
def test_conditional_drift_rejects_boolean_and_string_numeric_inputs(bad_value):
    valid = [float(index + 1) for index in range(8)]
    invalid = list(valid)
    invalid[0] = bad_value
    with pytest.raises(ValueError, match="d_cond_input_numeric_types_invalid"):
        compute_d_cond(invalid, valid)


def test_ols_preserves_one_shot_design_row_iterables():
    outcomes = [float(index + 1) for index in range(30)]
    design = (iter((1.0, float(index))) for index in range(30))
    result = fit_ols_log_positive_hc3(outcomes, design, coefficient_index=1)
    assert result["status"] in {"ESTIMABLE", "INSUFFICIENT_POWER"}
    assert result["metrics"]["n_events"] == 30
