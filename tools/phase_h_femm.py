"""Solve the in-plane cases of benchmark Phase H with FEMM and store them as a reference.

Each case is drawn from the design's exact region outlines, given the
materials, heat and cooled faces of ``planar_problem``, and solved on two
meshes. FEMM's block averages become a reference bundle in
``benchmarks/h-v1.0/references/femm5``. Needs FEMM 5 (set COILEM_FEMM5_APP if
it is not in ~/Applications):

    python -m tools.phase_h_femm --work ~/coilem-femm5-runs/phase-h
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backend.benchmark_suite.thermal_phase_h import PLANAR_MATERIALS, PLANAR_PARTS, REFERENCES, planar_problem, spec, spec_sha256
from tools.check_thermal_conduction_femm import NO_MESH, SOLVER, _mean, _sha256, draw, femm_build, lower, mesh_size_mm, open_femm, solve

ROOT = Path(__file__).resolve().parents[1]
TOOL_FOLDER = "femm5"
GROUPS = {kind: material or NO_MESH for kind, material in PLANAR_MATERIALS.items()}


def reference(femm, case_row: dict, work: Path, build: dict) -> dict:
    problem = planar_problem(case_row)
    faces = problem["faces"]
    model = lower(problem["regions"], {name: face["radius_mm"] for name, face in faces.items()}, GROUPS)
    coarse_mm = mesh_size_mm(problem["config"], problem["areas_m2"])
    surroundings = spec()["surroundings_C"]
    solved = {}
    for level, scale in (("coarse", 1.0), ("fine", 0.5)):
        size = {material: coarse_mm * scale for material in problem["conductivity_W_mK"]}
        size["gap"] = min(coarse_mm, problem["gap_mm"] / 2) * scale
        draw(femm, model, conductivity_W_mK=problem["conductivity_W_mK"], faces=faces, depth_mm=problem["depth_mm"], size_mm=size)
        path = work / f"{case_row['id']}-{level}.feh"
        solved[level] = solve(femm, model, problem["source_W_m3"], path,
                              face_radius_mm={name: (face["radius_mm"], face["inward"]) for name, face in faces.items()}) | {"input": path}
        femm.hi_close()
    fine, coarse = solved["fine"], solved["coarse"]
    files = sorted(p for run in (coarse, fine) for p in (run["input"], run["input"].with_suffix(".anh")))
    exits = {name: (fine["face_C"][name] - surroundings) / face["resistance_K_W"] for name, face in faces.items()}
    total = sum(case_row["heat_W"].values())
    return {
        "case_id": case_row["id"], "spec_sha256": spec_sha256(), "tool": SOLVER, "tool_folder": TOOL_FOLDER,
        "tool_build": f"{build['version']} macOS, femm_headless {build['sha256']['femm_headless'][:16]}",
        "kind": "planar finite elements; block averages from ho_blockintegral",
        "temperature_C": {part: _mean(fine["regions"], part)[0] for part in PLANAR_PARTS},
        "coarse_temperature_C": {part: _mean(coarse["regions"], part)[0] for part in PLANAR_PARTS},
        "area_difference_pct": {part: 100 * (_mean(fine["regions"], part)[1] - problem["areas_m2"][part]) / problem["areas_m2"][part]
                                for part in PLANAR_PARTS},
        "exit_W": exits, "heat_balance_pct": 100 * (sum(exits.values()) - total) / total,
        "elements": {"coarse": coarse["elements"], "fine": fine["elements"]}, "mesh_size_mm": {"coarse": coarse_mm, "fine": coarse_mm / 2},
        "given": {"conductivity_W_mK": problem["conductivity_W_mK"],
                  "faces": {name: {"radius_mm": face["radius_mm"], "h_W_m2K": face["h_W_m2K"]} for name, face in faces.items()}},
        "raw_artifact_sha256": hashlib.sha256("".join(f"{p.name}:{_sha256(p)}\n" for p in files).encode()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", type=Path, default=Path("~/coilem-femm5-runs/phase-h"), help="folder for FEMM's input and solution files")
    parser.add_argument("--only", help="run only the cases whose id contains this text")
    args = parser.parse_args()
    work = args.work.expanduser()
    work.mkdir(parents=True, exist_ok=True)
    out = ROOT / REFERENCES / TOOL_FOLDER
    out.mkdir(parents=True, exist_ok=True)
    build = femm_build()
    cases = [row for row in spec()["cases"] if row["scope"] == "in_plane" and (args.only is None or args.only in row["id"])]
    femm = open_femm()
    try:
        for row in cases:
            bundle = reference(femm, row, work, build)
            (out / f"{row['id']}.json").write_text(json.dumps(bundle, indent=1, allow_nan=False) + "\n", encoding="utf-8")
            mesh = max(abs(bundle["temperature_C"][p] - bundle["coarse_temperature_C"][p]) for p in PLANAR_PARTS)
            print(f"{row['id']:52s} " + " ".join(f"{p} {bundle['temperature_C'][p]:7.2f}" for p in PLANAR_PARTS)
                  + f"  mesh {mesh:.3f} K  balance {bundle['heat_balance_pct']:+.3f}%  {bundle['elements']['fine']:,} elements", flush=True)
    finally:
        femm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
