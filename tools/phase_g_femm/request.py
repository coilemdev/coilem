"""Write the frozen FEMM request of each Phase G rotor history (run in the coilEM environment).

A request holds everything the Windows FEMM collector needs and cannot compute itself without the
full coilEM environment: the native solver configuration, the loss coefficients and the native
winding regions to audit the FEMM model against. Requests are committed, so the FEMM machine needs
only tools/femm_reference/requirements.txt.

    python -m tools.phase_g_femm.request            # write missing requests
    python -m tools.phase_g_femm.request --check    # fail if a committed request is not what this build writes
"""

from __future__ import annotations

import argparse
from dataclasses import asdict

import numpy as np

from tools.phase_g_femm.contract import (
    FEMM_MESH,
    MATCHED_MAGNET,
    POSITIONS,
    PROTOCOL,
    ROOT,
    SPEC,
    SPEEDS,
    history,
    history_ids,
    read,
    request_path,
    sha,
    spec,
    write,
)


def native_windings(template: dict) -> list[dict]:
    """Each native coil side: its phase, direction, share of the turns and area-weighted centroid (mm)."""
    nodes = np.asarray(template["mesh"]["nodes"], dtype=float)
    triangles = np.asarray(template["mesh"]["triangles"], dtype=int)
    ids = np.asarray(template["element_region_ids"])
    sides = []
    for region in template["physics_contract"]["regions"]:
        if region["kind"] != "SlotWinding":
            continue
        corners = nodes[triangles[ids == region["id"]]]
        u, v = corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]
        weights = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
        centroid = np.average(corners.mean(axis=1), weights=weights, axis=0)
        winding = region["winding"]
        sides.append({"region": region["id"], "phase": winding["phase"], "direction": winding["direction"],
                      "turn_fraction": winding["turn_fraction"], "centroid_mm": [float(centroid[0]), float(centroid[1])]})
    if not sides:
        raise ValueError("The native template has no coil sides")
    return sides


def build(history_id: str) -> dict:
    from backend import __version__
    from backend.gmsh_solver import run_gmsh_mesh_preview
    from backend.iron_loss import M350_50A_LOSS
    from backend.models import MotorConfig
    from backend.solver import _clockwise_excitation_config

    row = history(history_id)
    requested = read(PROTOCOL / row["fixture"])
    # The native solve runs in its own counter-clockwise frame; the app maps public gamma 0 once, like this.
    native = _clockwise_excitation_config(MotorConfig.model_validate(requested))
    template = run_gmsh_mesh_preview(native, rotor_angle_deg=0)["solve_mesh_artifact"]
    density, airgap_mm, arc_deg = FEMM_MESH[row["motor"]]
    return {
        "schema": "coilem.phase_g_femm_request/v1",
        "history": row,
        "spec_sha256": sha(SPEC),
        "requested_config": requested,
        "native_config": native.model_dump(mode="json"),
        "coefficients": asdict(M350_50A_LOSS),
        "steel_bh_sha256": sha(ROOT / "materials/electrical-steel/M350-50A.csv"),
        "matched_magnet": MATCHED_MAGNET,
        "positions": POSITIONS,
        "collection_speed_rpm": spec()["rotor"]["collection_speed_rpm"],
        "evaluation_speeds_rpm": list(SPEEDS),
        "femm_mesh": {"density": density, "airgap_target_mm": airgap_mm, "airgap_arc_step_deg": arc_deg},
        "native_windings": native_windings(template),
        "written_by": f"coilEM {__version__}",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Fail if a committed request differs from what this build writes")
    parser.add_argument("--history", action="append", help="Only these histories (repeatable)")
    args = parser.parse_args(argv)
    problems = 0
    for history_id in args.history or history_ids():
        path = request_path(history_id)
        value = build(history_id)
        if path.exists():
            # Which build wrote a request is provenance, not content.
            if {**read(path), "written_by": None} != {**value, "written_by": None}:
                problems += 1
                print(f"{path.name}: differs from what this build writes; requests are frozen, start a new protocol to change one")
            elif args.check:
                print(f"{path.name}: agrees")
            continue
        if args.check:
            problems += 1
            print(f"{path.name}: missing")
            continue
        write(path, value)
        print(f"wrote {path.relative_to(ROOT)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
