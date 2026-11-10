"""Live SSE / payload helpers for the FEMM solver.

Sprint 27 Track 1F Phase 1: extracted from backend/femm_solver.py (3421 lines)
so the FEMMSolver class + helpers + run_femm_*_preview entry points stay
together in __init__.py while the pure-function streaming/payload block lives
in its own module. Behaviour is verbatim.
"""

from __future__ import annotations

import math
import time
from typing import Any

from backend.airgap_sampling import sample_airgap_midpoint_records_from_mesh
from backend.geometry_drawer import MotorGeometry, point_in_polygon

_FEMM_LIVE_AIRGAP_BRBT_BIN_COUNT = 180
_FEMM_POINT_VALUE_RETRIES = 4


def _pack_femm_live_float(value: Any, significant_digits: int = 6) -> Any:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(numeric):
        return value
    return float(f"{numeric:.{significant_digits}g}")


def _pack_femm_live_float_list(
    values: list[Any],
    significant_digits: int = 6,
) -> list[Any]:
    return [_pack_femm_live_float(value, significant_digits) for value in values]


def _pack_femm_live_segment(segment: list[Any]) -> list[Any]:
    return [_pack_femm_live_float(value, 7) for value in segment]


def _pack_femm_live_contours(contours: list[Any]) -> list[dict[str, Any]]:
    packed: list[dict[str, Any]] = []
    for contour in contours:
        packed.append(
            {
                "level": _pack_femm_live_float(contour.level),
                "segments_mm": [
                    _pack_femm_live_segment(segment)
                    for segment in contour.segments_mm
                ],
                "segment_b_mag_t": _pack_femm_live_float_list(
                    contour.segment_b_mag_t
                ),
                "segment_bx_t": _pack_femm_live_float_list(contour.segment_bx_t),
                "segment_by_t": _pack_femm_live_float_list(contour.segment_by_t),
            }
        )
    return packed


