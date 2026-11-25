"""Phase G rotor references from FEMM: the registered histories, requests and checkpoints.

No solver imports here, so the Windows FEMM environment (tools/femm_reference/requirements.txt)
can read the requests and the report can run anywhere with numpy.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "benchmarks/g-v2.0"
SPEC = PROTOCOL / "benchmark_spec.json"
REQUESTS = PROTOCOL / "femm-requests"
REFERENCES = PROTOCOL / "references/femm-rotor"
POSITIONS = 384
SPEEDS = (1500, 3000)
STRIDES = (4, 2, 1)  # 96, 192 and 384 of the 384 positions
ROTOR_GROUP = 10
# FEMM mesh controls per motor: mesh density, air-gap element size (mm) and air-gap arc step (deg). The same
# as the 0.5.9 Phase G FEMM qualification used for these fixtures (benchmarks/phase-g-v1 at 9088fd46^).
FEMM_MESH = {
    "inner_spm": ("fine", 0.1, 0.2),
    "flat_ipm": ("normal", 0.125, 0.25),
    "distributed_spm": ("normal", 0.125, 0.25),
    "outer_spm": ("normal", 0.125, 0.25),
}
MATCHED_MAGNET = {"remanence_T": 1.315, "relative_permeability": 1.05}


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_npz(path, **arrays) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp.npz")
    try:
        np.savez_compressed(temporary, **arrays)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def spec() -> dict:
    registered = read(SPEC)
    if registered.get("schema") != "coilem.phase_g_loss/v2" or registered["rotor"]["positions"] != POSITIONS:
        raise ValueError("Unknown Phase G specification")
    return registered


def history(history_id: str) -> dict:
    for row in spec()["rotor_histories"]:
        if row["id"] == history_id:
            if sha(PROTOCOL / row["fixture"]) != row["fixture_sha256"]:
                raise ValueError(f"The registered fixture of {history_id} changed")
            return row
    raise ValueError(f"No Phase G rotor history named {history_id}")


def history_ids() -> list[str]:
    return [row["id"] for row in spec()["rotor_histories"]]


def request_path(history_id: str) -> Path:
    return REQUESTS / f"{history_id}.json"


def load_request(history_id: str) -> dict:
    """A committed FEMM request, refused when the specification or the fixture it was written for changed."""
    path = request_path(history_id)
    request = read(path)
    row = history(history_id)
    if request["spec_sha256"] != sha(SPEC) or request["history"] != row:
        raise ValueError(f"{path.name} was written for another Phase G specification")
    if request["steel_bh_sha256"] != sha(ROOT / "materials/electrical-steel/M350-50A.csv"):
        raise ValueError("The M350-50A B-H curve changed since the request was written")
    return request


def phase_ampere_turns(config: dict, angle_deg: float) -> dict[str, float]:
    """Golden public-gamma-zero sine for these fixtures, independent of either field solver.

    The offsets are the phase axes registered for the 0.5.9 Phase G fixtures, which g-v2.0 reuses unchanged.
    """
    if config["solve_params"]["current_angle_deg"] != 0:
        raise ValueError("Phase G registers public gamma zero only")
    amplitude = config["solve_params"]["current_amplitude_A"] * config["winding"]["turns_per_coil"] / config["winding"]["parallel_paths"]
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
        phase: amplitude * math.sin(math.radians(config["rotor"]["pole_count"] / 2 * angle_deg + offset - shift))
        for phase, shift in zip("ABC", (0, 120, 240), strict=True)
    }


def pose_angle(index: int) -> float:
    """The rotor's mechanical angle at a pose: a clockwise full turn, the last pose closing it."""
    return -360 * index / POSITIONS


def areas(corners) -> np.ndarray:
    corners = np.asarray(corners, dtype=float)
    a, b = corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]
    value = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) * 0.5e-6
    if not np.isfinite(value).all() or np.any(value <= 0):
        raise ValueError("Loss integration needs positive finite element areas")
    return value


def checkpoint(directory, index: int):
    """A finished pose's record, or None. A pose whose files changed after it was written is refused."""
    path = Path(directory) / f"position-{index:04d}" / "position.json"
    if not path.exists():
        return None
    record = read(path)
    if record["index"] != index or record["angle_deg"] != pose_angle(index):
        raise ValueError("Pose checkpoint has a different angle")
    for name, digest in record["sha256"].items():
        if sha(path.parent / name) != digest:
            raise ValueError("A finished pose changed: " + str(path.parent / name))
    return record


def protocol(directory, expected: dict) -> None:
    path = Path(directory) / "protocol.json"
    if path.exists():
        if read(path) != expected:
            raise ValueError("The request, the collector or its sources changed; use a new output folder")
    else:
        write(path, expected)


def enough_disk(directory, minimum_gb: float = 6.0) -> None:
    free = shutil.disk_usage(directory).free / 1024**3
    if free < minimum_gb:
        raise OSError(f"Stopped before solving: {free:.1f} GB free, below {minimum_gb} GB. Finished poses are kept.")
