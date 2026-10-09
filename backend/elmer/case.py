"""Typed lowering of coilEM motor physics into an Elmer SIF case."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend.material_catalog import MAGNET_PROPERTIES
from backend.material_contract import load_electrical_steel_curve
from backend.models import MotorConfig

from .errors import ElmerCaseGenerationError
from .mesh import ElmerMeshManifest

MU0 = 4.0e-7 * math.pi


@dataclass(frozen=True)
class ElmerBodyRecord:
    body_number: int
    target_body_id: int
    region_id: str
    geometry_ir_kind: str
    material_number: int
    body_force_number: int | None
    motion_group: str


@dataclass(frozen=True)
class ElmerCaseManifest:
    schema_version: str
    sif_path: str
    sif_sha256: str
    bh_curve_path: str
    bh_curve_sha256: str
    outer_boundary_id: int
    airgap_inner_radius_m: float
    airgap_outer_radius_m: float
    bodies: tuple[ElmerBodyRecord, ...]

    def write(self, path: Path) -> None:
        payload = asdict(self)
        payload["bodies"] = [asdict(body) for body in self.bodies]
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ElmerCaseGenerationError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ElmerCaseGenerationError(f"{label} must be finite")
    return number


def _is_steel(material_key: str) -> bool:
    return material_key.startswith("steel:") or material_key in {
        "M350-50A",
        "M19",
        "M27",
        "M36",
        "NO20",
        "NO27",
        "1018_steel",
    }


def _steel_grade(material_key: str) -> str:
    return material_key.split(":")[-1]


def write_elmer_case(
    *,
    config: MotorConfig,
    solve_mesh_artifact: dict[str, Any],
    mesh_manifest: ElmerMeshManifest,
    converted_names: dict[str, int],
    case_dir: str | Path,
    profile: dict[str, Any],
) -> ElmerCaseManifest:
    """Create deterministic `case.sif`, B-H data, and a case manifest."""

    root = Path(case_dir)
    root.mkdir(parents=True, exist_ok=True)
    contracts = ((solve_mesh_artifact.get("physics_contract") or {}).get("regions") or [])
    if not contracts:
        raise ElmerCaseGenerationError("Solve mesh artifact has no physics-contract regions")
    contract_by_id = {str(region["id"]): region for region in contracts}
    used_region_ids = set(str(value) for value in solve_mesh_artifact.get("element_region_ids") or [])
    ordered_regions = [
        contract_by_id[region_id]
        for region_id in mesh_manifest.region_physical_ids
        if region_id in used_region_ids
    ]

    configured_steel = {config.materials.stator_steel, config.materials.rotor_steel}
    if configured_steel != {"M350-50A"}:
        raise ElmerCaseGenerationError(
            "Elmer v1 requires M350-50A for both stator and rotor steel; "
            f"got {sorted(configured_steel)}"
        )
    curve = load_electrical_steel_curve("M350-50A")
    bh_path = root / "material_M350-50A.dat"
    bh_path.write_text(
        "\n".join(f"{b_t:.17e} {h_a_per_m:.17e}" for b_t, h_a_per_m in curve.points) + "\n",
        encoding="utf-8",
    )

    body_records: list[ElmerBodyRecord] = []
    body_force_blocks: list[str] = []
    magnet_material_blocks: list[str] = []
    next_body_force = 1
    next_magnet_material = 10
    airgap_body_number: int | None = None
    rotor_body_numbers: list[int] = []
    body_blocks: list[str] = []

    for body_number, region in enumerate(ordered_regions, start=1):
        region_id = str(region["id"])
        physical_name = mesh_manifest.region_physical_names[region_id]
        if physical_name not in converted_names:
            raise ElmerCaseGenerationError(f"Converted mesh has no body named {physical_name}")
        target_id = int(converted_names[physical_name])
        geometry_kind = str(region.get("geometry_ir_kind") or region.get("kind") or "")
        material_key = str(region.get("material") or "")
        material_number = 1
        body_force_number: int | None = None

        if _is_steel(material_key):
            if _steel_grade(material_key) != "M350-50A":
                raise ElmerCaseGenerationError(f"Unsupported Elmer steel material: {material_key}")
            material_number = 2
        elif geometry_kind == "Magnet":
            props = MAGNET_PROPERTIES.get(config.materials.magnet_grade)
            if props is None:
                raise ElmerCaseGenerationError(
                    f"Unsupported Elmer magnet grade: {config.materials.magnet_grade}"
                )
            angle_deg = _finite(region.get("magnetization_angle_deg"), f"{region_id} magnet angle")
            direction_x = math.cos(math.radians(angle_deg))
            direction_y = math.sin(math.radians(angle_deg))
            mu_r = _finite(props["relative_permeability"], "magnet relative permeability")
            remanence_t = _finite(props["remanence_T"], "magnet remanence")
            magnetization = remanence_t / (MU0 * mu_r)
            material_number = next_magnet_material
            next_magnet_material += 1
            magnet_material_blocks.append(
                "\n".join(
                    (
                        f"Material {material_number}",
                        f'  Name = "{region_id}"',
                        "  Electric Conductivity = Real 0.0",
                        f"  Relative Permeability = Real {mu_r:.17e}",
                        "  Relative Permittivity = Real 1.0",
                        f"  Magnetization 1 = Real {magnetization * direction_x:.17e}",
                        f"  Magnetization 2 = Real {magnetization * direction_y:.17e}",
                        "End",
                    )
                )
            )
        elif geometry_kind == "SlotWinding":
            body_force_number = next_body_force
            next_body_force += 1
            current_density = _finite(
                region.get("current_density_a_per_m2", 0.0),
                f"{region_id} current density",
            )
            body_force_blocks.append(
                "\n".join(
                    (
                        f"Body Force {body_force_number}",
                        f'  Name = "current_{region_id}"',
                        f"  Current Density = Real {current_density:.17e}",
                        "  Calculate Potential = Logical True",
                        "End",
                    )
                )
            )

        lines = [
            f"Body {body_number}",
            f'  Name = "{region_id}"',
            f"  Target Bodies(1) = Integer {target_id}",
            "  Equation = Integer 1",
            f"  Material = Integer {material_number}",
        ]
        if body_force_number is not None:
            lines.append(f"  Body Force = Integer {body_force_number}")
        if geometry_kind == "Airgap":
            airgap_body_number = body_number
            mesh_info = (solve_mesh_artifact.get("mesh") or {}).get("info") or {}
            inner_m = _finite(mesh_info.get("airgap_inner_radius_mm"), "airgap inner radius") * 1.0e-3
            outer_m = _finite(mesh_info.get("airgap_outer_radius_mm"), "airgap outer radius") * 1.0e-3
            if not 0.0 < inner_m < outer_m:
                raise ElmerCaseGenerationError(
                    f"Invalid Arkkio annulus {inner_m:.6e}..{outer_m:.6e} m"
                )
            lines.extend(
                (
                    f"  R Inner = Real {inner_m:.17e}",
                    f"  R Outer = Real {outer_m:.17e}",
                )
            )
        lines.append("End")
        body_blocks.append("\n".join(lines))
        motion_group = str(region.get("motion_group") or "none")
        if motion_group in {"rotor", "sliding_airgap"} and geometry_kind != "Airgap":
            rotor_body_numbers.append(body_number)
        body_records.append(
            ElmerBodyRecord(
                body_number=body_number,
                target_body_id=target_id,
                region_id=region_id,
                geometry_ir_kind=geometry_kind,
                material_number=material_number,
                body_force_number=body_force_number,
                motion_group=motion_group,
            )
        )

    if airgap_body_number is None:
        raise ElmerCaseGenerationError("No Airgap body is available for Arkkio torque")
    if not rotor_body_numbers:
        raise ElmerCaseGenerationError("No rotor bodies are available for torque witness")
    outer_name = mesh_manifest.outer_boundary_physical_name
    if outer_name not in converted_names:
        raise ElmerCaseGenerationError(f"Converted mesh has no boundary named {outer_name}")
    outer_boundary_id = int(converted_names[outer_name])

    linear = profile["linear_solver"]
    nonlinear = profile["nonlinear_solver"]
    sif = f'''Check Keywords "Warn"

Header
  Mesh DB "." "mesh"
End

Simulation
  Max Output Level = 8
  Coordinate System = "Cartesian 2D"
  Simulation Type = "Steady state"
  Steady State Max Iterations = 1
  Output Intervals = 1
  Post File = "case.vtu"
End

Constants
  Permittivity of Vacuum = 8.8541878128e-12
End

Equation 1
  Name = "Magnetostatic 2D"
  Active Solvers(4) = 1 2 3 4
End

Solver 1
  Equation = "MagnetoDynamics2D"
  Variable = "A"
  Variable DOFs = 1
  Procedure = "MagnetoDynamics2D" "MagnetoDynamics2D"
  Nonlinear System Max Iterations = Integer {int(nonlinear['max_iterations'])}
  Nonlinear System Convergence Tolerance = Real {float(nonlinear['convergence_tolerance']):.17e}
  Nonlinear System Relaxation Factor = Real {float(nonlinear['relaxation_factor']):.17e}
  Nonlinear System Abort Not Converged = Logical True
  Linear System Solver = "{linear['type']}"
  Linear System Direct Method = "{linear['method']}"
  Linear System Convergence Tolerance = Real {float(linear['convergence_tolerance']):.17e}
End

Solver 2
  Equation = "MagnetoDynamicsCalcFields"
  Procedure = "MagnetoDynamics" "MagnetoDynamicsCalcFields"
  Potential Variable = "A"
  Calculate Magnetic Vector Potential = Logical True
  Calculate Magnetic Flux Density = Logical True
  Calculate Magnetic Field Strength = Logical True
  Calculate Nodal Fields = Logical True
  Calculate Elemental Fields = Logical True
  Calculate Nodal Forces = Logical True
  Linear System Solver = "{linear['type']}"
  Linear System Direct Method = "{linear['method']}"
End

Solver 3
  Exec Solver = "After Timestep"
  Equation = "ResultOutput"
  Procedure = "ResultOutputSolve" "ResultOutputSolver"
  Output File Name = "case"
  Save Geometry IDs = Logical True
  Vtu Format = Logical True
  Binary Output = Logical False
End

Solver 4
  Exec Solver = "After Timestep"
  Equation = "SaveScalars"
  Procedure = "SaveData" "SaveScalars"
  Filename = "scalars.dat"
  Save Component Results = Logical True
End

Material 1
  Name = "Air"
  Electric Conductivity = Real 0.0
  Relative Permeability = Real 1.0
  Relative Permittivity = Real 1.0
End

Material 2
  Name = "M350-50A"
  Electric Conductivity = Real 0.0
  Relative Permittivity = Real 1.0
  H-B Curve ({len(curve.points)},2) = Real
    Include "{bh_path.name}"
End

{chr(10).join(magnet_material_blocks)}

{chr(10).join(body_force_blocks)}

{chr(10).join(body_blocks)}

Component 1
  Name = "Rotating_Domains"
  Master Bodies({len(rotor_body_numbers)}) = Integer {' '.join(str(value) for value in rotor_body_numbers)}
  Calculate Magnetic Torque = Logical True
End

Boundary Condition 1
  Name = "outer_Az_zero"
  Target Boundaries(1) = Integer {outer_boundary_id}
  A = Real 0.0
End
'''
    sif_path = root / "case.sif"
    sif_path.write_text(sif, encoding="utf-8")
    (root / "ELMERSOLVER_STARTINFO").write_text("case.sif\n", encoding="utf-8")
    mesh_info = (solve_mesh_artifact.get("mesh") or {}).get("info") or {}
    manifest = ElmerCaseManifest(
        schema_version="openem.elmer_case_manifest/v1",
        sif_path=str(sif_path),
        sif_sha256=_sha256(sif_path),
        bh_curve_path=str(bh_path),
        bh_curve_sha256=_sha256(bh_path),
        outer_boundary_id=outer_boundary_id,
        airgap_inner_radius_m=float(mesh_info["airgap_inner_radius_mm"]) * 1.0e-3,
        airgap_outer_radius_m=float(mesh_info["airgap_outer_radius_mm"]) * 1.0e-3,
        bodies=tuple(body_records),
    )
    manifest.write(root / "case_manifest.json")
    return manifest