def _airgap_b_records_from_frame(
    field_data: dict[str, "Any"],
    live_field_frame: dict[str, "Any"],
    geom: "MotorGeometry | None" = None,
    *,
    rotor_angle_mech_deg: float = 0.0,
) -> dict[str, list[float]] | None:
    """Pre-filter the per-frame mesh + |B| to airgap-only triangles.

    Returns parallel arrays {centroid_x_mm, centroid_y_mm, b_magnitude_t}
    sized to the airgap-tagged triangles only. Returns None when the
    inputs are missing or yield no airgap triangles.

    Sprint 25: this lets the FEMM frame payload stay small (~24 KB/frame
    instead of ~1.5 MB) while still carrying enough data for Compare's
    airgap |B| stat cards + trace chart to render on the FEMM side.
    """
    nodes_mm = field_data.get("nodes_mm") or []
    triangles = field_data.get("triangles") or []
    regions = live_field_frame.get("regions") or []
    element_b_mag_t = live_field_frame.get("element_b_mag_t") or []
    element_bx_t = live_field_frame.get("element_bx_t") or []
    element_by_t = live_field_frame.get("element_by_t") or []
    if geom is not None and (
        not element_bx_t
        or not element_by_t
        or len(element_bx_t) != len(triangles)
        or len(element_by_t) != len(triangles)
    ):
        from backend.field_lines import generate_element_b_components

        az_nodal = field_data.get("az_nodal") or []
        if az_nodal:
            element_bx_t, element_by_t = generate_element_b_components(
                nodes_mm,
                triangles,
                az_nodal,
            )
    if geom is not None and (
        not regions
        or len(regions) != len(triangles)
    ):
        regions = _classify_femm_triangles_by_centroid(
            nodes_mm,
            triangles,
            geom,
            rotor_angle_mech_deg=rotor_angle_mech_deg,
        )
    if (
        not element_b_mag_t
        and len(element_bx_t) == len(triangles)
        and len(element_by_t) == len(triangles)
    ):
        element_b_mag_t = [
            math.hypot(float(bx), float(by))
            if isinstance(bx, (int, float))
            and isinstance(by, (int, float))
            and math.isfinite(float(bx))
            and math.isfinite(float(by))
            else 0.0
            for bx, by in zip(element_bx_t, element_by_t)
        ]
    if (
        not nodes_mm
        or not triangles
        or not regions
        or not element_b_mag_t
        or len(regions) != len(triangles)
        or len(element_b_mag_t) != len(triangles)
    ):
        return None

    have_components = (
        len(element_bx_t) == len(triangles)
        and len(element_by_t) == len(triangles)
    )

    if geom is not None and have_components:
        rotor_outer_with_magnets = geom.rotor_OD_r
        if geom.magnets:
            rotor_outer_with_magnets = max(
                geom.rotor_OD_r,
                max(m.outer_radius_mm for m in geom.magnets),
            )
        midpoint_records = sample_airgap_midpoint_records_from_mesh(
            nodes_mm=nodes_mm,
            triangles=triangles,
            regions=regions,
            element_bx_t=element_bx_t,
            element_by_t=element_by_t,
            airgap_inner_radius_mm=rotor_outer_with_magnets,
            airgap_outer_radius_mm=geom.stator_ID_r,
            sample_count=36,
            span_deg=360.0,
        )
        if midpoint_records is not None:
            return midpoint_records

    centroid_x: list[float] = []
    centroid_y: list[float] = []
    b_mag: list[float] = []
    b_radial: list[float] = []
    b_tangential: list[float] = []

    n_nodes = len(nodes_mm)
    for idx, tri in enumerate(triangles):
        if regions[idx] != "airgap":
            continue
        if len(tri) < 3:
            continue
        a, b, c = tri[0], tri[1], tri[2]
        if a >= n_nodes or b >= n_nodes or c >= n_nodes:
            continue
        na = nodes_mm[a]
        nb = nodes_mm[b]
        nc = nodes_mm[c]
        if not (len(na) >= 2 and len(nb) >= 2 and len(nc) >= 2):
            continue
        bm = element_b_mag_t[idx]
        if not isinstance(bm, (int, float)):
            continue
        bm_f = float(bm)
        if bm_f <= 0.0:
            continue
        cx = (na[0] + nb[0] + nc[0]) / 3.0
        cy = (na[1] + nb[1] + nc[1]) / 3.0
        centroid_x.append(cx)
        centroid_y.append(cy)
        b_mag.append(bm_f)

        # Decompose into radial / tangential components if the source frame
        # carried Bx / By. r_hat = (cos theta, sin theta) where theta is the
        # centroid angle; t_hat = (-sin theta, cos theta) (mathematical CCW
        # convention, matches CompareDashboard.computeAirgapTraceBins).
        if have_components:
            radius = (cx * cx + cy * cy) ** 0.5
            if radius > 1e-9:
                bx = element_bx_t[idx]
                by = element_by_t[idx]
                if isinstance(bx, (int, float)) and isinstance(by, (int, float)):
                    bxf = float(bx)
                    byf = float(by)
                    rx = cx / radius
                    ry = cy / radius
                    br = bxf * rx + byf * ry
                    bt = -bxf * ry + byf * rx
                    b_radial.append(br)
                    b_tangential.append(bt)
                    continue
            # If we got here, we couldn't decompose this row — keep arrays
            # aligned by appending NaN sentinels. Pydantic accepts NaN floats.
            b_radial.append(float("nan"))
            b_tangential.append(float("nan"))

    if not b_mag:
        return None
    out = {
        "centroid_x_mm": centroid_x,
        "centroid_y_mm": centroid_y,
        "b_magnitude_t": b_mag,
    }
    if have_components:
        out["b_radial_t"] = b_radial
        out["b_tangential_t"] = b_tangential
    return out


