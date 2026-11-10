"""Keep raw reference failures and mesh-convergence conclusions reproducible."""
import pytest

from tools.review_cogging_fixtures import metrics, review


def test_distributed_failures_and_refinement_results_from_original_samples():
    rows = review()["rows"]
    assert len(rows) == 3
    assert sum(value == "FAIL" for row in rows for value in row["baseline_femm"]["self_checks"].values()) == 5
    assert all(value == "PASS" for row in rows for value in row["refined_femm"]["self_checks"].values())
    assert [row["native_mesh_study"]["normal"]["vs_refined_femm"]["status"] for row in rows] == ["YELLOW", "PASS", "YELLOW"]
    assert all(row["native_mesh_study"]["very_fine"]["vs_refined_femm"]["status"] == "PASS" for row in rows)
    errors = [row["native_mesh_study"]["very_fine"]["vs_refined_femm"]["peak_to_peak_Nm_error_pct"] for row in rows]
    assert errors == pytest.approx([3.08, 3.27, 4.07], abs=0.005)


@pytest.mark.parametrize("values", [[0.0] * 24, [0.0] * 24 + [float("nan")]])
def test_review_rejects_incomplete_or_nonfinite_waveforms(values):
    with pytest.raises(ValueError, match="25 finite samples"):
        metrics(values)
