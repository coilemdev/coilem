"""Explicit 3D case lowering, external process execution, and SI result extraction."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path

import meshio
import numpy as np

from backend.elmer.capabilities import discover_elmer
from backend.elmer.mesh import parse_mesh_names
from backend.elmer.process import ElmerProcessRunner, convert_with_elmergrid

from .mesh import VolumeMesh, maxwell_stress, read_mesh
from .model import Case3D

MU0 = 4e-7 * math.pi
NOTICE = "Experimental Elmer 3D finite-element integration; no motor or release qualification claim."


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_revision() -> dict:
    root = Path(__file__).resolve().parents[2]
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, timeout=5)
        return {
            "commit": head.stdout.strip() if head.returncode == 0 else None,
            "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"commit": None, "dirty": None}


def write_case(case: Case3D, mesh: VolumeMesh | None, root: Path, *, converted_names: dict[str, int] | None = None) -> Path:
    """Lower typed physics only; caller-supplied SIF/MATC fragments are not accepted."""
    for name in (*case.materials, *case.bodies, *case.coils, case.outer_boundary):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            raise ValueError(f"physical/material/coil name must be a simple identifier: {name!r}")
    n = case.numerics
    nonlinear_steel = any(law.kind == "bh_curve" for law in case.materials.values())
    if converted_names is None and mesh is None:
        raise ValueError("volume mesh or converted physical names required")
    names = converted_names if converted_names is not None else {name: tag for name, (tag, _dim) in mesh.names.items()}
    coil_solver = bool(case.coils)
    field_solver = 2 if coil_solver else 1
    calc_solver, output_solver, scalars_solver = field_solver + 1, field_solver + 2, field_solver + 3
    solvers = [field_solver, calc_solver, output_solver, scalars_solver]
    lines = [
        'Check Keywords "Warn"',
        "Header",
        '  Mesh DB "." "mesh"',
        "End",
        "Simulation",
        '  Coordinate System = "Cartesian 3D"',
        '  Simulation Type = "Steady state"',
        "  Steady State Max Iterations = 1",
        "  Max Output Level = 6",
        "End",
        "Constants",
        "  Permittivity of Vacuum = 8.8541878128e-12",
        "End",
        "Equation 1",
        f"  Active Solvers(4) = {' '.join(map(str, solvers))}",
        "End",
    ]
    if coil_solver:
        lines += [
            "Equation 2",
            f"  Active Solvers(5) = 1 {' '.join(map(str, solvers))}",
            "End",
            "Solver 1",
            '  Equation = "ClosedCoils"',
            '  Procedure = "CoilSolver" "CoilSolver"',
            "  Coil Closed = Logical True",
            "  Narrow Interface = Logical True",
            "  Use Unity Conductivity = Logical True",
            "  Calculate Elemental Fields = Logical True",
            "  Calculate Nodal Fields = Logical True",
            '  Linear System Solver = "Direct"',
            '  Linear System Direct Method = "UMFPACK"',
            "  Linear System Abort Not Converged = Logical True",
            "End",
        ]
    lines += [
        f"Solver {field_solver}",
        '  Equation = "Magnetostatics3D"',
        '  Procedure = "MagnetoDynamics" "WhitneyAVSolver"',
        '  Variable = "A"',
        "  Edge Basis = Logical True",
        f"  Use Tree Gauge = Logical {'False' if nonlinear_steel else 'True'}",
        '  Linear System Solver = "Direct"',
        '  Linear System Direct Method = "UMFPACK"',
        '  Linear System Preconditioning = "None"',
        "  Linear System Convergence Tolerance = 1e-10",
        "  Linear System Abort Not Converged = Logical True",
        f"  Newton-Raphson Iteration = Logical {'False' if nonlinear_steel else 'True'}",
        f"  Nonlinear System Max Iterations = {n.nonlinear_max_iterations}",
        f"  Nonlinear System Convergence Tolerance = {n.nonlinear_tolerance:.17e}",
        f"  Nonlinear System Relaxation Factor = {n.nonlinear_relaxation:.17e}",
        "  Nonlinear System Abort Not Converged = Logical True",
    ]
    if coil_solver:
        lines += [
            "  Use Elemental CoilCurrent = Logical True",
            "  Fix Input Current Density = Logical True",
            '  jfix: Linear System Solver = "Direct"',
            '  jfix: Linear System Direct Method = "UMFPACK"',
            "  jfix: Linear System Abort Not Converged = Logical True",
        ]
    if nonlinear_steel:
        # Scale the mixed gauge equations with vacuum reluctivity in SI units.
        # Unit coefficients leave the equivalent-linear H(B) control ill-conditioned.
        lines += ["  Use Lagrange Gauge = Logical True", f"  Lagrange Gauge Coefficient = Real {1 / MU0:.17e}",
                  f"  Lagrange Gauge Penalization Coefficient = Real {1 / MU0:.17e}",
                  "  Linear System Refactorize = Logical True"]
    lines += [
        "End",
        f"Solver {calc_solver}",
        '  Equation = "Fields3D"',
        '  Procedure = "MagnetoDynamics" "MagnetoDynamicsCalcFields"',
        '  Potential Variable = "A"',
        "  Calculate Magnetic Vector Potential = Logical True",
        "  Calculate Magnetic Flux Density = Logical True",
        "  Calculate Magnetic Field Strength = Logical True",
        "  Calculate Nodal Fields = Logical True",
        '  Linear System Solver = "Direct"',
        '  Linear System Direct Method = "UMFPACK"',
    ]
    if coil_solver:
        lines += [
            "  Calculate Current Density = Logical True",
            "  Calculate Flux Linkage = Logical True",
            '  Flux Linkage Current Name = String "CoilCurrent e"',
        ]
    lines += [
        "End",
        f"Solver {output_solver}",
        '  Exec Solver = "After Timestep"',
        '  Procedure = "ResultOutputSolve" "ResultOutputSolver"',
        '  Output File Name = "fields"',
        "  Vtu Format = Logical True",
        "  Binary Output = Logical True",
        "  Single Precision = Logical False",
        '  Vector Field 1 = "magnetic flux density"',
        '  Vector Field 2 = "magnetic vector potential"',
        '  Vector Field 3 = "magnetic field strength"',
        "  Save Geometry IDs = Logical True",
        "  Save Bulk Only = Logical True",
        "End",
        f"Solver {scalars_solver}",
        '  Exec Solver = "After Timestep"',
        '  Procedure = "SaveData" "SaveScalars"',
        '  Filename = "scalars.dat"',
        "  Save Component Results = Logical True",
        "End",
    ]
    material_numbers = {name: i for i, name in enumerate(case.materials, 1)}
    for name, law in case.materials.items():
        number = material_numbers[name]
        lines += [f"Material {number}", f'  Name = "{name}"', "  Electric Conductivity = Real 0.0", "  Relative Permittivity = Real 1.0"]
        if law.kind == "bh_curve":
            curve_name = f"material_{number}.dat"
            (root / curve_name).write_text("".join(f"{b:.17e} {h:.17e}\n" for b, h in law.bh_points), encoding="utf-8")
            # Use the documented H(B) dependent-table form, with B/H columns.
            lines += ['  H-B Curve = Variable "dummy"', "    Real", f'      Include "{curve_name}"', "    End"]
        else:
            lines += [f"  Relative Permeability = Real {law.relative_permeability:.17e}"]
            if law.kind == "permanent_magnet":
                for i, br in enumerate(law.remanence_T, 1):
                    lines += [f"  Magnetization {i} = Real {br / (MU0 * law.relative_permeability):.17e}"]
        lines += ["End"]
    body_numbers = {name: i for i, name in enumerate(case.bodies, 1)}
    coil_bodies = {body: i for i, coil in enumerate(case.coils.values(), 1) for body in coil.bodies}
    for body, material in case.bodies.items():
        lines += [
            f"Body {body_numbers[body]}",
            f'  Name = "{body}"',
            f"  Target Bodies(1) = {names[body]}",
            f"  Equation = {2 if body in coil_bodies else 1}",
            f"  Material = {material_numbers[material]}",
        ]
        if body in coil_bodies:
            lines += [f"  Body Force = {coil_bodies[body]}", f"  Component = Integer {coil_bodies[body]}"]
        lines += ["End"]
    for i, (name, coil) in enumerate(case.coils.items(), 1):
        # Elmer's cut-normal convention is opposite to the right-hand loop
        # normal in this contract (verified with the circular-coil control).
        normal = -np.asarray(coil.normal) / np.linalg.norm(coil.normal)
        lines += [
            f"Body Force {i}",
            f"  Current Density Multiplier = Real {coil.turns * coil.current_A:.17e}",
            "End",
            f"Component {i}",
            f'  Name = "{name}"',
            f"  Master Bodies({len(coil.bodies)}) = {' '.join(str(body_numbers[b]) for b in coil.bodies)}",
            "  Coil Closed = Logical True",
            "  Desired Coil Current = Real 1.0",
            f"  Coil Normal(3) = {' '.join(f'{v:.17e}' for v in normal)}",
            # CoilCurrent is already a normalized 1 A current-density field.
            "  Electrode Area = Real 1.0",
            "End",
        ]
    lines += ["Boundary Condition 1", f"  Target Boundaries(1) = {names[case.outer_boundary]}", "  A {e} = Real 0.0", "  jfix = Real 0.0"]
    if nonlinear_steel:
        lines += ["  A = Real 0.0"]
    lines += ["End"]
    target = root / "case.sif"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "ELMERSOLVER_STARTINFO").write_text("case.sif\n", encoding="utf-8")
    return target


def read_vectors(path: Path, original_points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Read full nodal vectors and map by coordinates; Elmer may reorder mesh nodes."""
    result = meshio.read(path)
    # ElmerGrid writes decimal mesh coordinates, with small roundoff relative to
    # Gmsh's doubles. Neighbor bins avoid rounding-boundary mismatches.
    tolerance = 1e-10 * max(1.0, float(np.ptp(original_points, axis=0).max()))
    lookup = {}
    for i, point in enumerate(result.points):
        key = tuple(np.floor(point / tolerance).astype(np.int64))
        lookup.setdefault(key, []).append(i)
    permutation = []
    for point in original_points:
        key = np.floor(point / tolerance).astype(np.int64)
        candidates = [
            i
            for offset in itertools.product((-1, 0, 1), repeat=3)
            for i in lookup.get(tuple(key + offset), [])
            if np.linalg.norm(point - result.points[i]) <= tolerance
        ]
        if len(candidates) != 1:
            raise ValueError("VTU coordinates do not uniquely match the input volume mesh")
        permutation.append(candidates[0])

    def vector(label):
        for key, values in result.point_data.items():
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if normalized == label:
                array = np.asarray(values, dtype=float)
                if array.shape != (len(result.points), 3) or not np.isfinite(array).all():
                    raise ValueError(f"invalid three-component field: {key}")
                return array[permutation]
        raise ValueError(f"missing vector field {label}; available: {sorted(result.point_data)}")

    return vector("magneticvectorpotential"), vector("magneticfluxdensity")


