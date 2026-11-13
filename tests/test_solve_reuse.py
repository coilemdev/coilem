"""Work a solve can skip on later operating points: no-load reports and profile flushes."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import client as coilem
from backend import solve_profile, solver
from backend.client import _solve

pytestmark = pytest.mark.pr

SPM_FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"


@pytest.fixture(autouse=True)
def empty_caches():
    solver.clear_per_angle_gmsh_mesh_cache()
    yield
    solver.clear_per_angle_gmsh_mesh_cache()


def test_a_no_load_report_is_reused_until_its_mesh_is_replaced() -> None:
    solver._angle_mesh_cache_store("scope", 0, {"mesh": {"nodes_mm": [[0.0, 0.0]]}})
    key = ("scope", 0, "settings")
    report = {"results": {"flux_linkage_a_wb": 0.25}, "solve_info": {"convergence": {"iterations": 3}}, "field_plot": {"az": [1.0]}}

    solver._noload_report_cache_store(key, report)
    reused = solver._noload_report_cache_get(key)

    assert reused == report and reused is not report
    assert reused["field_plot"] is report["field_plot"]  # field arrays are shared, not copied
    reused["results"]["flux_linkage_a_wb"] = 1.0
    reused["solve_info"]["convergence"]["iterations"] = 0
    again = solver._noload_report_cache_get(key)
    assert again["results"]["flux_linkage_a_wb"] == 0.25 and again["solve_info"]["convergence"]["iterations"] == 3

    # Only a report whose mesh is cached is kept; a new mesh for the angle drops it.
    solver._noload_report_cache_store(("scope", 1, "settings"), report)
    assert solver._noload_report_cache_get(("scope", 1, "settings")) is None
    solver._angle_mesh_cache_store("scope", 0, {"mesh": {"nodes_mm": [[1.0, 0.0]]}})
    assert solver._noload_report_cache_get(key) is None


def _no_load_config(**params):
    body = coilem.build_request(coilem.Motor.load(SPM_FIXTURE), coilem.OperatingPoint(**params), analyses=["torque", "back_emf"])
    return solver._config_with_phase_current(_solve.prepared_config(body), 0.0)


def test_no_load_settings_ignore_the_operating_current_but_not_the_rest() -> None:
    reference = solver._noload_reuse_signature(_no_load_config(current_A=20, current_angle_deg=30))
    assert solver._noload_reuse_signature(_no_load_config(current_A=45, current_angle_deg=60)) == reference
    assert solver._noload_reuse_signature(_no_load_config(current_A=20, current_angle_deg=30, magnet_temperature_C=120)) != reference
    assert solver._noload_reuse_signature(_no_load_config(current_A=20, current_angle_deg=30, speed_rpm=6000)) != reference


class _CountingHandle:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.flushes = 0

    def write(self, text: str) -> int:
        return self.inner.write(text)

    def flush(self) -> None:
        self.flushes += 1
        self.inner.flush()


def test_the_solving_process_flushes_its_profile_records_once_when_it_collects(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("COILEM_SOLVE_PROFILE", raising=False)
    monkeypatch.setattr(solve_profile, "_handle", None)
    monkeypatch.setattr(solve_profile, "_started_at", None)

    solve_profile.begin()
    solve_profile.record("solve: one position", 0.5)
    handle = _CountingHandle(solve_profile._handle)
    monkeypatch.setattr(solve_profile, "_handle", handle)
    solve_profile.record("solve: one position", 0.25)
    assert handle.flushes == 0  # buffered while this process's solve is open
    summary = solve_profile.finish(None)
    assert handle.flushes == 1
    assert [row["count"] for row in summary["stages"] if row["stage"] == "solve: one position"] == [2]
    solve_profile.record("worker stage", 0.1)  # no solve open: flushed at once, as a worker's are
    assert handle.flushes == 2
    handle.inner.close()
