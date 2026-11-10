"""FEMM result extraction methods.

Extracted from femm_solver.py for maintainability.
Contains all methods for extracting electromagnetic results from FEMM:
- Torque extraction via block integrals
- Flux linkage extraction per phase
- Flux density map sampling (airgap, teeth, yoke)
- Flux density grid extraction (S4-12)
"""

from __future__ import annotations

import logging
import math
import platform
import re
import time
from typing import Any

import numpy as np

from backend.geometry_drawer import (
    MotorGeometry,
    SlotPlacement,
    compute_geometry,
    current_angle_elec_deg_for_rotor_elec,
    get_native_path_from_wine_path,
)
from backend.logging_utils import tagged_log
from backend.models import (
    FluxDensityMap,
    MotorConfig,
    Node,
)
from backend.winding_utils import (
    SlotLayerAssignment,
    distributed_full_pitch_slots,
    distributed_slot_layer_assignments,
    flux_linkage_slot_side_turn_factor,
)

logger = logging.getLogger(__name__)


_FEMM_HEADER_RE = re.compile(r"^\[(\w+)\]\s*=\s*(.*?)$")
_FEMM_BLOCKNAME_RE = re.compile(r'^\s*<BlockName>\s*=\s*"([^"]*)"\s*$')
_FEMM_KV_RE = re.compile(r"^\s*<(\w+)>\s*=\s*(.*?)\s*$")


def _parse_float_token(raw: str, default: float | None = None) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _parse_int_token(raw: str, default: int | None = None) -> int | None:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _parse_femm_block_label_metadata(fem_path: str) -> list[dict[str, Any]]:
    """Parse FEMM block-label metadata from a saved ``.fem`` file.

    The solved ``.ans`` element rows carry only an integer label pointer. The
    material name and magnetization angle for that pointer live in the
    ``[NumBlockLabels]`` section of the source ``.fem`` file, with the material
    name resolved through ``[BlockProps]``.
    """

    native_fem = get_native_path_from_wine_path(fem_path)
    try:
        lines = open(native_fem, encoding="latin-1", errors="replace").read().splitlines()
    except OSError as exc:
        tagged_log(f"[FEMM] disk-extract: could not read .fem block labels: {exc}")
        return []

    block_props: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        match = _FEMM_HEADER_RE.match(lines[i])
        if not match:
            i += 1
            continue
        key, value = match.group(1), match.group(2).strip()
        if key == "BlockProps":
            count = _parse_int_token(value, 0) or 0
            i += 1
            parsed = 0
            while parsed < count and i < len(lines):
                if "<BeginBlock>" not in lines[i]:
                    i += 1
                    continue
                block: dict[str, Any] = {
                    "name": "",
                    "h_c": 0.0,
                    "current_density_a_per_mm2": None,
                }
                i += 1
                while i < len(lines) and "<EndBlock>" not in lines[i]:
                    name_match = _FEMM_BLOCKNAME_RE.match(lines[i])
                    if name_match:
                        block["name"] = name_match.group(1)
                    kv_match = _FEMM_KV_RE.match(lines[i])
                    if kv_match:
                        key = kv_match.group(1)
                        if key == "H_c":
                            block["h_c"] = _parse_float_token(kv_match.group(2), 0.0) or 0.0
                        elif key in {"J", "J_re"}:
                            block["current_density_a_per_mm2"] = _parse_float_token(
                                kv_match.group(2)
                            )
                    i += 1
                block_props.append(block)
                parsed += 1
                i += 1
            continue
        if key == "NumBlockLabels":
            count = _parse_int_token(value, 0) or 0
            i += 1
            for label_index in range(count):
                if i >= len(lines):
                    break
                parts = lines[i].split()
                i += 1
                if len(parts) < 3:
                    continue
                block_prop_index = (_parse_int_token(parts[2], 0) or 0) - 1
                block = (
                    block_props[block_prop_index]
                    if 0 <= block_prop_index < len(block_props)
                    else {"name": "", "h_c": 0.0, "current_density_a_per_mm2": None}
                )
                magdir_deg = _parse_float_token(parts[5]) if len(parts) > 5 else None
                group = _parse_int_token(parts[6], 0) if len(parts) > 6 else 0
                name = str(block.get("name") or "")
                h_c = float(block.get("h_c") or 0.0)
                current_density_a_per_mm2 = block.get("current_density_a_per_mm2")
                labels.append(
                    {
                        "index": label_index,
                        "block_prop_index": block_prop_index,
                        "block_name": name,
                        "magnetization_angle_deg": magdir_deg,
                        "current_density_a_per_m2": (
                            float(current_density_a_per_mm2) * 1.0e6
                            if current_density_a_per_mm2 is not None
                            else None
                        ),
                        "group": group,
                        "is_magnet": abs(h_c) > 0.0 or "magnet" in name.lower(),
                    }
                )
            continue
        i += 1
    return labels


def _resolve_femm_element_label_index(raw_label: int | None, label_count: int) -> int | None:
    if raw_label is None or raw_label < 0 or label_count <= 0:
        return None
    # FEMM .ans files generated by FEMM 4.2 under Wine use 0-based pointers
    # into the .fem [NumBlockLabels] table. Preserve that as the primary
    # convention; a 1-based value exactly equal to label_count remains a
    # tolerant fallback for exporter variants that include the last label as N.
    if 0 <= raw_label < label_count:
        return raw_label
    if raw_label == label_count:
        return raw_label - 1
    return None


