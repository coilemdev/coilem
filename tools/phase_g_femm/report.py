"""Turn collected FEMM rotor histories into Phase G reference records (numpy only).

    python -m tools.phase_g_femm.report --out D:/coilem-phase-g-femm [--history inner_spm_loaded]

For each complete history it checks every pose, the closing pose and the fixed mesh, then works
out rotor hysteresis, lamination eddy and total loss with the independent loss calculator
(tools/rotor_loss_reference.py, no coilEM loss code) from 96, 192 and 384 of the positions at
1500 and 3000 rpm. The record goes to benchmarks/g-v2.0/references/femm-rotor/<history>.json,
where `python -m tools.run_phase_g --regrade` grades coilEM against it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from tools.phase_g_femm.contract import (
    POSITIONS,
    REFERENCES,
    ROOT,
    SPEC,
    SPEEDS,
    STRIDES,
    areas,
    checkpoint,
    history_ids,
    load_request,
    pose_angle,
    read,
    request_path,
    sha,
    write,
)


def analyse(directory: Path, history_id: str) -> dict:
    from tools.rotor_loss_reference import reference_loss

    protocol = read(directory / "protocol.json")
    request = load_request(history_id)
    if protocol["history"] != request["history"] or protocol["request_sha256"] != sha(request_path(history_id)):
        raise ValueError(f"{directory} was collected for another request")
    if protocol["spec_sha256"] != sha(SPEC):
        raise ValueError(f"{directory} was collected for another Phase G specification")
    records, fields = [], []
    for index in range(POSITIONS + 1):
        record = checkpoint(directory, index)
        if record is None:
            raise ValueError(f"{history_id}: pose {index} is missing; the history is not complete")
        if record["protocol_sha256"] != sha(directory / "protocol.json") or record["geometry_sha256"] != sha(directory / "rotor-geometry.npz"):
            raise ValueError(f"{history_id}: pose {index} belongs to another collection")
        records.append(record)
        with np.load(directory / f"position-{index:04d}" / "fields.npz") as data:
            fields.append(data["rotor"])
    with np.load(directory / "rotor-geometry.npz") as geometry:
        corners = geometry["rotor_corners"]
    values = np.asarray(fields)
    if values.shape != (POSITIONS + 1, len(corners), 2) or not np.isfinite(values).all():
        raise ValueError(f"{history_id}: incomplete or non-finite rotor fields")
    difference = values[-1] - values[0]
    closure = {"max_T": float(np.max(np.abs(difference))), "rms_T": float(np.sqrt(np.mean(difference**2)))}
    stack_m = request["requested_config"]["stator"]["stack_length_mm"] * 1e-3
    element_areas = areas(corners)
    speeds = {}
    for speed in SPEEDS:
        by_count = {}
        for stride in STRIDES:
            subset = values[:-1:stride]
            angles = np.array([pose_angle(index) for index in range(0, POSITIONS, stride)])
            loss = reference_loss(subset, angles, element_areas, speed_rpm=speed, stack_m=stack_m,
                                  coefficients=request["coefficients"], field_frame="rotor_material")
            by_count[str(len(subset))] = {key: float(loss[key]) for key in ("hysteresis_W", "lamination_eddy_W", "total_W")}
            mass = float(loss["mass_kg"])
        speeds[str(speed)] = by_count
    identity = protocol["reference_identity"]
    return {
        "schema": "coilem.phase_g_rotor_reference/v1",
        "history": history_id,
        "spec_sha256": sha(SPEC),
        "request_sha256": sha(request_path(history_id)),
        "solver": identity.get("solver") or ("FEMM 5" if identity.get("phase_g_femm5_execution") else "FEMM 4.2"),
        "reference_identity": identity,
        "femm_mesh": protocol["femm_mesh"],
        "positions": POSITIONS,
        "rotor_elements": int(len(corners)),
        "rotor_iron_mass_kg": mass,
        "closure": closure,
        "speeds": speeds,
        "loss_calculator": {"module": "tools/rotor_loss_reference.py", "sha256": sha(ROOT / "tools/rotor_loss_reference.py")},
        "collection_wall_s": round(sum(record["wall_s"] for record in records), 1),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="The base folder the collector wrote to")
    parser.add_argument("--history", action="append", help="Only these histories (repeatable)")
    args = parser.parse_args(argv)
    written = 0
    for history_id in args.history or history_ids():
        directory = (args.out / history_id).resolve()
        if not (directory / "protocol.json").exists():
            print(f"{history_id}: not collected")
            continue
        try:
            record = analyse(directory, history_id)
        except ValueError as exc:
            print(f"{history_id}: {exc}")
            continue
        path = REFERENCES / f"{history_id}.json"
        write(path, record)
        total = record["speeds"]["3000"]["384"]["total_W"] * 1000
        print(f"{history_id}: {total:.3f} mW at 3000 rpm, turn closes to {record['closure']['max_T']:.1e} T; wrote {path.relative_to(ROOT)}")
        written += 1
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
