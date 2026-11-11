"""Durable Halbach report exports with the permanent 2D-model notice."""

from __future__ import annotations

import colorsys
import csv
import io
import json
import math
from typing import Any

from backend.export_safety import literal_csv_cell

from .geometry import AXIAL_END_EFFECTS_NOTICE
from .linear_geometry import LINEAR_MODEL_NOTICE


def _format_optional_metric(
    value: float | int | None,
    *,
    suffix: str = "",
    precision: str = ".6g",
) -> str:
    if value is None:
        return "unavailable"
    return f"{format(value, precision)}{suffix}"


def _magnetization_angles(report: dict[str, Any], segment_count: int) -> list[float]:
    segments = report.get("magnet", {}).get("segments", [])
    if not isinstance(segments, list) or len(segments) != segment_count:
        raise ValueError("report magnet segment provenance is incomplete")
    return [float(segment["magnetization_angle_deg"]) for segment in segments]


def halbach_report_json(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def magnetostatic_problem_json(report: dict[str, Any]) -> bytes:
    problem = report.get("magnetostatic_problem")
    if not isinstance(problem, dict):
        raise ValueError("report does not contain a replayable magnetostatic_problem")
    return (json.dumps(problem, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def generic_field_report_json(report: dict[str, Any]) -> bytes:
    field_report = report.get("generic_field_report")
    if not isinstance(field_report, dict):
        raise ValueError("report does not contain a generic field_solution_report")
    return (json.dumps(field_report, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def samples_csv(report: dict[str, Any]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["openem_schema_kind", "halbach_field_samples"])
    writer.writerow(["openem_schema_version", "1.0"])
    writer.writerow(["axial_end_effects_modeled", "false"])
    writer.writerow(["model_notice", AXIAL_END_EFFECTS_NOTICE])
    writer.writerow([])
    writer.writerow(
        [
            "sample_set",
            "index",
            "x_mm",
            "y_mm",
            "angle_deg",
            "bx_t",
            "by_t",
            "b_magnitude_t",
            "b_parallel_t",
            "b_perpendicular_t",
            "element_index",
        ]
    )
    samples = report.get("samples", {})
    for sample_set in ("bore", "leakage"):
        rows = samples.get(sample_set, [])
        for index, sample in enumerate(rows):
            writer.writerow(
                [literal_csv_cell(value) for value in (
                    sample_set,
                    index,
                    sample.get("x_mm"),
                    sample.get("y_mm"),
                    sample.get("angle_deg"),
                    sample.get("bx_t"),
                    sample.get("by_t"),
                    sample.get("b_magnitude_t"),
                    sample.get("b_parallel_t"),
                    sample.get("b_perpendicular_t"),
                    sample.get("element_index"),
                )]
            )
    return stream.getvalue().encode("utf-8")


def design_svg(report: dict[str, Any]) -> bytes:
    config = report["configuration"]
    geometry = config["geometry"]
    n = int(geometry["segment_count"])
    ri = float(geometry["inner_radius"])
    ro = float(geometry["outer_radius"])
    gap = float(geometry["segment_gap_angle"])
    start = float(geometry["segment_start_angle"])
    scale = 220.0 / ro
    center = 250.0

    def point(radius: float, angle_deg: float) -> tuple[float, float]:
        angle = math.radians(angle_deg)
        return (
            center + radius * scale * math.cos(angle),
            center - radius * scale * math.sin(angle),
        )

    paths: list[str] = []
    arrows: list[str] = []
    pitch = 360.0 / n
    magnetization_angles = _magnetization_angles(report, n)
    for index in range(n):
        theta = start + (index + 0.5) * pitch
        a0 = theta - 0.5 * (pitch - gap)
        a1 = theta + 0.5 * (pitch - gap)
        o0 = point(ro, a0)
        o1 = point(ro, a1)
        i1 = point(ri, a1)
        i0 = point(ri, a0)
        large = 1 if a1 - a0 > 180.0 else 0
        hue = (index * 360.0 / n) % 360.0
        path = (
            f"M {o0[0]:.3f} {o0[1]:.3f} "
            f"A {ro*scale:.3f} {ro*scale:.3f} 0 {large} 0 {o1[0]:.3f} {o1[1]:.3f} "
            f"L {i1[0]:.3f} {i1[1]:.3f} "
            f"A {ri*scale:.3f} {ri*scale:.3f} 0 {large} 1 {i0[0]:.3f} {i0[1]:.3f} Z"
        )
        paths.append(
            f'<path d="{path}" fill="hsl({hue:.1f} 58% 47%)" '
            'stroke="#e5e7eb" stroke-width="1.2"/>'
        )
        alpha = magnetization_angles[index]
        midpoint = 0.5 * (ri + ro)
        origin = point(midpoint, theta)
        length = 0.28 * (ro - ri) * scale
        dx = length * math.cos(math.radians(alpha))
        dy = -length * math.sin(math.radians(alpha))
        arrows.append(
            f'<line x1="{origin[0]-dx/2:.3f}" y1="{origin[1]-dy/2:.3f}" '
            f'x2="{origin[0]+dx/2:.3f}" y2="{origin[1]+dy/2:.3f}" '
            'stroke="#fff" stroke-width="2" marker-end="url(#arrow)"/>'
        )
    direction = float(config["array"]["field_direction"])
    dx = 42.0 * math.cos(math.radians(direction))
    dy = -42.0 * math.sin(math.radians(direction))
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="560" viewBox="0 0 720 560">
<rect width="720" height="560" fill="#0b1020"/>
<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="5" markerHeight="5" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"/>
  </marker>
</defs>
<g>{''.join(paths)}{''.join(arrows)}</g>
<circle cx="{center}" cy="{center}"
        r="{float(config['sample_region']['radius'])*scale:.3f}"
        fill="none" stroke="#67e8f9" stroke-width="1.5"
        stroke-dasharray="5 4"/>
<line x1="{center}" y1="{center}" x2="{center+dx:.3f}" y2="{center+dy:.3f}" stroke="#fbbf24" stroke-width="4" marker-end="url(#arrow)"/>
<text x="500" y="65" fill="#f8fafc" font-family="sans-serif" font-size="22" font-weight="700">Cylindrical Halbach array</text>
<text x="500" y="94" fill="#94a3b8" font-family="sans-serif" font-size="15">{n} segments · p = 1 internal field</text>
<text x="28" y="525" fill="#fbbf24" font-family="sans-serif" font-size="14">{AXIAL_END_EFFECTS_NOTICE}</text>
</svg>"""
    return svg.encode("utf-8")


def design_png(report: dict[str, Any]) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - public package pins pillow
        raise RuntimeError("Pillow is required for Halbach PNG export") from exc

    config = report["configuration"]
    geometry = config["geometry"]
    n = int(geometry["segment_count"])
    ri = float(geometry["inner_radius"])
    ro = float(geometry["outer_radius"])
    gap = float(geometry["segment_gap_angle"])
    start = float(geometry["segment_start_angle"])
    scale = 220.0 / ro
    center = (250.0, 250.0)
    image = Image.new("RGB", (720, 560), "#0b1020")
    draw = ImageDraw.Draw(image)

    def point(radius: float, angle_deg: float) -> tuple[float, float]:
        angle = math.radians(angle_deg)
        return (
            center[0] + radius * scale * math.cos(angle),
            center[1] - radius * scale * math.sin(angle),
        )

    def arrow(origin: tuple[float, float], angle_deg: float, length: float, color: str, width: int) -> None:
        angle = math.radians(angle_deg)
        dx = length * math.cos(angle)
        dy = -length * math.sin(angle)
        start_point = (origin[0] - dx / 2.0, origin[1] - dy / 2.0)
        end_point = (origin[0] + dx / 2.0, origin[1] + dy / 2.0)
        draw.line([start_point, end_point], fill=color, width=width)
        head = max(5.0, width * 2.4)
        for offset in (-28.0, 28.0):
            branch_angle = angle + math.pi + math.radians(offset)
            branch = (
                end_point[0] + head * math.cos(branch_angle),
                end_point[1] - head * math.sin(branch_angle),
            )
            draw.line([end_point, branch], fill=color, width=width)

    pitch = 360.0 / n
    magnetization_angles = _magnetization_angles(report, n)
    for index in range(n):
        theta = start + (index + 0.5) * pitch
        a0 = theta - 0.5 * (pitch - gap)
        a1 = theta + 0.5 * (pitch - gap)
        angular_steps = max(3, int(math.ceil((a1 - a0) / 2.0)))
        polygon = [
            point(ro, a0 + (a1 - a0) * step / angular_steps)
            for step in range(angular_steps + 1)
        ]
        polygon.extend(
            point(ri, a0 + (a1 - a0) * step / angular_steps)
            for step in range(angular_steps, -1, -1)
        )
        hue = (index * 360.0 / n) % 360.0
        # HSV gives the same stable per-segment identity as the SVG export.
        rgb = tuple(
            round(component * 255.0)
            for component in colorsys.hsv_to_rgb(hue / 360.0, 0.58, 0.75)
        )
        draw.polygon(polygon, fill=rgb, outline="#e5e7eb", width=1)
        alpha = magnetization_angles[index]
        arrow(
            point(0.5 * (ri + ro), theta),
            alpha,
            0.28 * (ro - ri) * scale,
            "#ffffff",
            2,
        )

    roi_radius = float(config["sample_region"]["radius"]) * scale
    draw.ellipse(
        [
            center[0] - roi_radius,
            center[1] - roi_radius,
            center[0] + roi_radius,
            center[1] + roi_radius,
        ],
        outline="#67e8f9",
        width=2,
    )
    arrow(
        center,
        float(config["array"]["field_direction"]),
        84.0,
        "#fbbf24",
        4,
    )
    draw.text((500, 62), "Cylindrical Halbach array", fill="#f8fafc")
    draw.text((500, 90), f"{n} segments · p = 1 internal field", fill="#94a3b8")
    draw.multiline_text(
        (28, 518),
        "2D cross-section extruded over the design length —\n"
        "axial end effects are not included.",
        fill="#fbbf24",
        spacing=2,
    )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def report_pdf(report: dict[str, Any]) -> bytes:
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - packaging pins reportlab
        raise RuntimeError("reportlab is required for Halbach PDF export") from exc

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title="coilEM Cylindrical Halbach Array Report",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Cylindrical Halbach Array — 2D Magnetostatic Report", styles["Title"]),
        Spacer(1, 10),
        Paragraph(
            f"<b>Model fidelity:</b> {AXIAL_END_EFFECTS_NOTICE}",
            styles["Heading3"],
        ),
        Spacer(1, 10),
    ]
    bore = report["bore_field"]
    leakage = report["external_leakage"]
    magnet = report["magnet"]
    rows = [
        ["Metric", "Value"],
        ["Mean bore field", f"{bore['b_parallel_t']['mean']:.6g} T"],
        ["Field direction error", f"{bore['mean_field_direction_error_deg']:.4g}°"],
        [
            "Bore uniformity",
            _format_optional_metric(bore["uniformity_ppm"], suffix=" ppm"),
        ],
        ["Leakage RMS", f"{leakage['rms_b_t']:.6g} T"],
        [
            "Leakage ratio",
            _format_optional_metric(leakage["leakage_ratio_rms"]),
        ],
        ["Magnet volume", f"{magnet['volume_m3']:.6g} m³"],
        [
            "Magnet mass",
            "unavailable"
            if magnet["mass_kg"] is None
            else f"{magnet['mass_kg']:.6g} kg",
        ],
        [
            "Analytical segmented estimate",
            f"{bore['segmented_analytical_estimate_t']:.6g} T",
        ],
    ]
    table = Table(rows, colWidths=[2.6 * inch, 3.7 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#172033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
                ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#94a3b8")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#f8fafc"), HexColor("#eef2f7")]),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 16),
            Paragraph("Material provenance", styles["Heading2"]),
            Paragraph(
                json.dumps(magnet["material"], indent=2)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>"),
                styles["Code"],
            ),
            PageBreak(),
            Paragraph("Demagnetization screening", styles["Heading2"]),
            Paragraph(
                "Screening diagnostic — not a demagnetization certification.",
                styles["Heading3"],
            ),
            Paragraph(
                json.dumps(magnet["demagnetization_screening"], indent=2)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>"),
                styles["Code"],
            ),
            Spacer(1, 16),
            Paragraph("Solver timing and provenance", styles["Heading2"]),
            Paragraph(
                json.dumps(
                    {
                        "timings_ms": report["timings_ms"],
                        "peak_memory_bytes": report["peak_memory_bytes"],
                        "artifacts": report["artifacts"],
                    },
                    indent=2,
                )
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>"),
                styles["Code"],
            ),
            Spacer(1, 18),
            Paragraph(
                f"<b>Persistent limitation:</b> {AXIAL_END_EFFECTS_NOTICE}",
                styles["Heading3"],
            ),
        ]
    )
    document.build(story)
    return output.getvalue()


# --- Linear array exports -------------------------------------------------
#
# The linear report carries the block rectangles, their magnetization angles
# and both probe lines, so every drawing below is rebuilt from the solved
# report alone. Nothing is recomputed and nothing is assumed about the design
# beyond what the report states.


def _linear_blocks(report: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = report.get("magnet", {}).get("blocks", [])
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("report magnet block provenance is incomplete")
    resolved = []
    for block in blocks:
        bounds = [float(value) for value in block["bounds_mm"]]
        if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
            raise ValueError("report magnet block bounds are incomplete")
        angle = float(block["magnetization_angle_deg"])
        if not math.isfinite(angle):
            raise ValueError("report magnet block magnetization is incomplete")
        resolved.append({"bounds_mm": bounds, "angle_deg": angle})
    return resolved


def _linear_probe_lines(report: dict[str, Any]) -> list[dict[str, Any]]:
    lines = []
    for key, label, color in (
        ("working_field", "working line", "#67e8f9"),
        ("leakage_field", "weak-side line", "#f0a35b"),
    ):
        section = report[key]
        values = (
            float(section["line_y_mm"]),
            float(section["x_start_mm"]),
            float(section["x_end_mm"]),
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("report probe line is incomplete")
        lines.append(
            {
                "y_mm": values[0],
                "x_start_mm": values[1],
                "x_end_mm": values[2],
                "label": label,
                "color": color,
            }
        )
    return lines


def _linear_layout(
    blocks: list[dict[str, Any]],
    lines: list[dict[str, Any]],
) -> tuple[float, float, float]:
    """Return scale (px/mm) and the drawing centre for a 720 x 560 canvas."""

    x_values = [value for block in blocks for value in block["bounds_mm"][0::2]]
    y_values = [value for block in blocks for value in block["bounds_mm"][1::2]]
    for line in lines:
        x_values.extend((line["x_start_mm"], line["x_end_mm"]))
        y_values.append(line["y_mm"])
    half_width = max(abs(value) for value in x_values)
    half_height = max(abs(value) for value in y_values)
    if not (half_width > 0.0 and half_height > 0.0):
        raise ValueError("report geometry has no drawable extent")
    scale = min(310.0 / half_width, 150.0 / half_height)
    return scale, 360.0, 270.0


def _linear_caption(report: dict[str, Any], block_count: int) -> str:
    config = report["configuration"]
    periods = int(config["geometry"]["period_count"])
    side = "+Y" if config["array"]["strong_side"] == "positive_y" else "-Y"
    return (
        f"{block_count} magnets · {periods} period"
        f"{'' if periods == 1 else 's'} · enhanced side {side}"
    )


def linear_samples_csv(report: dict[str, Any]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["openem_schema_kind", "linear_halbach_field_samples"])
    writer.writerow(["openem_schema_version", "1.0"])
    writer.writerow(["out_of_plane_end_effects_modeled", "false"])
    writer.writerow(["model_notice", LINEAR_MODEL_NOTICE])
    writer.writerow([])
    writer.writerow(
        [
            "sample_set",
            "index",
            "x_mm",
            "y_mm",
            "bx_t",
            "by_t",
            "b_magnitude_t",
            "element_index",
        ]
    )
    samples = report.get("samples", {})
    for sample_set in ("working", "leakage"):
        rows = samples.get(sample_set, [])
        for index, sample in enumerate(rows):
            writer.writerow(
                [literal_csv_cell(value) for value in (
                    sample_set,
                    index,
                    sample.get("x_mm"),
                    sample.get("y_mm"),
                    sample.get("bx_t"),
                    sample.get("by_t"),
                    sample.get("b_magnitude_t"),
                    sample.get("element_index"),
                )]
            )
    return stream.getvalue().encode("utf-8")


def linear_design_svg(report: dict[str, Any]) -> bytes:
    blocks = _linear_blocks(report)
    lines = _linear_probe_lines(report)
    scale, center_x, center_y = _linear_layout(blocks, lines)

    def point(x_mm: float, y_mm: float) -> tuple[float, float]:
        return (center_x + x_mm * scale, center_y - y_mm * scale)

    shapes: list[str] = []
    arrows: list[str] = []
    for block in blocks:
        xmin, ymin, xmax, ymax = block["bounds_mm"]
        left, top = point(xmin, ymax)
        width = (xmax - xmin) * scale
        height = (ymax - ymin) * scale
        hue = block["angle_deg"] % 360.0
        shapes.append(
            f'<rect x="{left:.3f}" y="{top:.3f}" width="{width:.3f}" '
            f'height="{height:.3f}" fill="hsl({hue:.1f} 58% 47%)" '
            'stroke="#e5e7eb" stroke-width="1.2"/>'
        )
        origin = point(0.5 * (xmin + xmax), 0.5 * (ymin + ymax))
        length = 0.5 * min(width, height)
        dx = length * math.cos(math.radians(block["angle_deg"]))
        dy = -length * math.sin(math.radians(block["angle_deg"]))
        arrows.append(
            f'<line x1="{origin[0]-dx/2:.3f}" y1="{origin[1]-dy/2:.3f}" '
            f'x2="{origin[0]+dx/2:.3f}" y2="{origin[1]+dy/2:.3f}" '
            'stroke="#fff" stroke-width="2" marker-end="url(#arrow)"/>'
        )
    probes: list[str] = []
    for line in lines:
        start = point(line["x_start_mm"], line["y_mm"])
        end = point(line["x_end_mm"], line["y_mm"])
        label_y = start[1] - 8.0 if line["y_mm"] > 0.0 else start[1] + 18.0
        probes.append(
            f'<line x1="{start[0]:.3f}" y1="{start[1]:.3f}" '
            f'x2="{end[0]:.3f}" y2="{end[1]:.3f}" stroke="{line["color"]}" '
            'stroke-width="1.5" stroke-dasharray="7 5"/>'
            f'<text x="{start[0]:.3f}" y="{label_y:.3f}" fill="{line["color"]}" '
            f'font-family="sans-serif" font-size="13">{line["label"]}</text>'
        )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="560" viewBox="0 0 720 560">
<rect width="720" height="560" fill="#0b1020"/>
<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="5" markerHeight="5" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"/>
  </marker>
</defs>
<g>{''.join(shapes)}{''.join(arrows)}</g>
<g>{''.join(probes)}</g>
<text x="28" y="48" fill="#f8fafc" font-family="sans-serif" font-size="22" font-weight="700">Linear Halbach array</text>
<text x="28" y="76" fill="#94a3b8" font-family="sans-serif" font-size="15">{_linear_caption(report, len(blocks))}</text>
<text x="28" y="525" fill="#fbbf24" font-family="sans-serif" font-size="14">{LINEAR_MODEL_NOTICE}</text>
</svg>"""
    return svg.encode("utf-8")


def linear_design_png(report: dict[str, Any]) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - public package pins pillow
        raise RuntimeError("Pillow is required for Halbach PNG export") from exc

    blocks = _linear_blocks(report)
    lines = _linear_probe_lines(report)
    scale, center_x, center_y = _linear_layout(blocks, lines)
    image = Image.new("RGB", (720, 560), "#0b1020")
    draw = ImageDraw.Draw(image)

    def point(x_mm: float, y_mm: float) -> tuple[float, float]:
        return (center_x + x_mm * scale, center_y - y_mm * scale)

    def arrow(origin: tuple[float, float], angle_deg: float, length: float) -> None:
        angle = math.radians(angle_deg)
        dx = length * math.cos(angle)
        dy = -length * math.sin(angle)
        start_point = (origin[0] - dx / 2.0, origin[1] - dy / 2.0)
        end_point = (origin[0] + dx / 2.0, origin[1] + dy / 2.0)
        draw.line([start_point, end_point], fill="#ffffff", width=2)
        head = 5.0
        for offset in (-28.0, 28.0):
            branch_angle = angle + math.pi + math.radians(offset)
            branch = (
                end_point[0] + head * math.cos(branch_angle),
                end_point[1] - head * math.sin(branch_angle),
            )
            draw.line([end_point, branch], fill="#ffffff", width=2)

    for block in blocks:
        xmin, ymin, xmax, ymax = block["bounds_mm"]
        left, top = point(xmin, ymax)
        right, bottom = point(xmax, ymin)
        hue = block["angle_deg"] % 360.0
        # HSV gives the same stable per-direction identity as the SVG export.
        rgb = tuple(
            round(component * 255.0)
            for component in colorsys.hsv_to_rgb(hue / 360.0, 0.58, 0.75)
        )
        draw.rectangle([left, top, right, bottom], fill=rgb, outline="#e5e7eb", width=1)
        arrow(
            point(0.5 * (xmin + xmax), 0.5 * (ymin + ymax)),
            block["angle_deg"],
            0.5 * min(right - left, bottom - top),
        )

    for line in lines:
        start = point(line["x_start_mm"], line["y_mm"])
        end = point(line["x_end_mm"], line["y_mm"])
        # Pillow has no dashed stroke, so the dashes are drawn one by one.
        position = min(start[0], end[0])
        stop = max(start[0], end[0])
        while position < stop:
            draw.line(
                [(position, start[1]), (min(position + 7.0, stop), start[1])],
                fill=line["color"],
                width=2,
            )
            position += 12.0
        label_y = start[1] - 16.0 if line["y_mm"] > 0.0 else start[1] + 6.0
        draw.text((min(start[0], end[0]), label_y), line["label"], fill=line["color"])

    draw.text((28, 32), "Linear Halbach array", fill="#f8fafc")
    draw.text((28, 54), _linear_caption(report, len(blocks)), fill="#94a3b8")
    draw.text((28, 518), LINEAR_MODEL_NOTICE, fill="#fbbf24")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _pdf_code_block(value: Any) -> str:
    return (
        json.dumps(value, indent=2)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def linear_report_pdf(report: dict[str, Any]) -> bytes:
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - packaging pins reportlab
        raise RuntimeError("reportlab is required for Halbach PDF export") from exc

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title="coilEM Linear Halbach Array Report",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Linear Halbach Array: 2D Magnetostatic Report", styles["Title"]),
        Spacer(1, 10),
        Paragraph(
            f"<b>Model fidelity:</b> {LINEAR_MODEL_NOTICE}",
            styles["Heading3"],
        ),
        Spacer(1, 10),
    ]
    working = report["working_field"]
    leakage = report["leakage_field"]
    one_sidedness = report["one_sidedness"]
    magnet = report["magnet"]
    rows = [
        ["Metric", "Value"],
        ["Working-line RMS |B|", f"{working['b_magnitude_t']['rms']:.6g} T"],
        ["Working mean |B|", f"{working['b_magnitude_t']['mean']:.6g} T"],
        ["Working peak |B|", f"{working['b_magnitude_t']['maximum']:.6g} T"],
        [
            "Working-line ripple",
            _format_optional_metric(working.get("ripple_ppm"), suffix=" ppm"),
        ],
        ["Weak-side RMS |B|", f"{leakage['b_magnitude_t']['rms']:.6g} T"],
        [
            "Leakage ratio (weak-side RMS / working RMS)",
            _format_optional_metric(one_sidedness.get("leakage_ratio_rms")),
        ],
        [
            "Suppression ratio (working RMS / weak-side RMS)",
            _format_optional_metric(one_sidedness.get("suppression_ratio")),
        ],
        ["Working line y", f"{float(working['line_y_mm']):.6g} mm"],
        ["Weak-side line y", f"{float(leakage['line_y_mm']):.6g} mm"],
        ["Samples per line", f"{int(working['sample_count'])}"],
        ["Magnet volume", f"{magnet['volume_m3']:.6g} m³"],
        [
            "Magnet mass",
            "unavailable"
            if magnet.get("mass_kg") is None
            else f"{magnet['mass_kg']:.6g} kg",
        ],
    ]
    table = Table(rows, colWidths=[3.3 * inch, 3.0 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#172033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
                ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#94a3b8")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#f8fafc"), HexColor("#eef2f7")]),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 16),
            Paragraph("Material provenance", styles["Heading2"]),
            Paragraph(_pdf_code_block(magnet["material"]), styles["Code"]),
            PageBreak(),
            Paragraph("Demagnetization screening", styles["Heading2"]),
            Paragraph(
                "Screening diagnostic, not a demagnetization certification.",
                styles["Heading3"],
            ),
            Paragraph(
                _pdf_code_block(magnet.get("demagnetization_screening", {})),
                styles["Code"],
            ),
            Spacer(1, 16),
            Paragraph("Solver timing and provenance", styles["Heading2"]),
            Paragraph(
                _pdf_code_block(
                    {
                        "timings_ms": report["timings_ms"],
                        "peak_memory_bytes": report["peak_memory_bytes"],
                        "artifacts": report["artifacts"],
                    }
                ),
                styles["Code"],
            ),
            Spacer(1, 18),
            Paragraph(
                f"<b>Persistent limitation:</b> {LINEAR_MODEL_NOTICE}",
                styles["Heading3"],
            ),
        ]
    )
    document.build(story)
    return output.getvalue()