def _read_femm_mesh_from_disk(fem_path: str) -> dict[str, Any] | None:
    """Parse FEMM's ``.ans`` solution file into the same dict shape
    ``_extract_mesh`` returns.

    Why .ans and not .nod/.ele: FEMM 4.2 under Wine does NOT persist the
    Triangle mesh files separately. Confirmed by listing
    ~/.wine/drive_c/openem_tmp on a real run — only .fem and .ans
    appear. The mesh data is embedded in the .ans file in plain ASCII
    after a ``[Solution]`` marker, alongside the field solution.

    .ans format (relevant slice):

        ... header / problem definition ...
        [Solution]
        <n_nodes>
        <x> <y> <A_z> <boundary_flag>           ×  n_nodes
        <n_elements>
        <n1> <n2> <n3> <i_label> <group> <h>    ×  n_elements
        ...

    Node indices in the element rows are **0-based** in the .ans
    file (different from Triangle's .ele which is 1-based — important).

    Returns ``None`` if the .ans file or [Solution] marker isn't found
    (caller falls back to mo_* IPC). Raises on malformed solution body
    so we don't silently return a partial mesh.
    """
    import os

    native_fem = get_native_path_from_wine_path(fem_path)
    base, _ = os.path.splitext(native_fem)
    ans_path = base + ".ans"
    tagged_log(
        f"[FEMM] disk-extract: looking for {os.path.basename(ans_path)!r} "
        f"in {os.path.dirname(native_fem)}"
    )

    if not os.path.exists(ans_path):
        try:
            siblings = sorted(
                f for f in os.listdir(os.path.dirname(native_fem))
                if f.startswith(os.path.basename(base))
            )
            tagged_log(
                f"[FEMM] disk-extract: .ans file not found. "
                f"Matching siblings: {siblings}"
            )
        except OSError as exc:
            tagged_log(f"[FEMM] disk-extract: .ans not found, dir listing failed: {exc}")
        return None

    with open(ans_path, encoding="latin-1", errors="replace") as f:
        lines = f.read().splitlines()

    marker = "[Solution]"
    sol_idx = next((idx for idx, line in enumerate(lines) if line.strip() == marker), -1)
    if sol_idx < 0:
        tagged_log(
            f"[FEMM] disk-extract: '{marker}' not found in "
            f"{os.path.basename(ans_path)} ({sum(len(line) for line in lines)} bytes)"
        )
        return None

    pos = sol_idx + 1
    if pos >= len(lines):
        tagged_log("[FEMM] disk-extract: empty body after [Solution]")
        return None

    n_nodes = int(lines[pos].strip())
    pos += 1

    # Each node row: x, y, A_z, boundary_flag → 4 tokens. Always capture
    # A_z too — it costs ~nothing during parse and the field-preview
    # endpoint needs it. Mesh-only callers ignore the az_nodal field.
    nodes_mm: list[list[float]] = []
    az_nodal: list[float] = []
    for _ in range(n_nodes):
        if pos >= len(lines):
            raise ValueError(
                f".ans truncated in node section at node {len(nodes_mm)}/{n_nodes}"
            )
        parts = lines[pos].split()
        pos += 1
        if len(parts) < 4:
            raise ValueError(
                f".ans malformed node row at node {len(nodes_mm)}/{n_nodes}: {parts!r}"
            )
        x = float(parts[0])
        y = float(parts[1])
        az = float(parts[2])
        nodes_mm.append([x, y])
        az_nodal.append(az)

    if pos >= len(lines):
        raise ValueError(".ans missing element count after node section")
    n_elems = int(lines[pos].strip())
    pos += 1

    block_labels = _parse_femm_block_label_metadata(fem_path)
    triangles: list[list[int]] = []
    element_labels: list[int | None] = []
    element_groups: list[int | None] = []
    element_label_names: list[str | None] = []
    element_magnetization_angles_deg: list[float | None] = []
    element_current_density_a_per_m2: list[float | None] = []
    for _ in range(n_elems):
        if pos >= len(lines):
            raise ValueError(
                f".ans truncated in element section at element {len(triangles)}/{n_elems}"
            )
        parts = lines[pos].split()
        pos += 1
        if len(parts) < 3:
            raise ValueError(
                f".ans malformed element row at element {len(triangles)}/{n_elems}: {parts!r}"
            )
        n1 = int(parts[0])
        n2 = int(parts[1])
        n3 = int(parts[2])
        triangles.append([n1, n2, n3])
        raw_label = _parse_int_token(parts[3]) if len(parts) > 3 else None
        group = _parse_int_token(parts[4]) if len(parts) > 4 else None
        label_index = _resolve_femm_element_label_index(raw_label, len(block_labels))
        label = block_labels[label_index] if label_index is not None else None
        element_labels.append(raw_label)
        element_groups.append(group)
        element_label_names.append(str(label["block_name"]) if label else None)
        element_magnetization_angles_deg.append(
            float(label["magnetization_angle_deg"])
            if label and label.get("is_magnet") and label.get("magnetization_angle_deg") is not None
            else None
        )
        element_current_density_a_per_m2.append(
            float(label["current_density_a_per_m2"])
            if label and label.get("current_density_a_per_m2") is not None
            else None
        )

    tagged_log(
        f"[FEMM] disk-extract: parsed .ans · {n_nodes} nodes, "
        f"{n_elems} triangles"
    )
    result: dict[str, Any] = {
        "nodes_mm": nodes_mm,
        "triangles": triangles,
        "num_nodes": n_nodes,
        "num_triangles": n_elems,
        "az_nodal": az_nodal,
    }
    if any(label is not None for label in element_labels):
        result.update(
            {
                "element_labels": element_labels,
                "element_groups": element_groups,
                "element_label_names": element_label_names,
                "element_magnetization_angles_deg": element_magnetization_angles_deg,
                "element_current_density_a_per_m2": element_current_density_a_per_m2,
            }
        )
    return result


class FEMMTorqueExtractionError(RuntimeError):
    """Raised when FEMM's torque block-integral fails at a specific rotor
    position.

    Historically ``_extract_torque`` swallowed these and returned 0.0, which
    silently contaminated downstream parity analysis: a single dropped
    sample in a rotor sweep produces a flat odd-k leakage signature in the
    FFT that is indistinguishable from a real solver harmonic bug (observed
    2026-04-20 on spm_4p12s_simple, where θ=40° / θ=220° both dropped to
    0.0 and the CI gate flagged a false 100% "harmonic mismatch"). Now the
    extractor raises and the sweep loop is responsible for recording
    ``math.nan`` at the failed position and reporting the failure count in
    the run metadata rather than pretending zero was a real torque reading.
    """


