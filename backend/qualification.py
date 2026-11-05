"""Qualification status under the reviewed protocol 1.6 parity report.

docs/VALIDATION.md#qualification-status is the source: a combination of
rotor, winding and excitation is qualified when every registered fixture for
it passes its FEMM parity gates in QUALIFICATION_REPORT, which measured the
current winding, current-angle, slot-layer and Precise mesh models at 88aae101.
Combinations the benchmark did not measure, or measured with failures, are
experimental. The result travels with previews, solve validation and saved
runs, so the app and its exports say what the docs say.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Literal, TypedDict

from backend.models import MotorConfig
from backend.models.performance import (
    DQ_FLUX_LINKAGE_QUALIFIED_REASON,
    DQ_FLUX_LINKAGE_STATUS_REASON,
    MAGNET_TEMPERATURE_QUALIFIED_REASON,
    MAGNET_TEMPERATURE_STATUS_REASON,
    OutputStatus,
)
from backend.public_policy import EXPERIMENTAL_IPM_TOPOLOGIES, experimental_rotors_enabled
from backend.winding_utils import concentrated_uses_tooth_coils

QualificationStatus = Literal["qualified", "experimental", "unsupported"]

# The basis, reasons and caveats travel in public preview, solve and saved-run
# payloads, which must not name the reference solver or thermal analysis
# (tools/smoke_public_runtime.py); docs/VALIDATION.md names the report in full.
def _registered_qualification():
    from backend.resources import BENCHMARK_RECORDS_DIR, read_data_json

    try:
        record = read_data_json(f"{BENCHMARK_RECORDS_DIR}/windows-x86_64.json")
        if (isinstance(record, dict) and record.get("schema") == "coilem.benchmark_record/v1"
                and isinstance(record.get("measured_commit"), str) and re.fullmatch("[0-9a-f]{40}", record["measured_commit"])
                and isinstance(record.get("source"), str)):
            return record
        return {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


_QUALIFICATION_RECORD = _registered_qualification()
QUALIFICATION_BASIS = "coilEM benchmark report, measured at " + (_QUALIFICATION_RECORD["measured_commit"][:8]
                                                              if _QUALIFICATION_RECORD else "unavailable")
QUALIFICATION_REPORT = _QUALIFICATION_RECORD.get("source", "unavailable") + "/benchmark_summary.json"
PRIUS_QUALIFICATION_REPORT = _QUALIFICATION_RECORD.get(
    "prius_report", "benchmarks/candidate-qualification-20261103/prius/app-results.json")
QUALIFICATION_REFERENCE = "https://github.com/coilemdev/coilem/blob/main/docs/VALIDATION.md#qualification-status"
_QUALIFIED_STEEL = "M350-50A"
_QUALIFIED_IPM = "flat_buried"
_EXPERIMENTAL_IPM = "v_shape"


def evidence_matches_runtime() -> bool:
    """A historical label cannot qualify changed or unverifiable installed physics."""
    from backend.benchmark_suite.record import check_physics
    from backend.resources import BENCHMARK_RECORDS_DIR, read_data_json

    try:
        record = read_data_json(f"{BENCHMARK_RECORDS_DIR}/windows-x86_64.json")
        return (record["measured_commit"] == _QUALIFICATION_RECORD.get("measured_commit")
                and check_physics(record)["status"] == "MATCH")
    except (OSError, ValueError, KeyError, TypeError):
        return False


class Qualification(TypedDict):
    status: QualificationStatus
    reason: str
    caveats: list[str]
    basis: str
    reference: str


def _result(status: QualificationStatus, reason: str, caveats: list[str]) -> Qualification:
    return {
        "status": status,
        "reason": reason,
        "caveats": caveats,
        "basis": QUALIFICATION_BASIS,
        "reference": QUALIFICATION_REFERENCE,
    }


def _distributed_pitch(config: MotorConfig) -> str | None:
    """"full", "5/6" or None for any other coil span, in units of 3q slots."""

    span = config.winding.coil_span
    if span is None:
        return "full"
    full = Fraction(config.stator.slot_count, config.rotor.pole_count)
    ratio = Fraction(span) / full
    if ratio == 1:
        return "full"
    if ratio == Fraction(5, 6):
        return "5/6"
    return None


def _combination(config: MotorConfig) -> tuple[QualificationStatus, str]:
    if config.geometry_reference == "pyleecan_prius_2004":
        return ("experimental", "Pyleecan Prius software reference: pinned geometry and materials; "
                "measured hardware identity and release qualification remain separate.")
    winding = config.winding
    rotor = config.rotor
    six_step = config.solve_params is not None and config.solve_params.excitation_mode == "ideal_six_step_120"
    if rotor.flux_barrier_count or rotor.barrier_widths_mm:
        return "unsupported", "Multi-layer IPM rotors are not supported in this preview."
    if winding.type == "concentrated" and winding.layers != 1:
        if not concentrated_uses_tooth_coils(config.stator.slot_count, rotor.pole_count):
            return "unsupported", "Two layers apply only to fractional-slot concentrated windings (tooth coils)."

    if config.topology == "IPM":
        if six_step:
            return "unsupported", "Ideal six-step excitation is available for SPM only."
        if rotor.ipm_topology in EXPERIMENTAL_IPM_TOPOLOGIES and experimental_rotors_enabled():
            return (
                "experimental",
                "HoleM50 rotor (ORNL 2004 Prius): an experimental rotor path with no benchmark qualification; its reference comparison is pending.",
            )
        if rotor.ipm_topology not in (_QUALIFIED_IPM, _EXPERIMENTAL_IPM):
            return "unsupported", "Only flat-buried and V-shape IPM rotors are supported in this preview."
        if winding.type == "distributed":
            return "experimental", "IPM with distributed windings was not measured by the benchmark."
        if rotor.ipm_topology == _EXPERIMENTAL_IPM:
            return (
                "experimental",
                "V-shape IPM: all 6 benchmark fixtures pass, but the version comparison shows increased "
                "fundamental Back-EMF error; accuracy remains experimental.",
            )
        return "qualified", "Flat-buried IPM, single-layer concentrated winding, sinusoidal current: all 14 benchmark fixtures pass."

    if winding.type == "concentrated":
        if six_step:
            return "qualified", "SPM, single-layer concentrated winding, ideal six-step: all 3 benchmark fixtures pass (42 of 42 gates)."
        return "qualified", "SPM, single-layer concentrated winding, sinusoidal current: all 19 benchmark operating points pass."
    if six_step:
        return "experimental", "SPM with distributed windings under ideal six-step excitation was not measured by the benchmark."
    if winding.layers == 1:
        return "experimental", "Single-layer distributed windings were not measured by the benchmark."
    pitch = _distributed_pitch(config)
    if pitch is None:
        return "experimental", "Only full-pitch and 5/6 short-pitch distributed windings were measured by the benchmark."
    return "qualified", f"SPM, two-layer distributed winding ({pitch} pitch), sinusoidal current: all 4 benchmark fixtures pass."


def _caveats(config: MotorConfig) -> list[str]:
    caveats = []
    solve_params = config.solve_params
    if solve_params is not None and (
        solve_params.solve_quality == "quick" or solve_params.mesh_density == "coarse"
    ):
        caveats.append("The coarse Preview mesh was not qualified; the benchmark used the Standard plan's normal mesh.")
    return caveats


def classify_qualification(config: MotorConfig) -> Qualification:
    """Return the status, a one-sentence reason and any caveats for ``config``."""

    status, reason = _combination(config)
    if status == "qualified" and config.winding.type == "concentrated" and config.winding.layers != 1:
        status, reason = "experimental", "Two-layer concentrated windings (a coil on every tooth) were not measured by the benchmark."
    steels = {config.materials.stator_steel, config.materials.rotor_steel}
    if status == "qualified" and steels != {_QUALIFIED_STEEL}:
        status, reason = "experimental", f"Custom steel: the benchmark qualified only the bundled {_QUALIFIED_STEEL} curve."
    if status == "qualified" and config.solve_params is not None and config.solve_params.mesh_build == "fast":
        status, reason = "experimental", "Fast mesh build: the benchmark measured meshes built with Precise node placement."
    if status == "qualified" and not evidence_matches_runtime():
        status, reason = "experimental", (
            "This build's physics do not match the measured benchmark basis. "
            "Candidate qualification is pending; the historical report does not qualify this build."
        )
    return _result(status, reason, _caveats(config) if status != "unsupported" else [])


# Protocol 1.6.0 adds reference gates for two outputs of a qualified design
# (docs/VALIDATION.md#050-performance-outputs). Each is qualified only inside
# what those gates measured; Ld and Lq stay experimental everywhere.
_DQ_CURRENT_ANGLE_RANGE_DEG = (0.0, 60.0)
_MAGNET_TEMPERATURE_RANGE_C = (20.0, 100.0)


def dq_flux_linkage_status(config: MotorConfig) -> tuple[OutputStatus, str]:
    """Loaded λd and λq: qualified for a qualified single-layer concentrated design under sinusoidal current at γ 0–60°."""

    solve_params = config.solve_params
    low, high = _DQ_CURRENT_ANGLE_RANGE_DEG
    if (
        classify_qualification(config)["status"] == "qualified"
        and config.winding.type == "concentrated"
        and config.winding.layers == 1
        and (solve_params is None or solve_params.excitation_mode == "sinusoidal")
        and low <= (solve_params.current_angle_deg if solve_params is not None else 0.0) <= high
    ):
        return "qualified", DQ_FLUX_LINKAGE_QUALIFIED_REASON
    return "experimental", DQ_FLUX_LINKAGE_STATUS_REASON


def magnet_temperature_status(config: MotorConfig) -> tuple[OutputStatus, str]:
    """Magnet derating: qualified for a qualified design from the catalogue's 20 °C to 100 °C."""

    temperature = config.solve_params.magnet_temperature_C if config.solve_params is not None else None
    low, high = _MAGNET_TEMPERATURE_RANGE_C
    if classify_qualification(config)["status"] == "qualified" and temperature is not None and low <= temperature <= high:
        return "qualified", MAGNET_TEMPERATURE_QUALIFIED_REASON
    return "experimental", MAGNET_TEMPERATURE_STATUS_REASON