def _airgap_point_records_from_open_solution(
    femm: Any,
    geom: "MotorGeometry",
    *,
    sample_count: int = 36,
) -> dict[str, list[float]] | None:
    """Sample FEMM B directly at fixed midpoint-airgap ring points."""
    if sample_count <= 0 or geom.stator_ID_r <= geom.rotor_OD_r:
        return None

    try:
        femm.mo_smooth("off")
    except Exception:
        pass

    rotor_outer_with_magnets = geom.rotor_OD_r
    if geom.magnets:
        rotor_outer_with_magnets = max(
            geom.rotor_OD_r,
            max(m.outer_radius_mm for m in geom.magnets),
        )
    if geom.stator_ID_r <= rotor_outer_with_magnets:
        return None

    radius_mm = 0.5 * (rotor_outer_with_magnets + geom.stator_ID_r)
    centroid_x: list[float] = []
    centroid_y: list[float] = []
    b_mag: list[float] = []
    b_radial: list[float] = []
    b_tangential: list[float] = []

    for sample_idx in range(sample_count):
        theta = 2.0 * math.pi * sample_idx / sample_count
        x_mm = radius_mm * math.cos(theta)
        y_mm = radius_mm * math.sin(theta)
        values = None
        for attempt_idx in range(_FEMM_POINT_VALUE_RETRIES):
            values = femm.mo_getpointvalues(x_mm, y_mm)
            try:
                bx = float(values[1])
                by = float(values[2])
            except (IndexError, TypeError, ValueError):
                bx = by = 0.0
            if math.isfinite(bx) and math.isfinite(by) and (bx != 0.0 or by != 0.0):
                break
            if attempt_idx + 1 < _FEMM_POINT_VALUE_RETRIES:
                time.sleep(0.02)
        else:
            if values is None:
                return None

        if values is None:
            return None
        try:
            bx = float(values[1])
            by = float(values[2])
        except (IndexError, TypeError, ValueError):
            return None
        if not math.isfinite(bx) or not math.isfinite(by):
            return None

        br = bx * math.cos(theta) + by * math.sin(theta)
        bt = -bx * math.sin(theta) + by * math.cos(theta)
        if not math.isfinite(br) or not math.isfinite(bt):
            return None

        centroid_x.append(x_mm)
        centroid_y.append(y_mm)
        b_mag.append(math.hypot(bx, by))
        b_radial.append(br)
        b_tangential.append(bt)

    return {
        "centroid_x_mm": centroid_x,
        "centroid_y_mm": centroid_y,
        "b_magnitude_t": b_mag,
        "b_radial_t": b_radial,
        "b_tangential_t": b_tangential,
    }


