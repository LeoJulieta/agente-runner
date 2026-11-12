import pytest
from labs.pr_d_family_ii import compute_d_init

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
