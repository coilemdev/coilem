"""Write the frozen Phase G specification from the registered fixtures and FEMM records.

    python -m tools.make_phase_g

It refuses to replace an existing specification: a published result and any
future reference name the hash of that file. Change the protocol folder and
version instead.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks/g-v2.0"
REFERENCES = "references/femm-stator-copper-20261117"
MOTORS = {
    "inner_spm": "Inner-rotor SPM, 8 poles, 12 slots, concentrated winding",
    "flat_ipm": "Inner-rotor flat IPM, 8 poles, 12 slots (FSAE)",
    "distributed_spm": "Inner-rotor SPM, 8 poles, 24 slots, distributed winding",
    "outer_spm": "Outer-rotor SPM, 10 poles, 12 slots, single-layer winding",
}
LOADS = ("no_load", "loaded")
SPEEDS = (1500, 3000)
COLLECTION_SPEED = 3000


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    cases, histories = [], []
    for motor in MOTORS:
        for load in LOADS:
            history = f"{motor}_{load}"
            for speed in SPEEDS:
                name = f"loss_{motor}_{load}_{speed}rpm"
                fixture, reference = f"fixtures/{name}.json", f"{REFERENCES}/{name}.json"
                config = json.loads((PROTOCOL / fixture).read_text(encoding="utf-8"))
                cases.append({"id": name, "motor": motor, "load": load, "speed_rpm": speed,
                              "current_peak_A": float(config["solve_params"]["current_amplitude_A"]),
                              "fixture": fixture, "fixture_sha256": _sha256(PROTOCOL / fixture),
                              "reference": reference, "reference_sha256": _sha256(PROTOCOL / reference),
                              "rotor_history": history})
                if speed == COLLECTION_SPEED:
                    histories.append({"id": history, "motor": motor, "load": load, "rotor_layout": config.get("rotor_layout", "inner"),
                                      "fixture": fixture, "fixture_sha256": _sha256(PROTOCOL / fixture)})
    return {
        "schema": "coilem.phase_g_loss/v2",
        "protocol_version": "G-2.0.0",
        "scope": "Full-motor loss numbers on four motors at no load and one load, 1500 and 3000 rpm. "
                 "Sinusoidal drive, current on the q axis, M350-50A steel, N42 magnets, 0.8 mm wire with two strands, "
                 "20 C winding, no mechanical loss.",
        "motors": [{"id": motor, "description": description} for motor, description in MOTORS.items()],
        "stator_copper_reference": {
            "solver": "FEMM 4.2", "collected": "2026-11-17", "directory": REFERENCES,
            "manifest_sha256": _sha256(PROTOCOL / REFERENCES / "manifest.json"),
            "review_sha256": _sha256(PROTOCOL / REFERENCES / "review.json"),
            "note": "Stator iron loss from FEMM field histories over one electrical period (96 samples); copper from the "
                    "specified wire, turn count and end-turn geometry of the FEMM winding blocks.",
        },
        "rotor": {"positions": 384, "position_counts": [96, 192, 384], "collection_speed_rpm": COLLECTION_SPEED,
                  "evaluation_speeds_rpm": list(SPEEDS), "reference": None},
        "gates": {"reference_relative": 0.10, "absolute_W": 0.001, "copper_relative": 0.01,
                  "angular_relative": 0.05, "closure_max_T": 1e-6, "closure_rms_T": 1e-7},
        "not_included": ["magnet and other solid-part eddy currents", "AC winding loss", "inverter loss",
                         "excess loss, minor loops and rotating-flux corrections"],
        "cases": cases,
        "rotor_histories": histories,
    }


def main() -> int:
    path = PROTOCOL / "benchmark_spec.json"
    if path.exists():
        raise SystemExit(f"{path} exists and is frozen; start a new protocol folder instead")
    path.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
