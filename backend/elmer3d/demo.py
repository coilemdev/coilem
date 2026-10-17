"""Small reproducible physical controls; these are not Prius geometry."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from backend.gmsh_solver import _GMSH_API_LOCK, initialize_gmsh

from .gmsh_environment import preserve_process_path
from .model import Case3D, Coil3D, Material3D


def create_demo(
    directory: Path,
    *,
    kind: Literal["sphere", "coil", "torque", "steel"] = "sphere",
    mesh_scale: float = 1.0,
    outer_radius_m: float = 0.06,
    current_A: float = 2.0,
) -> Case3D:
    """Meshed PM sphere and/or closed toroidal coil, with a closed air stress surface."""
    import gmsh

    if kind not in {"sphere", "coil", "torque", "steel"} or not 0.25 <= mesh_scale <= 4 or outer_radius_m < 0.04:
        raise ValueError("invalid control geometry or mesh parameters")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / "input.msh"
    with _GMSH_API_LOCK, preserve_process_path():
        initialize_gmsh()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
            gmsh.option.setNumber("Mesh.Binary", 0)
            gmsh.model.add("elmer3d_control")
            solids = [(3, gmsh.model.occ.addSphere(0, 0, 0, outer_radius_m)), (3, gmsh.model.occ.addSphere(0, 0, 0, 0.009))]
            pm_index = coil_index = core_index = None
            if kind == "steel":
                core_index = len(solids)
                solids.append((3, gmsh.model.occ.addSphere(0, 0, 0, 0.007)))
            if kind != "coil":
                pm_index = len(solids)
                solids.append((3, gmsh.model.occ.addSphere(0, 0, 0, 0.004)))
            if kind in {"coil", "torque"}:
                coil_index = len(solids)
                solids.append((3, gmsh.model.occ.addTorus(0, 0, 0, 0.024, 0.003)))
            fragments, mapping = gmsh.model.occ.fragment(solids[:1], solids[1:])
            gmsh.model.occ.synchronize()
            pm = set(mapping[pm_index]) if pm_index is not None else set()
            coil = set(mapping[coil_index]) if coil_index is not None else set()
            core = set(mapping[core_index]) - pm if core_index is not None else set()
            all_volumes = {entity for entity in fragments if entity[0] == 3}
            air = all_volumes - pm - coil - core
            for name, volumes, tag in (("Air", air, 101), ("Magnet", pm, 205), ("Coil", coil, 309), ("Core", core, 310)):
                if volumes:
                    gmsh.model.addPhysicalGroup(3, sorted(t for _, t in volumes), tag=tag, name=name)
            outer = gmsh.model.getBoundary(sorted(all_volumes), combined=True, oriented=False)
            stress = gmsh.model.getBoundary(mapping[1], combined=True, oriented=False)
            gmsh.model.addPhysicalGroup(2, sorted(t for d, t in outer if d == 2), tag=407, name="Far")
            gmsh.model.addPhysicalGroup(2, sorted(t for d, t in stress if d == 2), tag=508, name="Stress")
            gmsh.option.setNumber("Mesh.MeshSizeMin", 0.0007 * mesh_scale)
            gmsh.option.setNumber("Mesh.MeshSizeMax", 0.012 * mesh_scale)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 14)
            active = pm | coil | core
            if active:
                boundaries = gmsh.model.getBoundary(sorted(active), combined=True, oriented=False)
                if kind in {"coil", "torque"}:
                    boundaries += stress  # Resolve the torque integration surface as well as the sources.
                distance = gmsh.model.mesh.field.add("Distance")
                gmsh.model.mesh.field.setNumbers(distance, "SurfacesList", [t for d, t in boundaries if d == 2])
                threshold = gmsh.model.mesh.field.add("Threshold")
                gmsh.model.mesh.field.setNumber(threshold, "InField", distance)
                gmsh.model.mesh.field.setNumber(threshold, "SizeMin", 0.0007 * mesh_scale)
                gmsh.model.mesh.field.setNumber(threshold, "SizeMax", 0.012 * mesh_scale)
                gmsh.model.mesh.field.setNumber(threshold, "DistMin", 0.001)
                gmsh.model.mesh.field.setNumber(threshold, "DistMax", 0.009)
                gmsh.model.mesh.field.setAsBackgroundMesh(threshold)
            gmsh.model.mesh.generate(3)
            gmsh.write(str(target))
        finally:
            gmsh.finalize()
    materials = {"AirLaw": Material3D()}
    bodies = {"Air": "AirLaw"}
    coils = {}
    if kind != "coil":
        materials["PMLaw"] = Material3D(
            kind="permanent_magnet", relative_permeability=1.12, remanence_T=(0, 0, 1) if kind in {"sphere", "steel"} else (1, 0, 0)
        )
        bodies["Magnet"] = "PMLaw"
    if kind == "steel":
        from backend.material_contract import load_electrical_steel_curve

        materials["CoreLaw"] = Material3D(kind="bh_curve", bh_points=list(load_electrical_steel_curve("M350-50A").points))
        bodies["Core"] = "CoreLaw"
    if kind in {"coil", "torque"}:
        bodies["Coil"] = "AirLaw"
        coils["Winding"] = Coil3D(bodies=["Coil"], normal=(0, 0, 1), turns=10, current_A=current_A)
    case = Case3D(
        mesh_file=target,
        materials=materials,
        bodies=bodies,
        coils=coils,
        outer_boundary="Far",
        stress_surface="Stress",
        assumptions=["Synthetic control geometry; not hardware validation."],
    )
    if kind == "steel":
        case.numerics.nonlinear_relaxation = 0.5
    (directory / "case.json").write_text(case.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return case