def coil_linkages(case: Case3D, root: Path) -> dict[str, float]:
    if not case.coils:
        return {}
    names_path, data_path = root / "scalars.dat.names", root / "scalars.dat"
    descriptions = names_path.read_text(encoding="utf-8").splitlines()
    rows = [line for line in data_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    values = [float(v.replace("D", "E").replace("d", "e")) for v in rows[-1].split()]
    result = {}
    for component, (name, coil) in enumerate(case.coils.items(), 1):
        matches = []
        for line in descriptions:
            match = re.match(r"\s*(\d+)\s*:\s*(.*)", line)
            if match and re.search(rf"component\s+{component}:\s*res:\s*flux linkage\s*$", match[2], re.IGNORECASE):
                matches.append(values[int(match[1]) - 1] * coil.turns)
        if len(matches) != 1 or not math.isfinite(matches[0]):
            raise ValueError(f"missing or ambiguous normalized flux linkage for {name}")
        result[name] = matches[0]
    return result


def field_convergence(stdout: str, tolerance: float) -> dict:
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
    changes = re.findall(
        rf"ComputeChange:\s+NS\s+\(ITER=\s*(\d+)\).*?\(NRM,RELC\):\s*\(\s*({number})\s+({number})\s*\)"
        r"\s*::\s*magnetostatics3d\b",
        stdout,
        re.IGNORECASE,
    )
    if not changes:
        raise ValueError("missing field-solver convergence evidence")
    iteration, norm_text, change_text = changes[-1]
    norm, change = (float(v.replace("D", "E").replace("d", "e")) for v in (norm_text, change_text))
    if not math.isfinite(norm) or not math.isfinite(change) or change > tolerance:
        raise ValueError(f"field solver did not converge: final relative change {change}, tolerance {tolerance}")
    return {
        "iterations": int(iteration),
        "final_relative_change": change,
        "tolerance": tolerance,
        "criterion": "Elmer nonlinear iterate change; not a discretization-error estimate",
    }


def solve_case(case: Case3D, *, output_dir: Path, elmer_home: Path | None = None, runner: ElmerProcessRunner | None = None) -> dict:
    """Run one immutable explicit case; preserve all meshes, fields and failure logs."""
    case = Case3D.model_validate(case.model_dump())
    root = Path(output_dir).resolve()
    if root.exists():
        raise FileExistsError(f"output directory already exists: {root}")
    source_mesh = case.mesh_file.resolve(strict=True)
    mesh = read_mesh(case, source_mesh)
    runtime = discover_elmer(configured_home=elmer_home).require_available(qualified=False)
    root.mkdir(parents=True, exist_ok=False)
    runner = runner or ElmerProcessRunner()
    started = time.monotonic()
    record = {
        "schema_version": "coilem.elmer3d_result/v1",
        "status": "RUNNING",
        "experimental": True,
        "qualified": False,
        "notice": NOTICE,
        "request": case.model_dump(mode="json"),
        "runtime": runtime.health_payload(),
        "source": source_revision(),
        "mesh_sha256": sha256(source_mesh),
        "nodes": len(mesh.mesh.points),
        "tetrahedra": len(mesh.tetra),
        "integration_source_sha256": {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
    }
    record["runtime"]["qualified"] = False  # The 2D discovery profile does not qualify 3D.
    record["runtime"]["profile"] = "coilem_elmer_motor_3d/experimental_v1"

    def save():
        record["elapsed_s"] = time.monotonic() - started
        (root / "result.json").write_text(json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    save()
    try:
        shutil.copyfile(source_mesh, root / "input.msh")
        convert_with_elmergrid(
            runner, grid_path=runtime.grid_path, gmsh_path=root / "input.msh", mesh_dir=root / "mesh", timeout_s=case.numerics.timeout_s
        )
        names = parse_mesh_names(root / "mesh" / "mesh.names")
        required_names = {*case.bodies, case.outer_boundary}
        if not required_names <= names.keys():
            raise ValueError(f"ElmerGrid lost physical groups: {sorted(required_names - names.keys())}")
        counts = [int(v) for v in (root / "mesh" / "mesh.header").read_text().splitlines()[0].split()]
        if counts[:2] != [len(mesh.mesh.points), len(mesh.tetra)]:
            raise ValueError("ElmerGrid changed the volume mesh node/element counts")
        sif = write_case(case, mesh, root, converted_names=names)
        record["sif_sha256"] = sha256(sif)
        completed = runner.run([runtime.solver_path, "case.sif"], cwd=root, timeout_s=case.numerics.timeout_s, log_prefix="elmersolver")
        if re.search(r"\b(FATAL|ERROR)\b", completed.stdout + completed.stderr):
            raise ValueError("Elmer reported an error; inspect retained solver logs")
        if "*** Elmer Solver: ALL DONE ***" not in completed.stdout:
            raise ValueError("missing Elmer completion marker; inspect retained solver logs")
        record["convergence"] = field_convergence(completed.stdout, case.numerics.nonlinear_tolerance)
        outputs = sorted(root.rglob("fields*.vtu"))
        if len(outputs) != 1:
            raise ValueError(f"expected one 3D field result, found {len(outputs)}")
        a, b = read_vectors(outputs[0], mesh.mesh.points)
        record["material_range_checks"] = {}
        for body, material in case.bodies.items():
            law = case.materials[material]
            if law.kind == "bh_curve":
                selected = mesh.tetra[mesh.body_ids == mesh.names[body][0]]
                peak = float(np.linalg.norm(b[np.unique(selected)], axis=1).max())
                record["material_range_checks"][body] = {"peak_nodal_b_T": peak, "table_max_b_T": law.bh_points[-1][0]}
                if peak > law.bh_points[-1][0] * (1 + 1e-6):
                    raise ValueError(f"H-B curve range exceeded in {body}: {peak:g} T > {law.bh_points[-1][0]:g} T")
        np.savez_compressed(
            root / "fields.npz", nodes_m=mesh.mesh.points, tetrahedra=mesh.tetra, body_ids=mesh.body_ids, magnetic_a_Wb_per_m=a, magnetic_b_T=b
        )
        record["phase_or_coil_flux_linkage_Wb"] = coil_linkages(case, root)
        record["peak_nodal_b_T"] = float(np.linalg.norm(b, axis=1).max())
        if case.stress_surface:
            record["stress"] = maxwell_stress(mesh, case.stress_surface, b, case.torque_origin_m)
        record["status"] = "COMPLETE"
        record["fields_vtu"] = outputs[0].relative_to(root).as_posix()
        record["fields_npz"] = "fields.npz"
        save()
        return record
    except Exception as exc:
        record["status"] = "FAILED"
        record["error"] = f"{type(exc).__name__}: {exc}"
        save()
        raise
