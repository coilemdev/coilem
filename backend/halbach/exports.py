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
