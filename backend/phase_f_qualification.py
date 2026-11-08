"""Windows-only engineering qualification for the reviewed Phase F scope.

This evidence is separate from the A-D record. Only mean torque and phase
Back-EMF are covered; other performance outputs keep their existing status.
Missing, changed or unverifiable public evidence fails closed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re

from backend.models import MotorConfig
from backend.reference_models import reference_model
from backend.rotor_layout import is_outer_rotor, outer_rotor_airgap_mm

RECORD_FILE = "benchmarks/records/phase-f/windows-x86_64.json"
SUITE_FILE = "benchmarks/abcd-v1.8/benchmark_spec.json"
BUNDLE_DIR = "benchmarks/reference-baselines/phase-f-reviewed-20261108"
# Pin the reviewed public packet, independently of its editable JSON contents.
RECORD_SHA256 = "9ef239d60943b991fa9fc392dee20a673afba76b232353d5ac2569bb819d45b0"
REFERENCE = "https://github.com/coilemdev/coilem/blob/main/docs/VALIDATION.md#outer-rotor-motors"
REVIEW_STATUS = "REVIEWED_FOR_WINDOWS_ENGINEERING_PARITY"

CASE_IDS = frozenset({
    "spm_outer_14p12s_drone__baseline",
    "spm_outer_14p12s_drone__high_current",
    "spm_outer_14p12s_drone__tight_airgap",
    "spm_outer_14p12s_drone__angle30",
    "spm_outer_14p12s_drone_noload__baseline",
    "spm_outer_12p9s_micro__baseline",
    "spm_outer_12p9s_micro_noload__baseline",
    "spm_outer_10p12s_single_layer__baseline",
    "spm_outer_28p24s_multirotor__baseline",
    "spm_outer_30p27s_hub__baseline",
})
GATE_IDS = frozenset({"mean_torque", "bemf_fundamental", "bemf_peak", "torque_method", "native_mesh", "angle_grids"})
# (slots, poles, layers): (conductors per slot, maximum peak phase current).
FAMILIES = {(12, 14, 2): (12, 15.0), (9, 12, 2): (14, 5.0), (12, 10, 1): (20, 15.0),
            (24, 28, 2): (10, 10.0), (27, 30, 2): (12, 20.0)}
CAVEATS = [
    "Windows x86_64 engineering scope only; geometry variations within the stated size and gap ranges were not each independently benchmarked.",
    "Phase F qualifies mean torque and Back-EMF only; it supplies no qualification for cogging, losses, efficiency, "
    "d/q parameters, inductance or magnet-temperature derating. Independent analytical qualifications keep their own scope.",
    "The two-dimensional model does not include bell end effects or magnet overhang.",
]


def _platform_key():
    from backend.benchmark_suite.record import platform_key

    return platform_key()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _verified_evidence():
    from backend.benchmark_suite.contract import DATA_ROOT
    from backend.benchmark_suite.record import check_physics
    from backend.benchmark_suite.references import load_bundle, load_suite
    from backend.resources import data_file

    try:
        if not re.fullmatch(r"[0-9a-f]{64}", RECORD_SHA256):
            return None
        raw = data_file(RECORD_FILE).read_bytes()
        if _digest(raw) != RECORD_SHA256:
            return None
        record = json.loads(raw)
        if (record["schema"] != "coilem.benchmark_record/v1" or record["platform"] != "windows-x86_64"
                or not re.fullmatch(r"[0-9a-f]{40}", record["measured_commit"])
                or not isinstance(record["source"], str) or not record["source"].startswith("benchmarks/")):
            return None
        scope = record["qualification_scope"]
        if scope["platform"] != "windows-x86_64" or scope["phase"] != "F" or set(scope["outputs"]) != {"mean_torque", "back_emf"}:
            return None
        if set(record["cases"]) != CASE_IDS:
            return None
        for case in record["cases"].values():
            if case["phase"] != "F" or case["status"] != "PASS" or set(case["gates"]) != GATE_IDS or set(case["gates"].values()) != {"PASS"}:
                return None
            values = case["values"]
            if set(values) != {"mean_torque_Nm", "back_emf_fundamental_V", "back_emf_peak_V"} or not all(_finite(v) for v in values.values()):
                return None
        suite_raw = data_file(SUITE_FILE).read_bytes()
        if _digest(suite_raw) != record["suite_sha256"]:
            return None
        spec = load_suite(DATA_ROOT / SUITE_FILE)
        manifest_raw = data_file(f"{BUNDLE_DIR}/manifest.json").read_bytes()
        if _digest(manifest_raw) != record["reference_manifest_sha256"]:
            return None
        manifest, references, bundle_identity = load_bundle(DATA_ROOT / BUNDLE_DIR, spec)
        if (manifest["schema"] != "coilem.frozen_reference_bundle/v2" or manifest["validation_status"] != REVIEW_STATUS
                or record["reference_id"] != manifest["reference_id"]
                or record["reference_bundle_sha256"] != bundle_identity or set(references) != CASE_IDS):
            return None
        if check_physics(record)["status"] != "MATCH":
            return None
        return record
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return None


def _scope_reason(config: MotorConfig):
    if not is_outer_rotor(config) or config.topology != "SPM" or reference_model(config) is not None:
        return "the design is not a generic outer-rotor SPM motor"
    winding, rotor, materials, params = config.winding, config.rotor, config.materials, config.solve_params
    family = FAMILIES.get((config.stator.slot_count, rotor.pole_count, winding.layers))
    if family is None or winding.type != "concentrated":
        return "the slot/pole/layer winding family was not measured"
    turns, current_limit = family
    if winding.parallel_paths != 1 or winding.turns_per_coil != turns or winding.coil_span is not None:
        return "the winding turns, parallel paths or coil span differ from the measured family"
    if not 18 <= config.stator.OD_mm <= 100 or not .25 - 1e-12 <= outer_rotor_airgap_mm(config) <= .5 + 1e-12:
        return "the stator diameter or air gap is outside the measured engineering range"
    from backend.geometry import validate_geometry

    if rotor.flux_barrier_count or rotor.barrier_widths_mm or validate_geometry(config):
        return "the geometry is invalid or uses an unmeasured rotor form"
    if (materials.stator_steel != "M350-50A" or materials.rotor_steel != "M350-50A"
            or materials.magnet_grade != "N42" or materials.conductor != "copper" or materials.custom_steels):
        return "the material selection differs from the measured M350-50A/N42/copper model"
    if params is None:
        return "the measured solve settings are absent"
    if (params.excitation_mode != "sinusoidal" or params.current_amplitude_convention != "peak"
            or params.phase_connection != "wye" or not 0 <= params.current_amplitude_A <= current_limit
            or not 0 <= params.current_angle_deg <= 30):
        return "the excitation is outside the measured family current and angle range"
    if params.rated_speed_rpm != 3000 or params.magnet_temperature_C not in (None, 20.0) or params.winding_temperature_C not in (None, 20.0):
        return "the speed or material temperature is outside the measured room-temperature scope"
    if (params.mesh_density != "normal" or params.mesh_build != "precise" or params.mesh_source != "native"
            or params.mesher != "gmsh" or params.rotor_rotation_model != "remesh_per_step"
            or params.corner_refinement or params.slot_sidewall_refinement or params.linear_steel_mu_rel is not None):
        return "the mesh or steel solve differs from the measured normal Precise model"
    if params.solve_quality != "custom" or params.rotor_sweep_range_deg != 360 or params.rotor_step_deg != 7.5:
        return "the solve does not use the measured custom full-cycle plan with its 7.5-degree grid and signoff tolerance"
    if (params.torque_method != "weighted_stress" or params.field_composition_source != "resultant"
            or params.nonlinear_solver != "picard" or params.linear_solver_preconditioner != "direct"
            or params.max_nonlinear_iterations is not None):
        return "the field solution or torque extraction differs from the measured model"
    return None


def classify_phase_f_qualification(config: MotorConfig):
    """Return the separate, Windows-only Phase F qualification payload."""
    basis = "coilEM Phase F Windows benchmark report, unavailable"
    result = {"status": "experimental", "reason": "", "caveats": list(CAVEATS), "basis": basis, "reference": REFERENCE}
    if _platform_key() != "windows-x86_64":
        result["reason"] = "Outer-rotor SPM: this platform has no matching Phase F Windows x86_64 engineering record."
        return result
    reason = _scope_reason(config)
    if reason is not None:
        result["reason"] = "Outer-rotor SPM: outside the Phase F Windows engineering scope; " + reason + "."
        return result
    record = _verified_evidence()
    if record is None:
        result["reason"] = "Outer-rotor SPM: reviewed Phase F Windows evidence is missing, changed or does not match this build's physics."
        return result
    result.update(
        status="qualified",
        reason="Outer-rotor SPM, measured concentrated winding families, sinusoidal current: "
        "all 10 Windows fixtures pass for mean torque and Back-EMF.",
        basis="coilEM Phase F Windows benchmark report, measured at " + record["measured_commit"][:8],
    )
    return result
