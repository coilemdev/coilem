"""Portable Phase G requests and evidence contracts, without solver imports."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmarks/phase-g-v1/benchmark_spec.json"
POSITIONS = 384
SPEEDS = (1500, 3000)
REGIONS = ("stator", "rotor")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_npz(path, **arrays):
    path = Path(path)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp.npz")
    try:
        np.savez_compressed(temporary, **arrays)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def suite():
    spec = read(SUITE)
    if spec["schema"] != "coilem.phase_g_loss/v1" or spec["positions"] != POSITIONS:
        raise ValueError("Unknown Phase G sampling contract")
    for case in spec["cases"]:
        if sha(ROOT / case["fixture"]) != case["fixture_sha256"]:
            raise ValueError("Registered Phase G fixture changed: " + case["id"])
    return spec


def case_by_id(case_id):
    return next(case for case in suite()["cases"] if case["id"] == case_id)


def config_for(case):
    raw = read(ROOT / case["fixture"])
    raw["solve_params"]["current_amplitude_A"] = case["current_peak_A"]
    return raw


def phase_ampere_turns(config, angle):
    """Golden public-gamma-zero sine, independent of either field backend."""
    if config["solve_params"]["current_angle_deg"] != 0:
        raise ValueError("Phase G v1 registers public gamma zero only")
    amplitude = config["solve_params"]["current_amplitude_A"] * config["winding"]["turns_per_coil"] / config["winding"]["parallel_paths"]
    # The native adapter maps public gamma 0 to native gamma 180 once.
    key = (
        config.get("rotor_layout", "inner"),
        config["winding"]["type"],
        config["stator"]["slot_count"],
        config["rotor"]["pole_count"],
        config["winding"]["layers"],
    )
    offsets = {("inner", "concentrated", 12, 8, 1): 60.0, ("inner", "distributed", 24, 8, 2): 90.0, ("outer", "concentrated", 12, 10, 1): -135.0}
    if key not in offsets:
        raise ValueError("No independently registered phase-axis contract for this fixture")
    offset = offsets[key]
    return {
        phase: amplitude * math.sin(math.radians(config["rotor"]["pole_count"] / 2 * angle + offset - shift))
        for phase, shift in zip("ABC", (0, 120, 240), strict=True)
    }


def areas(corners):
    corners = np.asarray(corners, dtype=float)
    a, b = corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]
    value = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) * 0.5e-6
    if not np.isfinite(value).all() or np.any(value <= 0):
        raise ValueError("Loss integration needs positive finite material areas")
    return value


def checkpoint(directory, index):
    path = Path(directory) / f"position-{index:04d}" / "position.json"
    if not path.exists():
        return None
    record = read(path)
    if record["index"] != index or record["angle_deg"] != -360 * index / POSITIONS:
        raise ValueError("Pose checkpoint has a different angle")
    for name, digest in record["sha256"].items():
        if sha(path.parent / name) != digest:
            raise ValueError("Raw Phase G checkpoint changed: " + str(path.parent / name))
    return record


def protocol(directory, expected):
    path = Path(directory) / "protocol.json"
    if path.exists():
        if read(path) != expected:
            raise ValueError("Phase G sources, inputs or sampling changed; use a new output directory")
    else:
        write(path, expected)


def enough_disk(directory, minimum_gb=20):
    import shutil

    if shutil.disk_usage(directory).free < minimum_gb * 1024**3:
        raise OSError("Phase G stopped before solving: less than 20 GiB free; checkpoints are retained")


def reference_resistance(config, coil_blocks):
    """Hand calculation from FEMM slot areas/centroids and specified round wire.

    Registered fixtures have identical slots, one path, tooth span 1 or a
    full-pitch distributed span of 3 slots. No production resistance/MLT input.
    """
    slots = config["stator"]["slot_count"]
    centres = {}
    for slot in range(slots):
        blocks = [b for b in coil_blocks if b["slot"] == slot]
        total = sum(b["area_mm2"] for b in blocks)
        if total <= 0:
            raise ValueError("Independent copper calculation has a missing slot")
        centres[slot] = tuple(sum(b["area_mm2"] * b["centroid_mm"][axis] for b in blocks) / total for axis in (0, 1))
    winding = config["winding"]
    span = 3 if winding["type"] == "distributed" else 1
    if winding["type"] == "distributed" and (slots, config["rotor"]["pole_count"]) != (24, 8):
        raise ValueError("No registered distributed copper end-turn contract")
    end_turns = []
    for index in range(0, slots, 2):
        a, b = centres[index], centres[(index + span) % slots]
        radius = (math.hypot(*a) + math.hypot(*b)) / 2
        delta = abs(math.atan2(a[1], a[0]) - math.atan2(b[1], b[0]))
        delta = min(delta, 2 * math.pi - delta)
        end_turns.append(math.pi / 2 * delta * radius)
    wire = winding["wire"]
    mean_turn_mm = 2 * config["stator"]["stack_length_mm"] + 2 * sum(end_turns) / len(end_turns) + 4 * wire.get("end_turn_extension_mm", 0)
    turn_area_m2 = wire["strands_in_hand"] * math.pi / 4 * (wire["wire_bare_diameter_mm"] * 1e-3) ** 2
    series_turns = slots * winding["turns_per_coil"] / 6
    rho = 1e-6 / 58 * (1 + 0.00393 * (config["solve_params"]["winding_temperature_C"] - 20))
    resistance = rho * series_turns * mean_turn_mm * 1e-3 / (turn_area_m2 * winding["parallel_paths"] ** 2)
    return {
        "phase_resistance_ohm": resistance,
        "mean_turn_length_mm": mean_turn_mm,
        "method": "independent specified-wire/turn-count/end-arc calculation from FEMM slot centroids",
        "shared_resistance_assumption": False,
    }