def _build_femm_live_field_payload(
    field_data: dict[str, Any],
    *,
    elec_angle_deg: float,
    geom: "MotorGeometry | None" = None,
    include_raw_mesh: bool = False,
    rotor_angle_mech_deg: float = 0.0,
) -> dict[str, Any] | None:
    """Build a compact per-position live-field-frame payload for SSE.

    FEMM can retriangulate each rotor position, so the backend must process
    that mesh locally. Normal GUI frames carry contour segments and compact
    airgap Br/Bt bins only; raw nodes/triangles/element arrays are included
    only when ``include_raw_mesh`` is true for diagnostics.

    Inputs:
      field_data: output of ``_read_femm_mesh_from_disk`` — must contain
                  ``nodes_mm``, ``triangles``, and ``az_nodal``.
      elec_angle_deg: electrical angle of this rotor position; the
                  frontend uses it to align the frame with the torque
                  chart cursor.
      geom: motor geometry for centroid-based airgap processing.
      include_raw_mesh: include FEMM's per-position mesh and element arrays.
                  Keep false for GUI solves; true is for payload diagnostics.

    Returns the payload dict, or ``None`` if the input mesh/Az data
    is incomplete.
    """
    from backend.field_lines import (
        generate_contour_levels,
        generate_contour_segments,
        generate_element_b_components,
    )

    nodes_mm = field_data.get("nodes_mm") or []
    triangles = field_data.get("triangles") or []
    az_nodal = field_data.get("az_nodal") or []
    if not nodes_mm or not triangles or not az_nodal:
        return None

    # 8 bands per side keeps FEMM and native flux patterns visually comparable.
    contour_levels = generate_contour_levels(az_nodal, bands_per_side=8)
    contours = generate_contour_segments(nodes_mm, triangles, az_nodal, contour_levels)
    payload: dict[str, Any] = {
        "angle_deg": _pack_femm_live_float(elec_angle_deg),
        "contour_levels": _pack_femm_live_contours(contours),
        "az_min": _pack_femm_live_float(min(az_nodal)),
        "az_max": _pack_femm_live_float(max(az_nodal)),
    }
    element_bx_t: list[float] = []
    element_by_t: list[float] = []
    if geom is not None or include_raw_mesh:
        element_bx_t, element_by_t = generate_element_b_components(
            nodes_mm, triangles, az_nodal
        )

    if geom is not None:
        pole_pitch_deg = 360.0 / max(1, geom.pole_count)
        payload["mesh_info"] = {
            "num_nodes": len(nodes_mm),
            "num_triangles": len(triangles),
            "pole_pitch_deg": pole_pitch_deg,
            # FEMM draws/parses the full mechanical machine. Report the full
            # 360° span so live Br/Bt plots do not fold the second half of the
            # airgap into the first electrical period.
            "n_pole_pitches": geom.pole_count,
            "total_span_deg": 360.0,
        }
        payload["n_pole_pitches"] = geom.pole_count
        payload["total_span_deg"] = 360.0
        airgap_brbt = _build_femm_airgap_brbt_profile(
            nodes_mm,
            triangles,
            element_bx_t,
            element_by_t,
            geom,
            span_deg=360.0,
        )
        if airgap_brbt is not None:
            payload["airgap_brbt"] = airgap_brbt

    if include_raw_mesh:
        element_b_mag_t = [
            math.hypot(bx, by)
            if math.isfinite(bx) and math.isfinite(by)
            else 0.0
            for bx, by in zip(element_bx_t, element_by_t)
        ]
        payload["element_b_mag_t"] = _pack_femm_live_float_list(element_b_mag_t)
        payload["element_bx_t"] = _pack_femm_live_float_list(element_bx_t)
        payload["element_by_t"] = _pack_femm_live_float_list(element_by_t)
        payload["nodes_mm"] = nodes_mm
        payload["triangles"] = triangles
        payload["regions"] = _classify_femm_triangles_by_centroid(
            nodes_mm,
            triangles,
            geom,
            rotor_angle_mech_deg=rotor_angle_mech_deg,
        ) if geom is not None else []
    return payload


