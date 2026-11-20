"""Fresh FEMM field anchors driven by the native preflight's explicit ampere-turns.

This is a small excitation/coordinate audit, not a loss history or a replacement
for reference mesh qualification. It never imports the active native backend.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import numpy as np

from tools.femm_reference import e_producer, phase_e, runtime
from tools.femm_reference.rotor_airgap import BOUNDARY, add_periodic_airgap, mesh_signature
from tools.femm_reference.rotor_loss_pilot import FIXTURE, export_fields, sha


def coil_group(slot, layer):
    return 100+8*slot+layer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-preflight", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    native = args.native_preflight.resolve()
    directory = args.out.resolve()
    if directory.exists():
        raise ValueError("excitation anchors require a fresh directory")
    protocol_native = json.loads((native / "protocol.json").read_text())
    if protocol_native["kind"] != "preflight" or protocol_native["fixture_sha256"] != sha(FIXTURE):
        raise ValueError("native preflight fixture or collection kind differs")
    points = np.loadtxt(native / "material-query-points.csv", delimiter=",", ndmin=2)
    inputs = []
    for index in range(3):
        path = native / f"position-{index:04d}" / "excitation.json"
        inputs.append((json.loads(path.read_text()), sha(path)))
    directory.mkdir(parents=True)
    identity = runtime.identity("e")
    Solver, Model, geometry, _, _, femm, automation_module, adapter = phase_e.load_adapter()
    e_producer.clear_solver_environment()
    os.environ["FEMM_AIRGAP_MESHSIZE_MM"] = "0.125"
    config = Model.model_validate(json.loads(FIXTURE.read_text()))
    config.solve_params.current_angle_deg = protocol_native["native_gamma_deg"]
    config.solve_params.mesh_density = "normal"
    geom = geometry(config)

    class ProbeSolver(Solver):
        def _set_femm_blockprop(self, *a, **kw):
            if a[4] == "rotor_core":
                kw["group"] = 10
            match = re.fullmatch(r"Coil_v3_s(\d+)_l(\d+)", a[1])
            if match:
                kw["group"] = coil_group(int(match[1]), int(match[2]))
            return super()._set_femm_blockprop(*a, **kw)

    protocol = {"schema": "coilem.rotor_excitation_probe/v1", "kind": "excitation_probe",
                "native_preflight_protocol_sha256": sha(native / "protocol.json"),
                "native_excitation_sha256": [digest for _, digest in inputs],
                "fixture_sha256": sha(FIXTURE), "reference_identity": identity,
                "requested_public_gamma_deg": protocol_native["requested_gamma_deg"],
                "native_gamma_deg": protocol_native["native_gamma_deg"],
                "angles_native_ccw_deg": [e["native_rotor_mechanical_deg"] for e, _ in inputs],
                "current_rule": "explicit phase ampere-turns from audited native preflight, divided by actual FEMM coil block area",
                "raw_field_frame": "rotor_material", "raw_mesh_frame": "rotor_material",
                "fresh_unsolved_base_each_pose": True, "loss_watts": None, "full_matrix_started": False}
    runtime.write(directory / "protocol.json", protocol)
    np.savetxt(directory / "material-query-points.csv", points, delimiter=",", fmt="%.17g")
    automation = automation_module.Automation(directory)
    try:
        automation.open(1)
        solver = ProbeSolver()
        solver._last_geom, solver._last_rotor_offset_rad = geom, 0.0
        solver._setup_problem(femm, config, geom)
        solver._draw_full_geometry(femm, config, geom, rotor_offset_deg=0)
        solver._apply_winding_current(femm, config, geom, 0)
        add_periodic_airgap(femm, solver, config, geom)
        solver._apply_boundary(femm, geom)
        base = directory / "unsolved-base.fem"
        femm.mi_saveas(str(base))
        femm.mi_saveas(str(directory / "area-probe.fem"))
        femm.mi_createmesh()
        femm.mi_analyze(1)
        femm.mi_loadsolution()
        areas = {}
        for region in adapter.winding_regions(config, geom):
            slot, layer, _, _ = adapter.assignment(region)
            femm.mo_groupselectblock(coil_group(slot, layer))
            area = float(femm.mo_blockintegral(5))*1e6
            femm.mo_clearblock()
            if area <= 0:
                raise ValueError("FEMM winding area probe returned an empty block")
            areas[f"Coil_v3_s{slot}_l{layer}"] = area
        runtime.write(directory / "winding-areas-mm2.json", areas)
        femm.mo_close()
        femm.mi_close()
        for index, (excitation, _) in enumerate(inputs):
            started = time.perf_counter()
            output = directory / f"position-{index:04d}"
            output.mkdir()
            femm.opendocument(str(base))
            angle = excitation["native_rotor_mechanical_deg"]
            femm.mi_modifyboundprop(BOUNDARY, 10, angle)
            applied = {}
            for region in adapter.winding_regions(config, geom):
                slot, layer, phase, direction = adapter.assignment(region)
                name = f"Coil_v3_s{slot}_l{layer}"
                turns = excitation["phase_ampere_turns"][phase]*(1 if direction == "in" else -1)
                density = turns/areas[name]
                femm.mi_modifymaterial(name, 4, density)
                applied[name] = {"phase": phase, "direction": direction, "ampere_turns": turns,
                                 "area_mm2": areas[name], "current_density_A_mm2": density}
            femm.mi_saveas(str(output / "model.fem"))
            femm.mi_createmesh()
            femm.mi_analyze(1)
            femm.mi_loadsolution()
            _, rotor_cells = export_fields(femm, output, 0.0, points)
            runtime.write(output / "applied-excitation.json", applied)
            record = {"index": index, "native_mechanical_angle_deg": angle, "rotor_cells": rotor_cells,
                      "total_elements": int(femm.mo_numelements()), "mesh_sha256": mesh_signature(output / "model.ans"),
                      "wall_s": time.perf_counter()-started, "sha256": {p.name: sha(p) for p in output.iterdir()}}
            femm.mo_close()
            femm.mi_close()
            runtime.write(output / "position.json", record)
            print(json.dumps({k: record[k] for k in ("index", "native_mechanical_angle_deg", "total_elements", "wall_s")}), flush=True)
    finally:
        automation.close()


if __name__ == "__main__":
    main()