class FEMMExtractionMixin:
    """Mixin providing result extraction methods for FEMMSolver.

    Expects the following attributes from the host class (FEMMSolver):
    - _last_geom: MotorGeometry
    - _last_rotor_offset_rad: float
    - _peak_flux_teeth: float
    - _peak_flux_yoke: float
    - femm_module: Any (pyFEMM module)
    - _setup_problem(femm, config, geom): method
    """

    # Declare attributes expected from FEMMSolver (satisfies mypy)
    _last_geom: MotorGeometry
    _last_rotor_offset_rad: float
    _peak_flux_teeth: float
    _peak_flux_yoke: float
    femm_module: Any

    def _setup_problem(self, femm: Any, config: MotorConfig, geom: MotorGeometry) -> None: ...

    def _select_all_machine_blocks(self, femm, config: MotorConfig, geom: MotorGeometry) -> None:
        """Select all modeled motor regions for global energy/coenergy integrals."""
        offset_rad = self._last_rotor_offset_rad
        slot_outer_r = (
            max((slot.outer_radius_mm for slot in geom.slots), default=geom.stator_ID_r)
            if geom.slots
            else geom.stator_ID_r
        )

        def select_polar(radius_mm: float, angle_rad: float) -> None:
            femm.mo_selectblock(radius_mm * math.cos(angle_rad), radius_mm * math.sin(angle_rad))

        # Stator yoke and teeth.
        yoke_r = (slot_outer_r + geom.stator_OD_r) / 2.0
        femm.mo_selectblock(yoke_r, 0.0)
        for idx, slot in enumerate(geom.slots):
            next_slot = geom.slots[(idx + 1) % len(geom.slots)]
            tooth_r = (geom.stator_ID_r + slot_outer_r) / 2.0
            right_of_slot = slot.center_angle_rad + slot.half_width_at_radius(tooth_r)
            left_of_next = next_slot.center_angle_rad - next_slot.half_width_at_radius(tooth_r)
            if left_of_next < right_of_slot:
                left_of_next += 2.0 * math.pi
            select_polar(tooth_r, (right_of_slot + left_of_next) / 2.0)

        # Slot winding/air regions.
        for slot in geom.slots:
            slot_r = (slot.inner_radius_mm + slot.outer_radius_mm) / 2.0
            select_polar(slot_r, slot.center_angle_rad)

        # Airgap and rotor core at a safe inter-magnet angle.
        if len(geom.magnets) >= 2:
            safe_angle = (
                geom.magnets[0].center_angle_rad
                + geom.magnets[1].center_angle_rad
                + 2.0 * offset_rad
            ) / 2.0
        else:
            safe_angle = math.radians(7.0) + offset_rad
        gap_r = (geom.stator_ID_r + geom.rotor_OD_r) / 2.0
        select_polar(gap_r, safe_angle)

        if geom.magnets:
            mag_inner_r = geom.magnets[0].inner_radius_mm
            rotor_core_r = (geom.shaft_r + mag_inner_r) / 2.0
        else:
            rotor_core_r = (geom.rotor_OD_r + geom.shaft_r) / 2.0
        select_polar(rotor_core_r, safe_angle)

        # Shaft and all magnets.
        femm.mo_selectblock(0.0, 0.0)
        for mag in geom.magnets:
            angle = mag.center_angle_rad + offset_rad
            select_polar(mag.radial_center_mm, angle)

    @staticmethod
    def _block_integral_scalar(value: Any) -> float:
        """pyFEMM may return a scalar or a one-element list; normalize both."""
        if isinstance(value, (list, tuple)):
            if not value:
                raise ValueError("empty block-integral result")
            value = value[0]
        return float(value)

    def _extract_energy_functionals(self, femm, config: MotorConfig, geom: MotorGeometry) -> tuple[float, float]:
        """Extract FEMM magnetic energy and coenergy over all modeled regions.

        FEMM block integral 2 is magnetic field energy and 17 is magnetic
        field coenergy. Coenergy finite differences are the primary diagnostic
        for torque at fixed currents; the energy trace is kept as a sign and
        consistency cross-check.
        """
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                self._select_all_machine_blocks(femm, config, geom)
                energy_j = self._block_integral_scalar(femm.mo_blockintegral(2))
                coenergy_j = self._block_integral_scalar(femm.mo_blockintegral(17))
                femm.mo_clearblock()
                return energy_j, coenergy_j
            except Exception as exc:
                last_exc = exc
                try:
                    femm.mo_clearblock()
                except Exception:
                    pass
                # Wine/pyFEMM can occasionally return an empty IPC response
                # immediately after loadsolution even though torque extraction
                # succeeded. Re-selecting blocks after a short pause recovers
                # that transient without masking persistent FEMM failures.
                if attempt + 1 < 3:
                    time.sleep(0.25 * (attempt + 1))
                    try:
                        femm.mo_shownames()
                    except Exception:
                        pass
        raise last_exc if last_exc is not None else RuntimeError("FEMM energy extraction failed")

    def _extract_torque(self, femm) -> float:
        """Extract torque using block integral on rotor regions.

        Returns:
            Torque in N·m.

        Raises:
            FEMMTorqueExtractionError: if FEMM throws during block selection
                or integration. Callers must catch this, record
                ``math.nan`` for the affected rotor position, and surface
                the failure count in the pipeline metadata. Do NOT
                fall back to 0.0 — it produces FFT impulse leakage that
                looks exactly like a real solver harmonic bug (see
                ``FEMMTorqueExtractionError`` docstring for the 2026-04-20
                spm_4p12s_simple false-alarm incident).

        Bug history:
        - mo_groupselectblock() selects group 0 (empty) → 0 torque
        - mo_lineintegral(4) gives force, not torque
        - magnet coords used base angle without rotor offset → wrong block selected
        - Pre-2026-04-20: ``except Exception: return 0.0`` silently masked
          FEMM failures and poisoned CI parity gates. Replaced with a raise.
        - Fix: select each rotor block by coordinate WITH rotor offset, then
          mo_blockintegral(22) = weighted stress tensor torque (N·m)
        """
        geom = self._last_geom
        offset_rad = self._last_rotor_offset_rad
        try:
            # Select all rotor blocks: shaft + rotor core + all magnets
            # mo_selectblock(x, y) selects the block containing that point
            femm.mo_selectblock(0, 0)  # shaft (center)

            # Rotor core — at safe angle between magnets, below magnet inner_r
            # Must add offset_rad because rotor is drawn rotated
            if geom.magnets:
                a1 = geom.magnets[0].center_angle_rad + offset_rad
                a2 = (geom.magnets[1].center_angle_rad + offset_rad
                      if len(geom.magnets) > 1 else a1 + 0.5)
                safe_angle = (a1 + a2) / 2
                mag_inner_r = geom.magnets[0].inner_radius_mm
                rc_r = (geom.shaft_r + mag_inner_r) / 2
                femm.mo_selectblock(rc_r * math.cos(safe_angle), rc_r * math.sin(safe_angle))

                # Each magnet block — use rotated coordinates
                for mag in geom.magnets:
                    angle = mag.center_angle_rad + offset_rad
                    lx = mag.radial_center_mm * math.cos(angle)
                    ly = mag.radial_center_mm * math.sin(angle)
                    femm.mo_selectblock(lx, ly)

            # mo_blockintegral(22) = weighted stress tensor torque (N·m)
            torque = self._block_integral_scalar(femm.mo_blockintegral(22))
            femm.mo_clearblock()

            tagged_log(f"[FEMM] Torque = {torque:.4f} N·m (offset={math.degrees(offset_rad):.1f}°)")
            return torque
        except Exception as e:
            try:
                femm.mo_clearblock()
            except Exception:
                pass
            # Re-raise with context; the sweep loop catches this and records
            # math.nan. Log here with a noisy marker so the failure is easy
            # to grep for in FEMM subprocess output even when the runner
            # drops stdout.
            offset_deg = math.degrees(offset_rad)
            tagged_log(
                f"[FEMM] !! Torque extraction FAILED at mech_offset={offset_deg:+.2f}°: {e}"
            )
            raise FEMMTorqueExtractionError(
                f"mo_blockintegral(22) failed at mech_offset={offset_deg:+.2f}°: {e}"
            ) from e

    def _extract_flux_linkage(
        self, femm, config: MotorConfig, geom: MotorGeometry
    ) -> tuple[float, float, float]:
        """Extract flux linkage per phase for back-EMF computation.

        Approximate each slot's average vector potential by sampling several
        interior points across the slot area. This is a closer match to
        magneto2d's slot-area averaging than a single slot-center probe.

        Returns (psi_a, psi_b, psi_c) in Weber (Wb).

        The physical flux linkage through a coil side is:
            Ψ = N × L_stack × A_z_avg
        where A_z_avg is the area-averaged vector potential (Wb/m) from
        FEMM's mo_getpointvalues, N is turns per coil, and L_stack is the
        axial stack length in metres.
        """
        psi = {"A": 0.0, "B": 0.0, "C": 0.0}

        for slot_info in self._extract_flux_linkage_slot_contributions(femm, config, geom):
            psi[slot_info["phase"]] += slot_info["flux_linkage_contribution_wb"]

        return psi["A"], psi["B"], psi["C"]

    def _extract_flux_linkage_slot_contributions(
        self, femm, config: MotorConfig, geom: MotorGeometry
    ) -> list[dict[str, Any]]:
        """Return per-slot flux-linkage contributions used in the FEMM no-load path.

        FEMM's vector-potential gauge can shift all occupied slots by a
        common A_z offset. Reference slot averages before applying the signed
        winding reduction so this path matches Magneto2D's gauge-invariant
        flux-linkage reducer.
        """
        turns_per_coil = config.winding.turns_per_coil
        turn_factor = flux_linkage_slot_side_turn_factor(
            config.winding.type,
            config.winding.layers,
            config.winding.parallel_paths,
        )
        l_stack_m = config.stator.stack_length_mm * 1e-3

        sampled_slots: list[dict[str, Any]] = []

        for slot in geom.slots:
            assignments = self._slot_extraction_assignments(config, slot)
            for assignment in assignments:
                az_samples: list[float] = []
                for x, y in self._slot_flux_sample_points_for_layer(
                    slot,
                    assignment.layer,
                    len(assignments),
                ):
                    az_val = self._sample_vector_potential(femm, x, y)
                    if az_val is not None:
                        az_samples.append(az_val)

                if not az_samples:
                    continue

                az_avg = sum(az_samples) / len(az_samples)
                sign = 1.0 if assignment.direction == "in" else -1.0
                slot_area_mm2 = max(0.0, float(slot.represented_area_mm2()))
                layer_area_mm2 = slot_area_mm2 * assignment.turn_fraction
                sampled_slots.append({
                    "slot_index": slot.slot_index,
                    "phase": assignment.phase,
                    "direction": assignment.direction,
                    "layer": assignment.layer,
                    "turn_fraction": assignment.turn_fraction,
                    "center_angle_deg": math.degrees(slot.center_angle_rad),
                    "sample_count": len(az_samples),
                    "az_avg_wb_per_m": az_avg,
                    "slot_area_m2": layer_area_mm2 * 1e-6,
                    "_slot_area_mm2": layer_area_mm2,
                    "_sign": sign,
                    "_turn_fraction": assignment.turn_fraction,
                })

        occupied = [row for row in sampled_slots if row["_slot_area_mm2"] > 1.0e-15]
        total_area_mm2 = sum(row["_slot_area_mm2"] for row in occupied)
        az_reference = (
            sum(row["az_avg_wb_per_m"] * row["_slot_area_mm2"] for row in occupied)
            / total_area_mm2
            if len(occupied) > 1 and total_area_mm2 > 1.0e-15
            else 0.0
        )

        contributions: list[dict[str, Any]] = []
        for row in sampled_slots:
            az_effective = row["az_avg_wb_per_m"] - az_reference
            sign = row.pop("_sign")
            row.pop("_slot_area_mm2", None)
            row["az_reference_wb_per_m"] = az_reference
            row["az_effective_wb_per_m"] = az_effective
            row["flux_linkage_contribution_wb"] = (
                sign
                * turn_factor
                * turns_per_coil
                * float(row.pop("_turn_fraction", 1.0))
                * l_stack_m
                * az_effective
            )
            contributions.append(row)

        return contributions

    def _extract_slot_excitation_contributions(
        self, femm: Any, config: MotorConfig, geom: MotorGeometry, elec_angle_deg: float
    ) -> list[dict[str, Any]]:
        """Extract per-slot ampere-turn injection from FEMM after solve.

        Mirrors the native magneto2d ``compute_slot_excitation_summary`` so
        the Compare view's slot excitation panel can put both side-by-side.
        Used to debug the +47% loaded-torque DC offset (Sprint-19 parity work):
        if native and FEMM disagree on per-slot ampere-turns, the bug is in
        the current-density assembly (turns interpretation, slot area, or
        parallel-paths divide), not the field solution.

        FEMM's ``mo_blockintegral(7)`` returns the total current through the
        selected block in Amperes. That's the *actual* ampere-turns the FEM
        mesh saw — independent of the analytical N·I/A_slot formula that
        produced J. Comparing this to native's equivalent integral isolates
        whether the J×A bookkeeping matches.

        Returns a list of dicts shaped like
        ``backend.models.SlotExcitationContribution`` so it can drop straight
        into ``SolveSummary.slot_excitation_contributions``.
        """
        _, phase_current_vector = self._slot_excitation_current_metadata(
            config,
            elec_angle_deg,
        )
        currents_per_phase_a = {
            "A": phase_current_vector[0],
            "B": phase_current_vector[1],
            "C": phase_current_vector[2],
        }

        turns_per_coil = max(1, int(getattr(config.winding, "turns_per_coil", 1) or 1))
        contributions: list[dict[str, Any]] = []

        for slot in geom.slots:
            assignments = self._slot_extraction_assignments(config, slot)
            if len(assignments) > 1:
                radial_span = max(0.0, slot.outer_radius_mm - slot.inner_radius_mm)
                for assignment in assignments:
                    layer_idx = max(1, min(assignment.layer, len(assignments))) - 1
                    slot_r = (
                        slot.inner_radius_mm
                        + radial_span * (layer_idx + 0.5) / len(assignments)
                    )
                    lx = slot_r * math.cos(slot.center_angle_rad)
                    ly = slot_r * math.sin(slot.center_angle_rad)

                    try:
                        femm.mo_clearblock()
                        femm.mo_selectblock(lx, ly)
                        amp_turns_a = float(femm.mo_blockintegral(7))
                        slot_area_m2 = float(femm.mo_blockintegral(5))
                        femm.mo_clearblock()
                    except Exception as exc:  # pragma: no cover - IPC failure path
                        logger.warning(
                            "[FEMM] slot %s layer %s ampere-turn extraction failed: %s",
                            slot.slot_index,
                            assignment.layer,
                            exc,
                        )
                        try:
                            femm.mo_clearblock()
                        except Exception:
                            pass
                        continue

                    phase_current_a = currents_per_phase_a.get(assignment.phase, 0.0)
                    sign = 1.0 if assignment.direction == "in" else -1.0
                    slot_current_a = (
                        amp_turns_a / float(turns_per_coil)
                        if turns_per_coil > 0
                        else 0.0
                    )
                    j_eff_a_per_m2 = (
                        amp_turns_a / slot_area_m2 if slot_area_m2 > 1e-18 else 0.0
                    )

                    contributions.append({
                        "slot_index_modeled": int(slot.slot_index),
                        "slot_index_global": int(slot.slot_index),
                        "phase": str(assignment.phase),
                        "direction": str(assignment.direction),
                        "layer": int(assignment.layer),
                        "turn_fraction": float(assignment.turn_fraction),
                        "center_angle_mech_deg": math.degrees(slot.center_angle_rad),
                        "slot_area_m2": slot_area_m2,
                        "effective_current_density_a_per_m2": j_eff_a_per_m2,
                        "integrated_amp_turns_a": amp_turns_a,
                        "slot_current_a": slot_current_a,
                        "phase_current_a": sign * phase_current_a,
                        "turns_per_coil": int(turns_per_coil),
                    })
                continue

            slot_r = (slot.inner_radius_mm + slot.outer_radius_mm) / 2.0
            lx = slot_r * math.cos(slot.center_angle_rad)
            ly = slot_r * math.sin(slot.center_angle_rad)

            # mo_blockintegral(7) returns total current through the selected
            # blocks in Amperes (= integrated J·dA = signed ampere-turns).
            # Code 0 is A·J and must not be used for current parity.
            try:
                femm.mo_clearblock()
                femm.mo_selectblock(lx, ly)
                amp_turns_a = float(femm.mo_blockintegral(7))
                # mo_blockintegral(5) = block area in m² (FEMM SI)
                slot_area_m2 = float(femm.mo_blockintegral(5))
                femm.mo_clearblock()
            except Exception as exc:  # pragma: no cover — IPC failure path
                logger.warning(
                    "[FEMM] slot %s ampere-turn extraction failed: %s",
                    slot.slot_index,
                    exc,
                )
                try:
                    femm.mo_clearblock()
                except Exception:
                    pass
                continue

            phase_current_a = currents_per_phase_a.get(slot.phase, 0.0)
            # FEMM signs J via the slot material: J = +current for "in",
            # −current for "out". Mirror that in the recorded direction.
            sign = 1.0 if slot.direction == "in" else -1.0
            slot_current_a = amp_turns_a / float(turns_per_coil) if turns_per_coil > 0 else 0.0
            j_eff_a_per_m2 = (
                amp_turns_a / slot_area_m2 if slot_area_m2 > 1e-18 else 0.0
            )

            contributions.append({
                "slot_index_modeled": int(slot.slot_index),
                "slot_index_global": int(slot.slot_index),
                "phase": str(slot.phase),
                "direction": str(slot.direction),
                "center_angle_mech_deg": math.degrees(slot.center_angle_rad),
                "slot_area_m2": slot_area_m2,
                "effective_current_density_a_per_m2": j_eff_a_per_m2,
                "integrated_amp_turns_a": amp_turns_a,
                "slot_current_a": slot_current_a,
                "phase_current_a": sign * phase_current_a,
                "turns_per_coil": int(turns_per_coil),
            })

        return contributions

    def _slot_excitation_current_metadata(
        self,
        config: MotorConfig,
        elec_angle_deg: float,
    ) -> tuple[float, list[float]]:
        """Return the current angle and phase currents used for slot J."""
        sp = config.solve_params
        current_angle_for_calc = current_angle_elec_deg_for_rotor_elec(
            config,
            elec_angle_deg,
        )

        currents_per_phase_a = [0.0, 0.0, 0.0]
        if sp is not None:
            if sp.excitation_mode == "ideal_six_step_120":
                from backend.excitation import resolve_phase_current_sample

                sample = resolve_phase_current_sample(config, elec_angle_deg)
                return float(current_angle_for_calc), list(sample.phase_current_a)
            try:
                from backend.geometry_drawer import resolve_phase_current_peak
                I_peak = resolve_phase_current_peak(config)
            except Exception:
                I_peak = float(getattr(sp, "current_amplitude_A", 0.0) or 0.0)
            theta = math.radians(current_angle_for_calc)
            parallel = max(1, int(getattr(config.winding, "parallel_paths", 1) or 1))
            I_conductor = I_peak / parallel
            currents_per_phase_a = [
                I_conductor * math.sin(theta),
                I_conductor * math.sin(theta - 2.0 * math.pi / 3.0),
                I_conductor * math.sin(theta - 4.0 * math.pi / 3.0),
            ]
        return float(current_angle_for_calc), currents_per_phase_a

    def _build_slot_excitation_frame(
        self,
        femm: Any,
        config: MotorConfig,
        geom: MotorGeometry,
        elec_angle_deg: float,
    ) -> dict[str, Any]:
        source_current_angle_deg, phase_current_a = self._slot_excitation_current_metadata(
            config,
            elec_angle_deg,
        )
        return {
            "angle_deg": float(elec_angle_deg),
            "source_current_angle_deg": source_current_angle_deg,
            "phase_current_a": phase_current_a,
            "contributions": self._extract_slot_excitation_contributions(
                femm,
                config,
                geom,
                elec_angle_deg,
            ),
        }

    @staticmethod
    def _slot_flux_sample_points(slot: SlotPlacement) -> list[tuple[float, float]]:
        """Return a small interior sampling grid for one slot."""
        radial_fracs = (0.25, 0.5, 0.75)
        angular_fracs = (-0.6, 0.0, 0.6)

        inner_r = slot.inner_radius_mm
        outer_r = slot.outer_radius_mm
        radial_span = outer_r - inner_r

        points: list[tuple[float, float]] = []
        for radial_frac in radial_fracs:
            radius = inner_r + radial_span * radial_frac
            effective_half_width = slot.half_width_at_radius(radius) * 0.8
            for angular_frac in angular_fracs:
                angle = slot.center_angle_rad + effective_half_width * angular_frac
                points.append((radius * math.cos(angle), radius * math.sin(angle)))
        return points

    @staticmethod
    def _slot_flux_sample_points_for_layer(
        slot: SlotPlacement,
        layer: int,
        layers: int,
    ) -> list[tuple[float, float]]:
        """Return a small interior sampling grid for one radial slot layer."""
        n_layers = max(1, int(layers))
        if n_layers <= 1:
            return FEMMExtractionMixin._slot_flux_sample_points(slot)

        layer_idx = max(1, min(int(layer), n_layers)) - 1
        radial_span = max(0.0, slot.outer_radius_mm - slot.inner_radius_mm)
        layer_inner = slot.inner_radius_mm + radial_span * layer_idx / n_layers
        layer_outer = slot.inner_radius_mm + radial_span * (layer_idx + 1) / n_layers
        radial_fracs = (0.25, 0.5, 0.75)
        angular_fracs = (-0.6, 0.0, 0.6)

        points: list[tuple[float, float]] = []
        for radial_frac in radial_fracs:
            radius = layer_inner + (layer_outer - layer_inner) * radial_frac
            effective_half_width = slot.half_width_at_radius(radius) * 0.8
            for angular_frac in angular_fracs:
                angle = slot.center_angle_rad + effective_half_width * angular_frac
                points.append((radius * math.cos(angle), radius * math.sin(angle)))
        return points

    @staticmethod
    def _slot_extraction_assignments(
        config: MotorConfig,
        slot: SlotPlacement,
    ) -> tuple[SlotLayerAssignment, ...]:
        if config.winding.type == "distributed" and config.winding.layers >= 2:
            full_pitch = distributed_full_pitch_slots(
                config.stator.slot_count,
                config.rotor.pole_count,
            )
            if (
                config.winding.coil_span is not None
                and int(config.winding.coil_span) != full_pitch
            ):
                return distributed_slot_layer_assignments(
                    slot.slot_index,
                    config.stator.slot_count,
                    config.rotor.pole_count,
                    config.winding.layers,
                    coil_span=config.winding.coil_span,
                )
        return (
            SlotLayerAssignment(
                layer=int(getattr(slot, "layer", 1)),
                phase=str(slot.phase),
                direction=str(slot.direction),
                turn_fraction=1.0,
            ),
        )

    @staticmethod
    def _sample_vector_potential(femm, x: float, y: float) -> float | None:
        """Read the local vector potential A at one point."""
        try:
            vals = femm.mo_getpointvalues(x, y)
        except Exception:
            return None

        if vals is None or not hasattr(vals, "__len__") or len(vals) == 0:
            return None

        try:
            return float(vals[0])
        except (TypeError, ValueError):
            return None

    def _extract_flux_density(self, femm, geom: MotorGeometry) -> FluxDensityMap:
        """Extract flux density at airgap, tooth, and yoke sample points.

        Sampling strategy:
         1. Airgap — 36 evenly-spaced points at the gap midpoint radius
         2. Teeth  — sample at actual tooth center angles (midway between
                     adjacent slot centers) to avoid landing in coil regions
         3. Yoke   — 36 evenly-spaced points at the yoke midpoint radius

        All values are capped at B_MAX_PHYSICAL (3.0 T) to discard obvious
        artifact spikes from mesh boundary or unlabeled region hits.
        """
        try:
            femm.mo_smooth("off")
        except Exception:
            pass

        nodes = []
        b_values = []

        gap_r = (geom.stator_ID_r + geom.rotor_OD_r) / 2
        slot_outer_r = geom.slots[0].outer_radius_mm if geom.slots else geom.stator_OD_r
        tooth_r = (geom.stator_ID_r + slot_outer_r) / 2
        yoke_r = (slot_outer_r + geom.stator_OD_r) / 2

        b_teeth_samples: list[float] = []
        b_yoke_samples: list[float] = []
        B_MAX_PHYSICAL = 3.0  # T — generous upper bound for steel in this tool

        def _sanitize_flux_sample(b: float) -> float:
            return min(max(b, 0.0), B_MAX_PHYSICAL)

        b_teeth_samples = []
        b_yoke_samples = []

        # ── Diagnostic probe: test mo_getpointvalues at a known-good slot center ──
        # Flux linkage extraction uses this exact pattern and works, so we can
        # compare the raw return format between slot vs tooth/yoke points.
        if geom.slots:
            probe_slot = geom.slots[0]
            probe_r = (probe_slot.inner_radius_mm + probe_slot.outer_radius_mm) / 2
            probe_x = probe_r * math.cos(probe_slot.center_angle_rad)
            probe_y = probe_r * math.sin(probe_slot.center_angle_rad)
            try:
                probe_vals = femm.mo_getpointvalues(probe_x, probe_y)
                probe_type = type(probe_vals).__name__
                probe_len = len(probe_vals) if hasattr(probe_vals, '__len__') else 'N/A'
                probe_preview = str(probe_vals[:5]) if hasattr(probe_vals, '__getitem__') and hasattr(probe_vals, '__len__') else str(probe_vals)
                tagged_log(f"[FLUX-DIAG] Slot probe at ({probe_x:.1f},{probe_y:.1f}): "
                      f"type={probe_type}, len={probe_len}, vals={probe_preview}")
            except Exception as exc:
                tagged_log(f"[FLUX-DIAG] Slot probe FAILED: {exc}")

            # Also probe a tooth point for comparison
            slot_angles = sorted([s.center_angle_rad for s in geom.slots])
            a1 = slot_angles[0]
            a2 = slot_angles[1] if len(slot_angles) > 1 else a1 + 0.1
            test_tooth_angle = (a1 + a2) / 2
            test_x = tooth_r * math.cos(test_tooth_angle)
            test_y = tooth_r * math.sin(test_tooth_angle)
            try:
                test_vals = femm.mo_getpointvalues(test_x, test_y)
                test_type = type(test_vals).__name__
                test_len = len(test_vals) if hasattr(test_vals, '__len__') else 'N/A'
                test_preview = str(test_vals[:5]) if hasattr(test_vals, '__getitem__') and hasattr(test_vals, '__len__') else str(test_vals)
                tagged_log(f"[FLUX-DIAG] Tooth probe at ({test_x:.1f},{test_y:.1f}): "
                      f"type={test_type}, len={test_len}, vals={test_preview}")
            except Exception as exc:
                tagged_log(f"[FLUX-DIAG] Tooth probe FAILED: {exc}")

        tagged_log(f"[FLUX-DIAG] Radii: gap_r={gap_r:.2f}, tooth_r={tooth_r:.2f}, "
              f"yoke_r={yoke_r:.2f}, stator_ID_r={geom.stator_ID_r:.2f}, "
              f"stator_OD_r={geom.stator_OD_r:.2f}")

        def _sample_point(x, y, label=""):
            """Read |B| at (x,y). Returns (value, ok) where ok=False means
            the point returned 0 because of an exception or empty response.

            Detects pyFEMM's fallback pattern: when a point is outside the
            mesh or FEMM IPC fails, mo_getpointvalues returns a list of all
            zeros (e.g. [0,0,0,0,...,0]) which masquerades as valid data.
            """
            try:
                vals = femm.mo_getpointvalues(x, y)

                # Handle non-list returns (some pyFEMM versions)
                if vals is None:
                    return 0.0, False
                if not hasattr(vals, '__len__'):
                    return 0.0, False

                if len(vals) >= 3:
                    bx, by = float(vals[1]), float(vals[2])
                    b_mag = math.sqrt(bx**2 + by**2)

                    # Detect pyFEMM fallback: all values are exactly zero
                    # means FEMM couldn't read the point (outside mesh, IPC fail).
                    # A real in-mesh point has non-zero A (vals[0]) even if B≈0.
                    if b_mag == 0.0 and float(vals[0]) == 0.0:
                        return 0.0, False

                    return b_mag, True
                else:
                    tagged_log(f"[FLUX] {label} mo_getpointvalues returned {len(vals)} values at ({x:.1f},{y:.1f})")
            except Exception as exc:
                tagged_log(f"[FLUX] {label} mo_getpointvalues error at ({x:.1f},{y:.1f}): {exc}")
            return 0.0, False

        # ── 1. Airgap ring: 36 points evenly spaced ──
        for i in range(36):
            angle = math.radians(i * 10)
            x, y = gap_r * math.cos(angle), gap_r * math.sin(angle)
            nodes.append(Node(x=x, y=y))
            b, _ = _sample_point(x, y, "airgap")
            b_values.append(b)

        # ── 2. Teeth: sample at tooth center angles only ──
        slot_angles = sorted([s.center_angle_rad for s in geom.slots])
        num_slots = len(slot_angles)
        for i in range(num_slots):
            a1 = slot_angles[i]
            a2 = slot_angles[(i + 1) % num_slots]
            if a2 < a1:
                a2 += 2 * math.pi
            tooth_angle = (a1 + a2) / 2
            x, y = tooth_r * math.cos(tooth_angle), tooth_r * math.sin(tooth_angle)
            nodes.append(Node(x=x, y=y))
            b, ok = _sample_point(x, y, f"tooth[{i}]")
            b_values.append(b)
            if ok:
                b_teeth_samples.append(_sanitize_flux_sample(b))

        # ── 3. Yoke ring: 36 points evenly spaced ──
        for i in range(36):
            angle = math.radians(i * 10)
            x, y = yoke_r * math.cos(angle), yoke_r * math.sin(angle)
            nodes.append(Node(x=x, y=y))
            b, ok = _sample_point(x, y, f"yoke[{i}]")
            b_values.append(b)
            if ok:
                b_yoke_samples.append(_sanitize_flux_sample(b))

        # Use max of valid samples
        b_max_teeth = max(b_teeth_samples) if b_teeth_samples else 0.0
        b_max_yoke = max(b_yoke_samples) if b_yoke_samples else 0.0

        teeth_valid = len(b_teeth_samples)
        yoke_valid = len(b_yoke_samples)
        tagged_log(f"[FLUX] Point-sampling: {len(nodes)} points "
              f"(teeth: {teeth_valid}/{num_slots} ok, yoke: {yoke_valid}/36 ok)")
        tagged_log(f"[FLUX] B_max_teeth={b_max_teeth:.3f} T, B_max_yoke={b_max_yoke:.3f} T")

        # ── Fallback: mesh-element centroid extraction ──────────────────
        # If point-sampling returned no valid teeth/yoke data, extract B from
        # mesh element centroids (guaranteed to be inside the mesh).  This
        # handles the case where computed sample points fall outside the mesh
        # or pyFEMM returns the all-zeros fallback for arbitrary coordinates.
        if b_max_teeth == 0.0 or b_max_yoke == 0.0:
            tagged_log("[FLUX] Point-sampling failed — trying mesh element centroid extraction")
            elem_b_teeth = []
            elem_b_yoke = []
            try:
                num_elem = femm.mo_numelements()
                tagged_log(f"[FLUX] Scanning {num_elem} mesh elements for tooth/yoke B")
                for ei in range(1, num_elem + 1):
                    elem = femm.mo_getelement(ei)
                    # mo_getelement returns: [n1, n2, n3, cx, cy, area, group]
                    if not elem or len(elem) < 5:
                        continue
                    cx, cy = float(elem[3]), float(elem[4])
                    r = math.sqrt(cx**2 + cy**2)

                    # Classify element by radius
                    is_tooth_r = (geom.stator_ID_r - 0.5) < r < (slot_outer_r + 0.5)
                    is_yoke_r = (slot_outer_r - 0.5) < r < (geom.stator_OD_r + 0.5)

                    if not is_tooth_r and not is_yoke_r:
                        continue

                    # Sample B at element centroid (inside mesh by definition)
                    try:
                        vals = femm.mo_getpointvalues(cx, cy)
                        if vals and hasattr(vals, '__len__') and len(vals) >= 3:
                            bx_e = float(vals[1])
                            by_e = float(vals[2])
                            a_val = float(vals[0])
                            b_elem = math.sqrt(bx_e**2 + by_e**2)

                            # Skip all-zeros fallback
                            if b_elem == 0.0 and a_val == 0.0:
                                continue

                            b_elem = _sanitize_flux_sample(b_elem)

                            # Use mu to distinguish iron (teeth/yoke) from air/copper (slots)
                            # vals[9] = mu_x, vals[10] = mu_y — iron has mu >> 1
                            if len(vals) >= 11:
                                mu_x = float(vals[9])
                                if mu_x < 5.0:
                                    continue  # Skip air/copper/magnet regions

                            if is_tooth_r and b_max_teeth == 0.0:
                                elem_b_teeth.append(b_elem)
                            if is_yoke_r and b_max_yoke == 0.0:
                                elem_b_yoke.append(b_elem)
                    except Exception:
                        continue

                if elem_b_teeth:
                    b_max_teeth = max(elem_b_teeth)
                    tagged_log(f"[FLUX] Element fallback teeth: {len(elem_b_teeth)} valid, "
                          f"B_max={b_max_teeth:.3f} T")
                if elem_b_yoke:
                    b_max_yoke = max(elem_b_yoke)
                    tagged_log(f"[FLUX] Element fallback yoke: {len(elem_b_yoke)} valid, "
                          f"B_max={b_max_yoke:.3f} T")
                if not elem_b_teeth and not elem_b_yoke:
                    tagged_log("[FLUX] Element fallback also returned no valid data")
            except Exception as exc:
                tagged_log(f"[FLUX] Element fallback failed: {exc}")

        self._peak_flux_teeth = b_max_teeth
        self._peak_flux_yoke = b_max_yoke

        if not nodes:
            nodes = [Node(x=0, y=0)]
            b_values = [0.0]

        return FluxDensityMap(nodes=nodes, B_magnitude=b_values)

    # ── Flux density map helpers ─────────────────────────────────────────

    @staticmethod
    def _estimate_yoke_flux(flux_map: FluxDensityMap) -> float:
        """Estimate yoke flux density from airgap data."""
        if not flux_map.B_magnitude:
            return 0.0
        avg_flux = sum(flux_map.B_magnitude) / len(flux_map.B_magnitude)
        return avg_flux * 0.75

    def extract_flux_grid(self, config: MotorConfig, grid_nx: int = 80,
                         grid_ny: int = 80) -> dict:
        """Extract flux density on a rectangular grid (S4-12).

        Args:
            config: Motor configuration
            grid_nx: Grid points in X
            grid_ny: Grid points in Y

        Returns:
            dict with "x_mm", "y_mm", "B_tesla"
        """
        logger.info(f"[FLUX] Extracting {grid_nx}×{grid_ny} flux map grid (S4-12)")

        femm = self.femm_module
        # Initialize COM for this thread before pyFEMM's Dispatch call.
        # Mirrors the fix in FEMMSolver._open_femm: required when this
        # code runs off the main thread (e.g. FastAPI worker threads).
        if platform.system() == "Windows":
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass
        femm.openfemm(1)  # Hidden window

        try:
            geom = compute_geometry(config)
            self._setup_problem(femm, config, geom)
            femm.mi_analyze()
            femm.mi_loadsolution()
            time.sleep(0.2)

            # Sample grid
            x_min, x_max = -geom.stator_OD_r, geom.stator_OD_r
            y_min, y_max = -geom.stator_OD_r, geom.stator_OD_r

            x_vals = np.linspace(x_min, x_max, grid_nx)
            y_vals = np.linspace(y_min, y_max, grid_ny)

            B_grid = np.zeros((grid_ny, grid_nx))

            for j, y in enumerate(y_vals):
                for i, x in enumerate(x_vals):
                    try:
                        vals = femm.mo_getpointvalues(x, y)
                        if vals and len(vals) >= 3:
                            bx, by = vals[1], vals[2]
                            B_grid[j, i] = math.sqrt(bx**2 + by**2)
                    except Exception:
                        pass

            logger.info("[FLUX] Grid extraction complete (S4-12)")
            return {
                "x_mm": x_vals.tolist(),
                "y_mm": y_vals.tolist(),
                "B_tesla": B_grid.tolist(),
            }
        finally:
            try:
                femm.mo_close()
                femm.mi_close()
            except Exception:
                pass
            femm.closefemm()

    def _extract_mesh(self, femm, fem_path: str | None = None) -> dict[str, Any]:
        """Extract mesh triangulation from FEMM after mi_createmesh().

        Two paths:

        1. **Fast path** (when ``fem_path`` is provided): parse the ``.nod``
           and ``.ele`` files Triangle writes alongside the .fem during
           ``mi_createmesh()``. Plain text, ~1 sec for 50k nodes — no Wine
           IPC. The .ans file solved by ``mi_analyze()`` doesn't need to
           exist for this path; the mesh files are written before analyze
           runs.
        2. **Slow path** (fallback): use the postprocess API
           (``mo_numnodes`` / ``mo_getnode`` / ``mo_numelements`` /
           ``mo_getelement``). Requires a loaded solution. One pyFEMM call
           per node + per element — at ~1ms per Wine round-trip, a 50k-node
           mesh takes ~100s. Use only when fast-path files aren't present
           or fail to parse.

        Returns:
            Dictionary with keys:
            - "nodes_mm": list of [x, y] coordinates in mm
            - "triangles": list of [i, j, k] node indices (0-based)
            - "num_nodes": count of nodes
            - "num_triangles": count of triangles
        """
        if fem_path is not None:
            try:
                fast = _read_femm_mesh_from_disk(fem_path)
                if fast is not None:
                    tagged_log(
                        f"[FEMM] Extracted mesh (disk): {fast['num_nodes']} nodes, "
                        f"{fast['num_triangles']} triangles"
                    )
                    return fast
            except Exception as e:
                tagged_log(
                    f"[FEMM] disk-extract failed ({e}); falling back to mo_* IPC path"
                )

        try:
            num_nodes = int(femm.mo_numnodes())
            num_triangles = int(femm.mo_numelements())

            nodes_mm: list[list[float]] = []
            for i in range(1, num_nodes + 1):
                x, y = femm.mo_getnode(i)
                nodes_mm.append([float(x), float(y)])

            triangles: list[list[int]] = []
            for i in range(1, num_triangles + 1):
                # mo_getelement(i) returns (n1, n2, n3, ...) where n1, n2, n3
                # are 1-based node indices. Convert to 0-based for JSON output.
                elem_data = femm.mo_getelement(i)
                n1, n2, n3 = int(elem_data[0]) - 1, int(elem_data[1]) - 1, int(elem_data[2]) - 1
                triangles.append([n1, n2, n3])

            tagged_log(
                f"[FEMM] Extracted mesh (mo_*): {num_nodes} nodes, {num_triangles} triangles"
            )
            return {
                "nodes_mm": nodes_mm,
                "triangles": triangles,
                "num_nodes": num_nodes,
                "num_triangles": num_triangles,
            }
        except Exception as e:
            tagged_log(f"[FEMM] !! Mesh extraction FAILED: {e}")
            raise