def _build_femm_airgap_brbt_profile(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    element_bx_t: list[float],
    element_by_t: list[float],
    geom: "MotorGeometry",
    *,
    span_deg: float,
) -> dict[str, Any] | None:
    """Bin FEMM element fields into a compact airgap Br/Bt profile."""

    if (
        not nodes_mm
        or not triangles
        or not element_bx_t
        or not element_by_t
        or len(element_bx_t) != len(triangles)
        or len(element_by_t) != len(triangles)
    ):
        return None

    rotor_outer_with_magnets = geom.rotor_OD_r
    if geom.magnets:
        rotor_outer_with_magnets = max(
            geom.rotor_OD_r,
            max(m.outer_radius_mm for m in geom.magnets),
        )
    if geom.stator_ID_r <= rotor_outer_with_magnets:
        return None

    bin_count = _FEMM_LIVE_AIRGAP_BRBT_BIN_COUNT
    bins = [
        {"bmag": 0.0, "br": 0.0, "bt": 0.0, "brbt": 0.0, "samples": 0}
        for _ in range(bin_count)
    ]
    sample_count = 0
    normalized_span = max(1.0, min(360.0, span_deg))

    for tri_idx, tri in enumerate(triangles):
        if len(tri) != 3:
            continue
        try:
            i, j, k = tri
            na = nodes_mm[i]
            nb = nodes_mm[j]
            nc = nodes_mm[k]
            cx = (float(na[0]) + float(nb[0]) + float(nc[0])) / 3.0
            cy = (float(na[1]) + float(nb[1]) + float(nc[1])) / 3.0
        except (IndexError, TypeError, ValueError):
            continue

        centroid_radius_mm = math.hypot(cx, cy)
        if (
            centroid_radius_mm <= rotor_outer_with_magnets
            or centroid_radius_mm > geom.stator_ID_r
            or centroid_radius_mm <= 1e-9
        ):
            continue

        bx = element_bx_t[tri_idx]
        by = element_by_t[tri_idx]
        if not math.isfinite(bx) or not math.isfinite(by):
            continue

        bmag = math.hypot(bx, by)
        radial_x = cx / centroid_radius_mm
        radial_y = cy / centroid_radius_mm
        tangential_x = -radial_y
        tangential_y = radial_x
        br = bx * radial_x + by * radial_y
        bt = bx * tangential_x + by * tangential_y
        if not math.isfinite(br) or not math.isfinite(bt):
            continue

        raw_angle_deg = (math.degrees(math.atan2(cy, cx)) + 360.0) % 360.0
        airgap_angle_deg = (
            raw_angle_deg % normalized_span
            if normalized_span < 359.5
            else raw_angle_deg
        )
        bin_index = min(
            bin_count - 1,
            max(0, int((airgap_angle_deg / normalized_span) * bin_count)),
        )
        bin_acc = bins[bin_index]
        bin_acc["bmag"] += bmag
        bin_acc["br"] += br
        bin_acc["bt"] += bt
        bin_acc["brbt"] += br * bt
        bin_acc["samples"] += 1
        sample_count += 1

    if sample_count == 0:
        return None

    packed_bins: list[dict[str, Any]] = []
    for index, bin_acc in enumerate(bins):
        samples = int(bin_acc["samples"])
        if samples == 0:
            continue
        packed_bins.append(
            {
                "mech_angle_deg": _pack_femm_live_float(
                    ((index + 0.5) / bin_count) * normalized_span,
                    6,
                ),
                "b_magnitude_t": _pack_femm_live_float(bin_acc["bmag"] / samples),
                "br_t": _pack_femm_live_float(bin_acc["br"] / samples),
                "bt_t": _pack_femm_live_float(bin_acc["bt"] / samples),
                "br_bt_t2": _pack_femm_live_float(bin_acc["brbt"] / samples),
                "samples": samples,
            }
        )

    return {
        "span_deg": _pack_femm_live_float(normalized_span),
        "bin_count": bin_count,
        "sample_count": sample_count,
        "bins": packed_bins,
    }


