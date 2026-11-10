"""Build SVG preview regions by tessellating the shared geometry IR."""

from __future__ import annotations

import re

from backend.geometry_ir import GeometryIR, GeometryIRRegion
from backend.geometry_ir_tessellation import polygon_centroid, tessellate_ir_region
from backend.models import GeometryRegion, WindingSlot

PHASE_COLORS = {
    "A": "#F0A030",
    "B": "#34D399",
    "C": "#A78BFA",
}
PHASE_COLORS_DIM = {
    "A": "#A87020",
    "B": "#24956B",
    "C": "#7A60C4",
}


def preview_regions_from_geometry_ir(
    ir: GeometryIR,
    *,
    slotless_diagnostic: bool = False,
) -> list[GeometryRegion]:
    """Convert geometry IR regions into SVG preview polygons."""
    preview_regions: list[GeometryRegion] = []
    labeled_magnet_poles: set[int] = set()

    for region in ir.regions:
        if region.kind == "ExteriorAir":
            continue

        points = tessellate_ir_region(region)
        if not points:
            continue

        style = _preview_style_for_ir_region(
            region,
            slotless_diagnostic=slotless_diagnostic,
            labeled_magnet_poles=labeled_magnet_poles,
            ipm_topology=ir.ipm_topology,
        )
        if style is None:
            continue

        region_type, fill, label, text_label, text_position = style
        preview_regions.append(
            GeometryRegion(
                region_type=region_type,
                points=points,
                fill=fill,
                label=label,
                text_label=text_label,
                text_position=text_position,
            )
        )

    return preview_regions


def _preview_style_for_ir_region(
    region: GeometryIRRegion,
    *,
    slotless_diagnostic: bool,
    labeled_magnet_poles: set[int],
    ipm_topology: str | None,
) -> tuple[str, str, str, str | None, list[float] | None] | None:
    kind = region.kind

    if kind == "StatorYoke":
        label = "Slotless Stator" if slotless_diagnostic else "Stator Yoke"
        return ("stator_yoke", "#8A9BAD", label, None, None)

    if kind == "StatorTooth":
        tooth_idx = _trailing_index(region.region_id)
        return ("stator_tooth", "#7B8C9D", f"Tooth {tooth_idx}", None, None)

    if kind == "SlotWinding":
        return _slot_winding_style(region)

    if kind == "Airgap":
        return ("airgap", "none", "Airgap", None, None)

    if kind == "RotorCore":
        return ("rotor_core", "#4A5568", "Rotor Core", None, None)

    if kind == "Shaft":
        return ("shaft", "#2D3748", "Shaft", None, None)

    if kind == "Magnet":
        return _magnet_style(region, labeled_magnet_poles, ipm_topology=ipm_topology)

    if kind == "MagnetPocketAir":
        return _pocket_air_style(region)

    return None


def _slot_winding_style(
    region: GeometryIRRegion,
) -> tuple[str, str, str, None, None]:
    slot_index = _trailing_index(region.region_id)
    phase = "A"
    direction = "in"
    source = region.source_group or ""
    match = re.match(r"winding:([ABC]):(in|out):slot(\d+)", source)
    if match:
        phase = match.group(1)
        direction = match.group(2)
        slot_index = int(match.group(3))

    fill = (
        PHASE_COLORS.get(phase, "#888888")
        if direction == "in"
        else PHASE_COLORS_DIM.get(phase, "#88888899")
    )
    direction_symbol = "+" if direction == "in" else "−"
    label = f"Slot {slot_index + 1} ({phase}{direction_symbol})"
    region_type = label.lower().replace(" ", "_")
    return (region_type, fill, label, None, None)


def _magnet_style(
    region: GeometryIRRegion,
    labeled_magnet_poles: set[int],
    *,
    ipm_topology: str | None,
) -> tuple[str, str, str, str | None, list[float] | None]:
    polarity = "N"
    source = region.source_group or ""
    parts = source.split(":")
    if len(parts) >= 2 and parts[0] == "pm":
        polarity = parts[1]

    magnet_idx = _trailing_index(region.region_id)
    pole_idx = _magnet_pole_key(magnet_idx, ipm_topology)
    fill = "#E53E3E" if polarity == "N" else "#3182CE"
    label = f"Magnet {polarity} {pole_idx}"
    region_type = f"magnet_{polarity.lower()}_{pole_idx}"

    text_label: str | None = None
    text_position: list[float] | None = None
    if pole_idx not in labeled_magnet_poles:
        points = tessellate_ir_region(region)
        cx, cy = polygon_centroid(points)
        text_label = polarity
        text_position = [cx, cy]
        labeled_magnet_poles.add(pole_idx)

    return (region_type, fill, label, text_label, text_position)


