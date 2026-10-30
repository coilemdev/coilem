"""Registered phase-resistance gate (protocol 1.6.0): coilEM's phase resistance against hand calculations.

The phase resistance is a closed-form result of the winding's geometry, wire
and conductor data, so it needs no solve and no reference solver. Its
reference is an independent hand calculation, written out step by step in
benchmarks/abcd-v1.6/PHASE-RESISTANCE.md and registered with its results in
benchmarks/abcd-v1.6/phase_resistance_gate.json.

Each gate case is a registered suite fixture plus a declared wire, conductor
and winding temperature. The fixtures carry none of these, since a field solve
does not need them; everything else (slots, bore, yoke, teeth, stack, turns,
paths, winding type and layers) is the fixture's own.
"""

from pathlib import Path

from backend.benchmark_suite.abc_metrics import band, pct
from backend.benchmark_suite.contract import checked_json, read

REGISTRATION = Path("benchmarks/abcd-v1.6/phase_resistance_gate.json")
# Percent between coilEM's phase resistance and the hand calculation: pass, then yellow.
PHASE_RESISTANCE_PCT = (1.0, 3.0)


def gate_config(case, root):
    """The case's fixture with its declared wire, conductor and winding temperature."""

    from backend.models import MotorConfig

    raw = checked_json(root, case["fixture"], case["fixture_sha256"])
    raw["winding"]["wire"] = dict(case["wire"])
    raw["materials"]["conductor"] = case["conductor"]
    raw["solve_params"]["winding_temperature_C"] = case["winding_temperature_C"]
    return MotorConfig.model_validate(raw)


def phase_resistance_gates(root, registration=REGISTRATION):
    """Each case's status with coilEM's values, the hand values and the errors behind it."""

    from backend.winding_resistance import winding_resistance

    root = Path(root)
    spec = read(root / registration)
    if spec["schema"] != "coilem.phase_resistance_gate/v1":
        raise ValueError("Unsupported phase-resistance gate registration")
    rows = []
    for case in spec["cases"]:
        record = winding_resistance(gate_config(case, root))
        hand = case["hand"]
        error = pct(record.phase_resistance_ohm, hand["phase_resistance_ohm"])
        rows.append({
            "id": case["id"],
            "status": band(error, *PHASE_RESISTANCE_PCT),
            "phase_resistance_error_pct": error,
            "phase_resistance_20C_error_pct": pct(record.phase_resistance_20C_ohm, hand["phase_resistance_20C_ohm"]),
            "mean_turn_length_error_pct": pct(record.mean_turn_length_mm, hand["mean_turn_length_mm"]),
            "coilem": {
                "end_turn_length_mm": record.end_turn_length_mm,
                "mean_turn_length_mm": record.mean_turn_length_mm,
                "turn_copper_area_mm2": record.turn_copper_area_mm2,
                "series_turns_per_phase": record.series_turns_per_phase,
                "phase_resistance_20C_ohm": record.phase_resistance_20C_ohm,
                "phase_resistance_ohm": record.phase_resistance_ohm,
            },
            "hand": hand,
        })
    return rows
