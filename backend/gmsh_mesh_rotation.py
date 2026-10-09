"""Slot-pitch congruence reuse for remesh-per-step Gmsh sweeps.

When the rotor advances by exactly one stator slot pitch, the combined
stator∪rotor geometry is a rigid rotation of an earlier rotor position:
rotating the whole plane by one slot pitch maps the stator onto itself
(slot k lands on slot k+1's position) and carries the rotor along with it.
The mesh for rotor angle θ + n·slot_pitch is therefore the mesh for θ with
every node rotated by n·slot_pitch — no Gmsh call required.

What must be fixed up on the rotated artifact:

* nodes — rigid 2D rotation by δ = n·slot_pitch.
* magnet metadata — rotates with the rotor: absolute magnetization angles
  shift by +δ. No relabeling: magnet i keeps its polarity and moves with
  the mesh, exactly as a fresh mesh at θ+δ would have it.
* stator winding metadata — the stator does NOT move physically, but the
  mesh's slot regions do. Region ``slot_winding_i`` now sits where slot
  i+n is in reality, so it must carry slot i+n's phase/direction, with
  phase currents evaluated at the target rotor angle.
* angle bookkeeping — ``rotor_angle_mech_deg`` (top level, physics
  contract motion block, mesh_info if present) becomes the target angle so
  the Rust side's explicit-metadata angle check passes.

For a full-electrical-cycle sweep this cuts Gmsh producer work by
``sweep_span_mech / slot_pitch`` (3x for 12 slots over 90° mech, 4x for
the 4-slot lesson motor over 360° mech).

Disable with COILEM_MAGNETO2D_GMSH_MESH_REUSE=0.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Callable

from backend.solver_environment import solver_setting

_SOURCE_GROUP_RE = re.compile(
    r"^winding:(?P<phase>[A-Za-z0-9]+):(?P<direction>in|out):slot(?P<index>\d+)"
    r"(?::layer(?P<layer>\d+))?$"
)
_SLOT_REGION_RE = re.compile(r"^slot_winding_(?P<index>\d+)(?:_layer(?P<layer>\d+))?$")

_ANGLE_TOL_DEG = 1.0e-6


def gmsh_mesh_reuse_enabled() -> bool:
    return solver_setting("COILEM_MAGNETO2D_GMSH_MESH_REUSE", "1") not in {
        "0",
        "false",
        "False",
    }


def gmsh_solve_reuse_enabled() -> bool:
    """Slot-pitch congruence SOLUTION reuse (skip the FEM solve, not just Gmsh).

    Requires mesh reuse to be on: a derived solve can only be synthesized from
    a base solve when the derived mesh is the rigidly rotated base mesh.
    """
    return gmsh_mesh_reuse_enabled() and solver_setting(
        "COILEM_MAGNETO2D_GMSH_SOLVE_REUSE", "1"
    ) not in {"0", "false", "False"}


def slot_pitch_deg(slot_count: int) -> float:
    return 360.0 / max(1, int(slot_count))


def slot_congruence_groups(
    mesh_jobs: list[dict[str, Any]],
    slot_count: int,
    *,
    tol_deg: float = _ANGLE_TOL_DEG,
) -> list[dict[str, Any]]:
    """Group mesh jobs whose rotor angles differ by whole slot pitches.

    Returns a list of ``{"base": job, "derived": [(job, n_slot_pitches), ...]}``
    entries. Jobs in a group share one Gmsh mesh: the ``base`` job (smallest
    rotor angle) is meshed for real and each ``derived`` job reuses it via
    ``rotate_solve_mesh_artifact``. Grouping is exact: a job only joins a
    group when its angle differs from the base by an integer number of slot
    pitches to within ``tol_deg``.
    """
    pitch = slot_pitch_deg(slot_count)
    groups: list[dict[str, Any]] = []
    ordered = sorted(mesh_jobs, key=lambda job: float(job["rotor_angle_mech_deg"]))
    for job in ordered:
        angle = float(job["rotor_angle_mech_deg"])
        placed = False
        for group in groups:
            base_angle = float(group["base"]["rotor_angle_mech_deg"])
            ratio = (angle - base_angle) / pitch
            n = round(ratio)
            if n != 0 and abs(ratio - n) * pitch <= tol_deg:
                group["derived"].append((job, int(n)))
                placed = True
                break
        if not placed:
            groups.append({"base": job, "derived": []})
    return groups


def _slot_table_from_contract(
    physics_regions: list[dict[str, Any]],
) -> dict[tuple[int, int | None], tuple[str, str]]:
    """Map (slot index, optional layer) -> (phase, direction) from the contract."""
    table: dict[tuple[int, int | None], tuple[str, str]] = {}
    for entry in physics_regions:
        source_group = entry.get("source_group")
        if not isinstance(source_group, str):
            continue
        match = _SOURCE_GROUP_RE.match(source_group)
        if match is None:
            continue
        layer_raw = match.group("layer")
        table[(int(match.group("index")), int(layer_raw) if layer_raw is not None else None)] = (
            match.group("phase"),
            match.group("direction"),
        )
    return table


def _slot_index_angular_direction(
    artifact: dict[str, Any],
    slot_indices: list[int],
) -> int:
    """Return +1 when slot index increases counter-clockwise, else -1.

    Determined empirically from the mesh (circular mean of each slot
    region's element centroid angles) so the remap does not depend on the
    geometry builder's ordering convention.
    """
    mesh = artifact["mesh"]
    nodes = mesh["nodes"]
    triangles = mesh["triangles"]
    element_region_ids = artifact["element_region_ids"]

    sin_sum: dict[int, float] = {}
    cos_sum: dict[int, float] = {}
    for tri, region_id in zip(triangles, element_region_ids):
        match = _SLOT_REGION_RE.match(str(region_id))
        if match is None:
            continue
        idx = int(match.group("index"))
        cx = sum(nodes[node][0] for node in tri) / 3.0
        cy = sum(nodes[node][1] for node in tri) / 3.0
        angle = math.atan2(cy, cx)
        sin_sum[idx] = sin_sum.get(idx, 0.0) + math.sin(angle)
        cos_sum[idx] = cos_sum.get(idx, 0.0) + math.cos(angle)

    centers = {
        idx: math.atan2(sin_sum[idx], cos_sum[idx])
        for idx in sin_sum
        if idx in cos_sum
    }
    ordered = [idx for idx in sorted(slot_indices) if idx in centers]
    if len(ordered) < 2:
        return 1
    votes = 0
    for left, right in zip(ordered, ordered[1:]):
        diff = (centers[right] - centers[left]) % (2.0 * math.pi)
        votes += 1 if diff < math.pi else -1
    return 1 if votes >= 0 else -1


def rotate_solve_mesh_artifact(
    artifact: dict[str, Any],
    *,
    slot_count: int,
    target_rotor_angle_mech_deg: float,
    phase_density_a_per_mm2: Callable[[float], dict[str, float]],
    current_angle_elec_deg_for_mech: Callable[[float], float],
    tol_deg: float = _ANGLE_TOL_DEG,
) -> dict[str, Any]:
    """Derive the solve-mesh artifact for ``target_rotor_angle_mech_deg``
    from a congruent artifact at another angle by rigid rotation.

    ``phase_density_a_per_mm2(elec_deg)`` returns per-phase current density
    in A/mm² for a resolved electrical angle; ``current_angle_elec_deg_for_mech``
    maps a mechanical rotor angle to that resolved electrical angle. Both are
    supplied by the caller so this module stays import-light and unit-testable
    without a MotorConfig.
    """
    base_angle = float(artifact.get("rotor_angle_mech_deg") or 0.0)
    delta_deg = target_rotor_angle_mech_deg - base_angle
    pitch = slot_pitch_deg(slot_count)
    ratio = delta_deg / pitch
    n_slots = round(ratio)
    if abs(ratio - n_slots) * pitch > tol_deg:
        raise ValueError(
            "rotate_solve_mesh_artifact requires a whole number of slot "
            f"pitches: delta={delta_deg:.9f}deg, slot_pitch={pitch:.9f}deg"
        )

    rotated = copy.deepcopy(artifact)
    if n_slots == 0 and abs(delta_deg) <= tol_deg:
        return rotated

    delta_rad = math.radians(delta_deg)
    cos_d = math.cos(delta_rad)
    sin_d = math.sin(delta_rad)

    # ── Nodes: rigid rotation ────────────────────────────────────────────
    rotated["mesh"]["nodes"] = [
        [x * cos_d - y * sin_d, x * sin_d + y * cos_d]
        for x, y in artifact["mesh"]["nodes"]
    ]

    # ── Rotor metadata: rotates with the mesh ────────────────────────────
    element_magnetization = rotated.get("element_magnetization")
    if element_magnetization is not None:
        rotated["element_magnetization"] = [
            ((value + delta_deg) % 360.0) if value is not None else None
            for value in element_magnetization
        ]

    # ── Stator winding metadata: slot index remap + fresh phase currents ─
    physics_contract = rotated.get("physics_contract") or {}
    contract_regions = physics_contract.get("regions") or []
    slot_table = _slot_table_from_contract(contract_regions)
    slot_indices = sorted({slot_idx for slot_idx, _layer in slot_table})
    direction_sign = (
        _slot_index_angular_direction(artifact, slot_indices)
        if slot_table
        else 1
    )
    index_shift = direction_sign * n_slots

    elec_deg = current_angle_elec_deg_for_mech(target_rotor_angle_mech_deg)
    densities_a_per_mm2 = phase_density_a_per_mm2(elec_deg)

    current_density_by_region: dict[str, float] = {}
    for entry in contract_regions:
        entry_id = str(entry.get("id") or "")
        slot_match = _SLOT_REGION_RE.match(entry_id)
        if slot_match is not None and slot_table:
            slot_idx = int(slot_match.group("index"))
            region_layer_raw = slot_match.group("layer")
            region_layer = int(region_layer_raw) if region_layer_raw is not None else None
            winding = entry.get("winding")
            if isinstance(winding, dict) and winding.get("layer") is not None:
                region_layer = int(winding["layer"])
            mapped_idx = (slot_idx + index_shift) % max(1, slot_count)
            mapped = slot_table.get((mapped_idx, region_layer)) or slot_table.get(
                (mapped_idx, None)
            )
            if mapped is None:
                raise ValueError(
                    "slot congruence remap missing winding metadata for "
                    f"slot {mapped_idx} layer {region_layer}"
                )
            phase, direction = mapped
            density = densities_a_per_mm2.get(phase, 0.0)
            if direction == "out":
                density = -density
            density_a_per_m2 = density * 1.0e6
            layer_suffix = f":layer{int(region_layer)}" if region_layer is not None else ""
            entry["source_group"] = f"winding:{phase}:{direction}:slot{slot_idx}{layer_suffix}"
            if "current_density_a_per_m2" in entry:
                entry["current_density_a_per_m2"] = density_a_per_m2
            if isinstance(winding, dict):
                winding["phase"] = phase
                winding["direction"] = direction
                winding["slot_index"] = slot_idx
                winding["current_density_a_per_m2"] = density_a_per_m2
                winding.setdefault(
                    "current_density_source",
                    "geometry_ir_winding_table",
                )
            current_density_by_region[entry_id] = density_a_per_m2
        elif "magnetization_angle_deg" in entry:
            entry["magnetization_angle_deg"] = (
                float(entry["magnetization_angle_deg"]) + delta_deg
            ) % 360.0

    element_current_density = rotated.get("element_current_density_a_per_m2")
    if element_current_density is not None and current_density_by_region:
        element_region_ids = rotated["element_region_ids"]
        rotated["element_current_density_a_per_m2"] = [
            current_density_by_region.get(str(region_id))
            if previous is not None
            else None
            for previous, region_id in zip(element_current_density, element_region_ids)
        ]

    # ── Angle bookkeeping ────────────────────────────────────────────────
    rotated["rotor_angle_mech_deg"] = float(target_rotor_angle_mech_deg)
    motion = physics_contract.get("motion")
    if isinstance(motion, dict):
        motion["rotor_angle_mech_deg"] = float(target_rotor_angle_mech_deg)
    mesh_info = rotated["mesh"].get("info")
    if isinstance(mesh_info, dict) and "rotor_angle_mech_deg" in mesh_info:
        mesh_info["rotor_angle_mech_deg"] = float(target_rotor_angle_mech_deg)

    provenance = physics_contract.get("provenance")
    if isinstance(provenance, dict):
        provenance["mesh_reuse"] = {
            "kind": "slot_pitch_congruence_rotation",
            "rotated_from_rotor_angle_mech_deg": base_angle,
            "n_slot_pitches": int(n_slots),
        }

    return rotated


def rebake_solve_mesh_artifact_currents(
    artifact: dict[str, Any],
    *,
    phase_density_a_per_mm2: Callable[[float], dict[str, float]],
    current_angle_elec_deg_for_mech: Callable[[float], float],
) -> dict[str, Any]:
    """Return a deep copy of ``artifact`` with slot currents re-baked for the
    caller's operating point at the artifact's OWN rotor angle.

    Geometry, magnetization, and winding phase/direction metadata are
    untouched — only current-density values change. This is the per-angle
    mesh-cache companion to :func:`rotate_solve_mesh_artifact`: a cached
    artifact built at one current amplitude / advance angle (gamma) becomes
    valid for another operating point by rewriting element and contract
    current densities exactly the way the producer bakes them
    (gmsh_solver._current_density_by_ir_region). This lets
    an MTPA gamma sweep mesh each rotor angle once.
    """
    rebaked = copy.deepcopy(artifact)
    rotor_angle_mech_deg = float(rebaked.get("rotor_angle_mech_deg") or 0.0)
    elec_deg = current_angle_elec_deg_for_mech(rotor_angle_mech_deg)
    densities_a_per_mm2 = phase_density_a_per_mm2(elec_deg)

    physics_contract = rebaked.get("physics_contract") or {}
    contract_regions = physics_contract.get("regions") or []
    current_density_by_region: dict[str, float] = {}
    for entry in contract_regions:
        if not isinstance(entry, dict) or entry.get("kind") != "SlotWinding":
            continue
        winding = entry.get("winding")
        if not isinstance(winding, dict):
            continue
        phase = str(winding.get("phase") or "")
        direction = str(winding.get("direction") or "in")
        density = densities_a_per_mm2.get(phase, 0.0)
        if direction == "out":
            density = -density
        density_a_per_m2 = density * 1.0e6
        entry_id = str(entry.get("id") or "")
        if "current_density_a_per_m2" in entry:
            entry["current_density_a_per_m2"] = density_a_per_m2
        if "current_density_a_per_m2" in winding:
            winding["current_density_a_per_m2"] = density_a_per_m2
        current_density_by_region[entry_id] = density_a_per_m2

    element_current_density = rebaked.get("element_current_density_a_per_m2")
    if isinstance(element_current_density, list) and current_density_by_region:
        element_region_ids = rebaked["element_region_ids"]
        rebaked["element_current_density_a_per_m2"] = [
            current_density_by_region.get(str(region_id))
            if previous is not None
            else None
            for previous, region_id in zip(element_current_density, element_region_ids)
        ]

    provenance = physics_contract.get("provenance")
    if isinstance(provenance, dict):
        provenance["mesh_reuse"] = {
            "kind": "per_angle_mesh_cache_current_rebake",
            "rotor_angle_mech_deg": rotor_angle_mech_deg,
        }

    return rebaked


# ─── Slot-pitch congruence SOLUTION reuse ────────────────────────────────────
#
# A derived artifact is the base mesh rigidly rotated, with magnet
# magnetization carried along exactly. The magnetostatic solution of the
# derived artifact is therefore exactly the rotated base solution — same A_z
# value on every (rotated) node — WHENEVER the source term also carries over,
# i.e. every element keeps the current density it had in the base artifact.
# That holds trivially for no-load solves (J = 0 everywhere) and holds for
# loaded solves when the winding pattern maps onto itself under the slot
# shift with currents evaluated at the shifted electrical angle (e.g. 8p12s:
# one slot pitch = 120° elec, a pure phase relabel for a balanced winding).
#
# When it holds, the derived report is synthesized from the base report:
# torque and energy are rotation-invariant (copied); per-slot flux/excitation
# contributions are relabeled by physical slot position (the Rust solver
# assigns slot phases from centroid angle, so the slot at position t in the
# derived mesh carries the solution integrals of base position t − n with
# position t's phase/direction); field-plot nodes are rotated so field-line
# frames stay visually correct.

_PHASE_INDEX = {"A": 0, "B": 1, "C": 2}


def slot_current_pattern_matches(
    base_artifact: dict[str, Any],
    derived_artifact: dict[str, Any],
    *,
    rel_tol: float = 1.0e-9,
) -> bool:
    """True when the derived artifact's per-element current densities equal
    the base artifact's, so the derived solve is the rotated base solve.

    Conservative on missing data: if either artifact lacks element current
    densities the answer is False (the Rust solver would synthesize currents
    natively and the equivalence cannot be established from here).
    """
    base = base_artifact.get("element_current_density_a_per_m2")
    derived = derived_artifact.get("element_current_density_a_per_m2")
    if not isinstance(base, list) or not isinstance(derived, list):
        return False
    if len(base) != len(derived):
        return False
    scale = 0.0
    for value in base:
        if value is not None:
            scale = max(scale, abs(float(value)))
    for value in derived:
        if value is not None:
            scale = max(scale, abs(float(value)))
    if scale <= 0.0:
        return True  # no-load: zero everywhere on both
    tol = rel_tol * scale
    for base_value, derived_value in zip(base, derived):
        if (base_value is None) != (derived_value is None):
            return False
        if base_value is None:
            continue
        if abs(float(base_value) - float(derived_value)) > tol:
            return False
    return True


def _direction_sign(direction: str) -> float:
    return 1.0 if str(direction) == "in" else -1.0


def _contributions_by_global_slot(
    contributions: list[dict[str, Any]],
    slot_count: int,
    *,
    what: str,
) -> dict[int, dict[str, Any]]:
    by_slot: dict[int, dict[str, Any]] = {}
    for entry in contributions:
        idx = int(entry["slot_index_global"])
        if idx in by_slot:
            raise ValueError(
                f"solution reuse requires one {what} contribution per slot; "
                f"slot {idx} appears more than once (sector model?)"
            )
        by_slot[idx] = entry
    if sorted(by_slot) != list(range(slot_count)):
        raise ValueError(
            f"solution reuse requires {what} contributions covering all "
            f"{slot_count} slots; got slots {sorted(by_slot)}"
        )
    return by_slot


def _phase_currents_from_angle(amplitude_a: float, angle_deg: float) -> list[float]:
    """Mirror of the Rust sin-convention 3-phase synthesis (sources.rs)."""
    theta = math.radians(angle_deg)
    return [
        amplitude_a * math.sin(theta),
        amplitude_a * math.sin(theta - 2.0 * math.pi / 3.0),
        amplitude_a * math.sin(theta - 4.0 * math.pi / 3.0),
    ]


def derive_congruent_solve_report(
    base_report: dict[str, Any],
    *,
    slot_count: int,
    n_slot_pitches: int,
    rotation_delta_deg: float,
    elec_delta_deg: float,
) -> dict[str, Any]:
    """Synthesize the solve report a congruent derived artifact would produce.

    ``n_slot_pitches`` is the (signed) whole number of slot pitches the rotor
    advanced from the base solve, ``rotation_delta_deg`` the mechanical
    rotation (= n_slot_pitches × slot pitch) and ``elec_delta_deg`` the
    corresponding electrical advance (= rotation × pole pairs).

    Raises ValueError when the base report does not carry the per-slot
    contribution data needed for an exact relabel; callers should fall back
    to a real solve in that case.
    """
    report = copy.deepcopy(base_report)
    results = report.get("results")
    if not isinstance(results, dict):
        raise ValueError("solution reuse requires a report with a results block")

    shift = int(n_slot_pitches) % max(1, slot_count)

    # ── Phase currents at the derived electrical angle ───────────────────
    base_source_angle = float(results["source_current_angle_deg"])
    base_phase_currents = [float(v) for v in results["phase_current_a"]]
    # Recover the amplitude from the balanced triple: Σ i² = (3/2)·I².
    amplitude = math.sqrt(
        max(0.0, sum(v * v for v in base_phase_currents) * (2.0 / 3.0))
    )
    source_angle = base_source_angle + elec_delta_deg
    phase_currents = (
        _phase_currents_from_angle(amplitude, source_angle)
        if amplitude > 0.0
        else [0.0, 0.0, 0.0]
    )
    results["source_current_angle_deg"] = source_angle
    results["phase_current_a"] = phase_currents

    # ── Flux linkage: relabel per-slot contributions by physical position ─
    flux_contributions = results.get("slot_flux_linkage_contributions")
    if not isinstance(flux_contributions, list) or not flux_contributions:
        raise ValueError(
            "solution reuse requires slot_flux_linkage_contributions in the base report"
        )
    flux_by_slot = _contributions_by_global_slot(
        flux_contributions, slot_count, what="flux-linkage"
    )
    new_flux_contributions: list[dict[str, Any]] = []
    phase_flux = [0.0, 0.0, 0.0]
    for target in range(slot_count):
        label = flux_by_slot[target]
        source = flux_by_slot[(target - shift) % slot_count]
        sign = _direction_sign(label["direction"]) * _direction_sign(source["direction"])
        entry = dict(label)
        entry["az_reference_wb_per_m"] = source["az_reference_wb_per_m"]
        entry["az_avg_wb_per_m"] = source["az_avg_wb_per_m"]
        entry["az_effective_wb_per_m"] = source["az_effective_wb_per_m"]
        entry["slot_area_m2"] = source["slot_area_m2"]
        entry["contribution_wb"] = float(source["contribution_wb"]) * sign
        new_flux_contributions.append(entry)
        phase_idx = _PHASE_INDEX.get(str(label["phase"]))
        if phase_idx is None:
            raise ValueError(f"unknown winding phase {label['phase']!r}")
        phase_flux[phase_idx] += entry["contribution_wb"]
    results["slot_flux_linkage_contributions"] = new_flux_contributions
    results["flux_linkage_a_wb"] = phase_flux[0]
    results["flux_linkage_b_wb"] = phase_flux[1]
    results["flux_linkage_c_wb"] = phase_flux[2]

    # ── Slot excitation: same positional relabel, currents recomputed ────
    excitation_contributions = results.get("slot_excitation_contributions")
    if isinstance(excitation_contributions, list) and excitation_contributions:
        excitation_by_slot = _contributions_by_global_slot(
            excitation_contributions, slot_count, what="excitation"
        )
        new_excitation_contributions: list[dict[str, Any]] = []
        for target in range(slot_count):
            label = excitation_by_slot[target]
            source = excitation_by_slot[(target - shift) % slot_count]
            entry = dict(label)
            entry["slot_area_m2"] = source["slot_area_m2"]
            entry["effective_current_density_a_per_m2"] = source[
                "effective_current_density_a_per_m2"
            ]
            entry["integrated_amp_turns_a"] = source["integrated_amp_turns_a"]
            entry["slot_current_a"] = source["slot_current_a"]
            phase_idx = _PHASE_INDEX.get(str(label["phase"]))
            if phase_idx is None:
                raise ValueError(f"unknown winding phase {label['phase']!r}")
            entry["phase_current_a"] = phase_currents[phase_idx]
            new_excitation_contributions.append(entry)
        results["slot_excitation_contributions"] = new_excitation_contributions

    # ── Field plot: rotate node coordinates so frames stay correct ───────
    field_plot = report.get("field_plot")
    if isinstance(field_plot, dict) and isinstance(field_plot.get("nodes_mm"), list):
        delta_rad = math.radians(rotation_delta_deg)
        cos_d = math.cos(delta_rad)
        sin_d = math.sin(delta_rad)
        field_plot["nodes_mm"] = [
            [x * cos_d - y * sin_d, x * sin_d + y * cos_d]
            for x, y in field_plot["nodes_mm"]
        ]

    # ── Bookkeeping: no solver work happened for this report ─────────────
    solve_info = report.get("solve_info")
    if isinstance(solve_info, dict):
        for key in ("total_time_ms", "solve_time_ms", "assembly_time_ms"):
            if key in solve_info:
                solve_info[key] = 0
        if "nonlinear_iterations" in solve_info:
            solve_info["nonlinear_iterations"] = 0
    report["solution_reuse"] = {
        "kind": "slot_pitch_congruence_rotation",
        "n_slot_pitches": int(n_slot_pitches),
        "rotation_delta_deg": float(rotation_delta_deg),
        "elec_delta_deg": float(elec_delta_deg),
    }
    return report