def _magnet_pole_key(magnet_idx: int, ipm_topology: str | None) -> int:
    if ipm_topology in {"v_shape", "pyleecan_holem50"}:
        return magnet_idx // 2
    return magnet_idx


def _pocket_air_style(
    region: GeometryIRRegion,
) -> tuple[str, str, str, None, None]:
    region_id = region.region_id
    if region_id.startswith("spm_inter_pole_air_"):
        idx = _trailing_index(region_id)
        return (f"spm_inter_pole_air_{idx}", "#111827", f"Inter-pole air {idx}", None, None)

    if region_id.startswith("magnet_pocket_air_"):
        idx = _trailing_index(region_id)
        return (f"ipm_pocket_{idx}", "#111827", f"Pocket {idx}", None, None)

    return (region_id, "#111827", region_id.replace("_", " ").title(), None, None)


def _trailing_index(value: str) -> int:
    match = re.search(r"(\d+)$", value)
    return int(match.group(1)) if match else 0


def append_winding_symbols(
    regions: list[GeometryRegion],
    winding_layout: list[WindingSlot],
    *,
    bore_r: float,
    slot_bottom_r: float,
    slot_body_width: float,
    slot_pitch_rad: float,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """Add in/out winding marker glyphs (not part of geometry IR)."""
    import math

    radial_span = max(0.0, slot_bottom_r - bore_r)
    max_layer_by_slot: dict[int, int] = {}
    for slot in winding_layout:
        max_layer_by_slot[slot.slot_index] = max(
            max_layer_by_slot.get(slot.slot_index, 1),
            int(getattr(slot, "layer", 1) or 1),
        )

    for ws in sorted(winding_layout, key=lambda item: (item.slot_index, item.layer)):
        slot_idx = ws.slot_index
        layer_count = max_layer_by_slot.get(slot_idx, 1)
        slot_center_r = bore_r + radial_span * (ws.layer - 0.5) / max(1, layer_count)
        slot_angle = slot_idx * slot_pitch_rad
        cx = origin_x + slot_center_r * math.cos(slot_angle)
        cy = origin_y + slot_center_r * math.sin(slot_angle)
        symbol_size = slot_body_width * (0.11 if layer_count > 1 else 0.15)

        if ws.direction == "in":
            dot_pts = []
            for i in range(8):
                a = (i / 8) * 2 * math.pi
                dot_pts.append([cx + symbol_size * math.cos(a), cy + symbol_size * math.sin(a)])
            dot_pts.append(dot_pts[0])
            regions.append(
                GeometryRegion(
                    region_type="winding_symbol",
                    points=dot_pts,
                    fill="#FFFFFF",
                    label=f"{ws.phase}+ (in)",
                )
            )
            continue

        for angle_offset in [math.pi / 4, -math.pi / 4]:
            line_pts = [
                [
                    cx + symbol_size * math.cos(slot_angle + angle_offset),
                    cy + symbol_size * math.sin(slot_angle + angle_offset),
                ],
                [
                    cx - symbol_size * math.cos(slot_angle + angle_offset),
                    cy - symbol_size * math.sin(slot_angle + angle_offset),
                ],
                [
                    cx - symbol_size * math.cos(slot_angle + angle_offset)
                    + 0.3 * math.cos(slot_angle + angle_offset + math.pi / 2),
                    cy - symbol_size * math.sin(slot_angle + angle_offset)
                    + 0.3 * math.sin(slot_angle + angle_offset + math.pi / 2),
                ],
                [
                    cx + symbol_size * math.cos(slot_angle + angle_offset)
                    + 0.3 * math.cos(slot_angle + angle_offset + math.pi / 2),
                    cy + symbol_size * math.sin(slot_angle + angle_offset)
                    + 0.3 * math.sin(slot_angle + angle_offset + math.pi / 2),
                ],
            ]
            line_pts.append(line_pts[0])
            regions.append(
                GeometryRegion(
                    region_type="winding_symbol",
                    points=line_pts,
                    fill="#FFFFFF",
                    label=f"{ws.phase}− (out)",
                )
            )