def _classify_femm_triangles_by_centroid(
    nodes_mm: list[list[float]],
    triangles: list[list[int]],
    geom: "MotorGeometry",
    *,
    rotor_angle_mech_deg: float = 0.0,
) -> list[str]:
    """Assign one region tag per triangle based on its centroid position.

    Tags match what the frontend MotorViewport expects (see
    ``MESH_REGION_RENDER_ORDER`` in ``meshOverlayUtils.ts``):
    ``shaft``, ``rotor_core``, ``magnet``, ``inter_pole_gap``, ``airgap``,
    ``slot_winding``, ``stator_tooth``, ``stator_yoke``.

    Why centroid and not FEMM block labels: ``mo_getelement`` returns the
    block label index per element, but pulling it requires one Wine IPC
    round-trip per triangle — defeats the disk-parse fast path entirely.
    Centroid classification is geometric and deterministic from the
    MotorConfig we already have.

    Returns a list of length ``len(triangles)``. Order matches triangles.
    """
    is_ipm = str(geom.topology).upper() == "IPM"
    rotor_offset_rad = math.radians(rotor_angle_mech_deg)
    rotor_outer_with_magnets = geom.rotor_OD_r
    if geom.magnets:
        rotor_outer_with_magnets = max(
            geom.rotor_OD_r,
            max(m.outer_radius_mm for m in geom.magnets),
        )

    slot_outer_r = geom.stator_OD_r
    if geom.slots:
        slot_outer_r = max(s.outer_radius_mm for s in geom.slots)

    out: list[str] = [""] * len(triangles)
    for tri_idx, (i, j, k) in enumerate(triangles):
        # Triangle centroid in mm
        cx = (nodes_mm[i][0] + nodes_mm[j][0] + nodes_mm[k][0]) / 3.0
        cy = (nodes_mm[i][1] + nodes_mm[j][1] + nodes_mm[k][1]) / 3.0
        r = math.hypot(cx, cy)

        # ── Rotor side ────────────────────────────────────────────────
        if r < geom.shaft_r:
            out[tri_idx] = "shaft"
            continue
        if is_ipm:
            theta = math.atan2(cy, cx)
            for mag in geom.magnets:
                if mag.corners_mm is not None:
                    if rotor_offset_rad:
                        test_x = cx * math.cos(-rotor_offset_rad) - cy * math.sin(-rotor_offset_rad)
                        test_y = cx * math.sin(-rotor_offset_rad) + cy * math.cos(-rotor_offset_rad)
                    else:
                        test_x, test_y = cx, cy
                    if point_in_polygon(test_x, test_y, mag.corners_mm):
                        out[tri_idx] = "magnet"
                        break
                    continue
                if mag.inner_radius_mm <= r <= mag.outer_radius_mm:
                    delta = _normalize_signed_angle(
                        theta - (mag.center_angle_rad + rotor_offset_rad)
                    )
                    if abs(delta) <= mag.half_width_rad:
                        out[tri_idx] = "magnet"
                        break
            else:
                if r < geom.rotor_OD_r:
                    out[tri_idx] = "rotor_core"
                    continue
            if out[tri_idx] == "magnet":
                continue
        if r < geom.rotor_OD_r:
            out[tri_idx] = "rotor_core"
            continue
        if r <= rotor_outer_with_magnets:
            # In the magnet annulus — magnet if inside any magnet's angular
            # span, otherwise inter-pole gap (the "another shade of white"
            # the user wants visible).
            theta = math.atan2(cy, cx)
            for mag in geom.magnets:
                if mag.inner_radius_mm <= r <= mag.outer_radius_mm:
                    delta = _normalize_signed_angle(
                        theta - (mag.center_angle_rad + rotor_offset_rad)
                    )
                    if abs(delta) <= mag.half_width_rad:
                        out[tri_idx] = "magnet"
                        break
            else:
                out[tri_idx] = "inter_pole_gap"
            continue

        # ── Airgap ────────────────────────────────────────────────────
        if r <= geom.stator_ID_r:
            out[tri_idx] = "airgap"
            continue

        # ── Stator side ───────────────────────────────────────────────
        if r <= slot_outer_r:
            theta = math.atan2(cy, cx)
            inside_slot = False
            for slot in geom.slots:
                if slot.inner_radius_mm <= r <= slot.outer_radius_mm:
                    delta = _normalize_signed_angle(theta - slot.center_angle_rad)
                    if abs(delta) <= slot.half_width_at_radius(r):
                        out[tri_idx] = "slot_winding"
                        inside_slot = True
                        break
            if not inside_slot:
                out[tri_idx] = "stator_tooth"
            continue

        out[tri_idx] = "stator_yoke"

    return out


def _normalize_signed_angle(theta: float) -> float:
    """Wrap an angle into ``(-π, π]`` for half-width comparisons."""
    while theta > math.pi:
        theta -= 2 * math.pi
    while theta <= -math.pi:
        theta += 2 * math.pi
    return theta
