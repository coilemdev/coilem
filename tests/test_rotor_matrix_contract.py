"""Matrix input conventions and speed reuse must not silently relabel fields."""
import copy
import subprocess
import sys

import pytest

from backend.geometry_drawer import compute_3phase_slot_ampere_turns_for_rotor_elec
from tools.rotor_matrix_contract import CASES, excitation_parameters, validate_excitation
from tools.rotor_matrix_native import configured
from tools.rotor_matrix_report import speed_scaling


@pytest.mark.parametrize("case", CASES)
def test_registered_excitation_with_zero_and_loaded_currents(case):
    requested, native = configured(case)
    parameters = excitation_parameters(native)
    assert requested.solve_params.current_angle_deg == 0
    assert native.solve_params.symmetry == "full"
    assert native.solve_params.rated_speed_rpm == 3000
    for angle in (0, -0.9375, -19.6875, -360):
        values = compute_3phase_slot_ampere_turns_for_rotor_elec(native, 4*angle)
        e = {"gate": "PASS", "native_rotor_mechanical_deg": angle,
             "native_gamma_deg": 180, "phase_ampere_turns": values}
        validate_excitation(e, angle, parameters)
        bad = copy.deepcopy(e)
        bad["phase_ampere_turns"]["A"] += 0.01
        with pytest.raises(ValueError, match="independent matrix sine"):
            validate_excitation(bad, angle, parameters)


def test_speed_reuse_separates_linear_and_quadratic_terms():
    low = {"hysteresis_W": 0.002, "lamination_eddy_W": 0.003, "total_W": 0.005}
    high = {"hysteresis_W": 0.004, "lamination_eddy_W": 0.012, "total_W": 0.016}
    assert speed_scaling(low, high)["pass"]
    assert not speed_scaling(low, {k: 2*v for k, v in low.items()})["pass"]


def test_independent_sine_rejects_other_winding_and_gamma():
    _, config = configured("ipm-loaded")
    config.solve_params.current_angle_deg = 0
    with pytest.raises(ValueError, match="registered matrix"):
        excitation_parameters(config)


def test_flat_refinement_keeps_geometry_load_and_materials():
    _, a = configured("ipm-loaded")
    _, b = configured("ipm-loaded-finer")
    assert a.model_dump() == b.model_dump()
    assert CASES["ipm-loaded-finer"]["native_base_lc_mm"] < 1.872
    assert CASES["ipm-loaded-finer"]["native_airgap_divisions"] > CASES["ipm-loaded"]["native_airgap_divisions"]


def test_reference_input_adapter_preserves_isolated_backend_namespace():
    subprocess.run([sys.executable, "-c", "import sys; import tools.femm_reference.rotor_matrix_history; "
        "assert 'backend' not in sys.modules, 'Reference adapter imported the native backend'"], check=True)
