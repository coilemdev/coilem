"""Public, single-run report exports built only from immutable stored inputs.

This module is intentionally independent from the private application report
surface. Callers provide plain mappings captured by the durable solve workspace;
no solver, geometry, or live application state is read.
"""

from __future__ import annotations

import csv
import io
import json
import math
import shutil
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from PIL import ImageDraw
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.export_safety import literal_csv_cell
from backend.local_file_safety import require_contained_path

PUBLIC_REPORT_SCHEMA = "coilem.single_run_report.v1"
PUBLIC_REPORT_LIMITATIONS = (
    "Electromagnetic analysis only; temperature prediction is not included.",
    "M350-50A uses an open reference B-H curve. Supplier-specific loss data is not included.",
    "Results describe the stored mesh, operating point, and solver build. Manufacturing tolerances require separate validation.",
)
SIX_STEP_REPORT_LIMITATION = (
    "Ideal six-step is an ideal current excitation only; PWM, switching ripple, "
    "Hall timing, dead time, ESC dynamics, switching loss, and startup behavior are not modeled."
)

_NAVY = colors.HexColor("#0B172A")
_BLUE = colors.HexColor("#2563EB")
_GREEN = colors.HexColor("#059669")
_RED = colors.HexColor("#DC2626")
_SLATE = colors.HexColor("#475569")
_LIGHT = colors.HexColor("#F1F5F9")
_BORDER = colors.HexColor("#CBD5E1")
_WHITE = colors.white

# Match the public field viewer's discrete flux-density palette.
_HEAT_COLORS = (
    "#142a61", "#1855a7", "#1b8eb7", "#2ab673",
    "#a7c83a", "#f1c232", "#f58b24", "#dc3d3d",
)
_REGION_COLORS = {
    "stator": ("Stator steel", "#8A9BAD"),
    "rotor": ("Rotor steel", "#4A5568"),
    "winding": ("Windings", "#F0A030"),
    "magnet": ("Magnets", "#E53E3E"),
    "shaft": ("Shaft", "#D6D3D1"),
    "air": ("Air / pockets", "#F1F5F9"),
    "other": ("Other region", "#D6D3D1"),
}

_SUMMARY_UNITS = {
    "avg_torque_Nm": "N m",
    "torque_ripple_pct": "%",
    "back_emf_fundamental_V": "V",
    "back_emf_thd_pct": "%",
    "back_emf_thd_h6_pct": "%",
    "back_emf_thd_h12_pct": "%",
    "back_emf_thd_h24_pct": "%",
    "back_emf_line_thd_h12_pct": "%",
    "back_emf_line_thd_h24_pct": "%",
    "Kt_Nm_per_A": "N m/A",
    "peak_flux_density_teeth_T": "T",
    "peak_flux_density_yoke_T": "T",
    "solve_time_s": "s",
}
_SUMMARY_LABELS = {
    "avg_torque_Nm": "Average torque",
    "torque_ripple_pct": "Torque ripple",
    "back_emf_fundamental_V": "Back EMF fundamental",
    "back_emf_thd_pct": "Back EMF THD headline",
    "back_emf_thd_h6_pct": "Back EMF phase THD H6 (legacy band)",
    "back_emf_thd_h12_pct": "Back EMF phase THD H12",
    "back_emf_thd_h24_pct": "Back EMF phase THD H24",
    "back_emf_line_thd_h12_pct": "Back EMF line AB THD H12",
    "back_emf_line_thd_h24_pct": "Back EMF line AB THD H24",
    "Kt_Nm_per_A": "Torque constant",
    "peak_flux_density_teeth_T": "Peak tooth flux density",
    "peak_flux_density_yoke_T": "Peak yoke flux density",
    "solve_time_s": "Solve time",
}
_SUMMARY_ORDER = tuple(_SUMMARY_LABELS)


def _plain(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return format(value, ".12g")
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
    return str(value)


def _flatten(value: Any, *, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten(value[key], prefix=child)
    elif isinstance(value, (list, tuple)):
        if not value:
            yield prefix, []
        else:
            for index, child_value in enumerate(value):
                yield from _flatten(child_value, prefix=f"{prefix}[{index}]")
    else:
        yield prefix, value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, (list, tuple)) else ()


def _warnings(result: Mapping[str, Any]) -> tuple[str, ...]:
    raw = result.get("warnings")
    if isinstance(raw, str) and raw.strip():
        return (raw.strip(),)
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        found = tuple(str(item).strip() for item in raw if str(item).strip())
        if found:
            return found
    raw = _mapping(result.get("solve_metadata")).get("warnings")
    if isinstance(raw, str) and raw.strip():
        return (raw.strip(),)
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def _safe_paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(_plain(value)), style)


def _metric_value(value: Any, unit: str) -> str:
    text = _plain(value)
    return f"{text} {unit}".strip() if text else "Not recorded"


def build_public_run_csv(
    *,
    project: Mapping[str, Any],
    request: Mapping[str, Any],
    result: Mapping[str, Any],
    material: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> bytes:
    """Return the canonical, long-form CSV for one stored solve run."""

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(["report_schema", PUBLIC_REPORT_SCHEMA])
    writer.writerow(["section", "field", "unit", "value", "sample_index"])

    def row(
        section: str,
        field: str,
        value: Any,
        unit: str = "",
        sample_index: int | str = "",
    ) -> None:
        writer.writerow([_plain(literal_csv_cell(item)) for item in (section, field, unit, value, sample_index)])

    row("identity", "project_name", manifest.get("project_name"))
    row("identity", "project_slug", manifest.get("project_slug"))
    row("identity", "run_id", manifest.get("run_id"))
    row("identity", "started_at", manifest.get("started_at"))
    row("identity", "completed_at", manifest.get("completed_at"))
    row("identity", "project_schema", project.get("openem_schema_version"))
    row("identity", "request_schema", request.get("schema_version"))

    for field, value in _flatten(_mapping(manifest.get("provenance"))):
        row("provenance", field, value)
    for field, value in _flatten(_mapping(manifest.get("bindings"))):
        row("binding", field, value)
    for index, record in enumerate(_sequence(material.get("records"))):
        for field, value in _flatten(record):
            row("material", field, value, sample_index=index)

    resolved_config = _mapping(request.get("resolved_config"))
    for field, value in _flatten(resolved_config):
        row("setting", field, value)

    summary = _mapping(result.get("summary"))
    known = set(_SUMMARY_ORDER)
    for field in (*_SUMMARY_ORDER, *sorted(set(summary) - known)):
        if field in summary:
            row("summary", field, summary[field], _SUMMARY_UNITS.get(field, ""))
    for field, value in _flatten(_mapping(result.get("solve_metadata"))):
        row("solve_metadata", field, value)

    torque = _mapping(result.get("torque_waveform"))
    torque_angles = _sequence(torque.get("electrical_angle_deg"))
    torque_values = _sequence(torque.get("torque_Nm"))
    for index in range(max(len(torque_angles), len(torque_values))):
        if index < len(torque_angles):
            row("torque_waveform", "electrical_angle_deg", torque_angles[index], "deg", index)
        if index < len(torque_values):
            row("torque_waveform", "torque_Nm", torque_values[index], "N m", index)

    phase_current = _mapping(result.get("phase_current_waveform"))
    phase_current_fields = (
        ("electrical_angle_deg", "deg"),
        ("phase_a_A", "A"),
        ("phase_b_A", "A"),
        ("phase_c_A", "A"),
    )
    current_sample_count = max(
        (len(_sequence(phase_current.get(field))) for field, _unit in phase_current_fields),
        default=0,
    )
    for index in range(current_sample_count):
        for field, unit in phase_current_fields:
            values = _sequence(phase_current.get(field))
            if index < len(values):
                row("phase_current_waveform", field, values[index], unit, index)

    back_emf = _mapping(result.get("back_emf_waveform"))
    back_emf_fields = (
        ("electrical_angle_deg", "deg"),
        ("phase_a_V", "V"),
        ("phase_b_V", "V"),
        ("phase_c_V", "V"),
        ("line_ab_V", "V"),
        ("line_bc_V", "V"),
        ("line_ca_V", "V"),
    )
    sample_count = max(
        (len(_sequence(back_emf.get(field))) for field, _unit in back_emf_fields),
        default=0,
    )
    for index in range(sample_count):
        for field, unit in back_emf_fields:
            values = _sequence(back_emf.get(field))
            if index < len(values):
                row("back_emf_waveform", field, values[index], unit, index)

    cogging = _mapping(result.get("cogging_torque_waveform"))
    cogging_angles = _sequence(cogging.get("electrical_angle_deg"))
    cogging_values = _sequence(cogging.get("torque_Nm"))
    for index in range(max(len(cogging_angles), len(cogging_values))):
        if index < len(cogging_angles):
            row("cogging_waveform", "electrical_angle_deg", cogging_angles[index], "deg", index)
        if index < len(cogging_values):
            row("cogging_waveform", "torque_Nm", cogging_values[index], "N m", index)

    for index, warning in enumerate(_warnings(result)):
        row("warning", "message", warning, sample_index=index)
    for index, limitation in enumerate(PUBLIC_REPORT_LIMITATIONS):
        row("known_limitation", "message", limitation, sample_index=index)
    if _mapping(resolved_config.get("solve_params")).get("excitation_mode") == "ideal_six_step_120":
        row(
            "known_limitation",
            "message",
            SIX_STEP_REPORT_LIMITATION,
            sample_index=len(PUBLIC_REPORT_LIMITATIONS),
        )
    return output.getvalue().encode("utf-8")


def _report_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            textColor=_NAVY,
            spaceAfter=4 * mm,
            alignment=TA_LEFT,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=_SLATE,
            spaceAfter=6 * mm,
        ),
        "heading": ParagraphStyle(
            "ReportHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=_NAVY,
            spaceBefore=5 * mm,
            spaceAfter=2.5 * mm,
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=_NAVY,
        ),
        "small": ParagraphStyle(
            "ReportSmall",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.2,
            leading=9.5,
            textColor=_SLATE,
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=_SLATE,
        ),
        "metric_value": ParagraphStyle(
            "MetricValue",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=_NAVY,
        ),
        "table_head": ParagraphStyle(
            "TableHead",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=_WHITE,
        ),
    }


def _section(title: str, styles: Mapping[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(escape(title), styles["heading"])


def _key_value_table(
    rows: Sequence[tuple[str, Any]],
    styles: Mapping[str, ParagraphStyle],
    *,
    widths: tuple[float, float] = (50 * mm, 130 * mm),
) -> Table:
    data = [[_safe_paragraph(label, styles["small"]), _safe_paragraph(value, styles["body"])] for label, value in rows]
    table = Table(data, colWidths=list(widths), hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), _LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.4, _BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ]
        )
    )
    return table


def _metric_table(
    summary: Mapping[str, Any],
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    cells: list[list[Any]] = []
    metrics = [field for field in _SUMMARY_ORDER if field in summary]
    for offset in range(0, len(metrics), 4):
        labels: list[Any] = []
        values: list[Any] = []
        for field in metrics[offset : offset + 4]:
            labels.append(_safe_paragraph(_SUMMARY_LABELS[field], styles["metric_label"]))
            values.append(
                _safe_paragraph(
                    _metric_value(summary[field], _SUMMARY_UNITS[field]),
                    styles["metric_value"],
                )
            )
        while len(labels) < 4:
            labels.append("")
            values.append("")
        cells.extend([labels, values])
    table = Table(cells or [["No primary metrics recorded"]], colWidths=[45 * mm] * 4, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ]
        )
    )
    return table


def _numeric_points(x_values: Any, y_values: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for x_value, y_value in zip(_sequence(x_values), _sequence(y_values)):
        try:
            x = float(x_value)
            y = float(y_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            points.append((x, y))
    return points


def _line_plot(
    *,
    title: str,
    x_label: str,
    y_label: str,
    series: Sequence[tuple[str, Sequence[tuple[float, float]], colors.Color]],
) -> Drawing | None:
    valid = [(name, points, color) for name, points, color in series if points]
    if not valid:
        return None
    drawing = Drawing(180 * mm, 66 * mm)
    drawing.add(String(0, 61 * mm, title, fontName="Helvetica-Bold", fontSize=9, fillColor=_NAVY))
    plot = LinePlot()
    plot.x = 16 * mm
    plot.y = 11 * mm
    plot.width = 155 * mm
    plot.height = 43 * mm
    plot.data = [points for _name, points, _color in valid]
    plot.joinedLines = 1
    plot.strokeColor = _BORDER
    plot.xValueAxis.valueMin = min(point[0] for _n, points, _c in valid for point in points)
    plot.xValueAxis.valueMax = max(point[0] for _n, points, _c in valid for point in points)
    y_values = [point[1] for _n, points, _c in valid for point in points]
    y_min, y_max = min(y_values), max(y_values)
    if math.isclose(y_min, y_max):
        margin = max(abs(y_min) * 0.05, 1.0)
        y_min -= margin
        y_max += margin
    plot.yValueAxis.valueMin = y_min
    plot.yValueAxis.valueMax = y_max
    plot.xValueAxis.labels.fontName = "Helvetica"
    plot.xValueAxis.labels.fontSize = 6
    plot.yValueAxis.labels.fontName = "Helvetica"
    plot.yValueAxis.labels.fontSize = 6
    plot.xValueAxis.strokeColor = _SLATE
    plot.yValueAxis.strokeColor = _SLATE
    for index, (_name, _points, color) in enumerate(valid):
        plot.lines[index].strokeColor = color
        plot.lines[index].strokeWidth = 1.4
    drawing.add(plot)
    drawing.add(String(88 * mm, 2 * mm, x_label, fontName="Helvetica", fontSize=6.5, fillColor=_SLATE, textAnchor="middle"))
    drawing.add(String(1 * mm, 33 * mm, y_label, fontName="Helvetica", fontSize=6.5, fillColor=_SLATE))
    legend_x = 18 * mm
    for name, _points, color in valid:
        drawing.add(String(legend_x, 57.5 * mm, name, fontName="Helvetica", fontSize=6.5, fillColor=color))
        legend_x += stringWidth(name, "Helvetica", 6.5) + 8 * mm
    return drawing


class _InvariantCanvas(canvas.Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["invariant"] = 1
        super().__init__(*args, **kwargs)


def _region_group(region: str) -> str:
    if region in {"magnet_pocket_air", "airgap", "air", "exterior_air", "flux_barrier"}:
        return "air"
    if region == "shaft":
        return "shaft"
    if region.startswith("stator"):
        return "stator"
    if region.startswith("rotor"):
        return "rotor"
    if region.startswith("slot") or region == "winding":
        return "winding"
    if region.startswith("magnet"):
        return "magnet"
    return "other"


def _saved_motor_mesh(plot: Mapping[str, Any]) -> tuple[
    list[tuple[float, float]], list[tuple[int, int, int]], list[str],
] | None:
    """Reject incomplete meshes rather than presenting a partial motor."""
    raw_nodes = _sequence(plot.get("nodes_mm"))
    raw_triangles = _sequence(plot.get("triangles"))
    raw_regions = _sequence(plot.get("regions"))
    if not raw_nodes or not raw_triangles or len(raw_triangles) != len(raw_regions):
        return None
    nodes: list[tuple[float, float]] = []
    for raw in raw_nodes:
        point = _sequence(raw)
        if len(point) != 2:
            return None
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        nodes.append((x, y))
    triangles: list[tuple[int, int, int]] = []
    for raw in raw_triangles:
        indices = _sequence(raw)
        if len(indices) != 3 or any(
            not isinstance(index, int) or isinstance(index, bool)
            or index < 0 or index >= len(nodes) for index in indices
        ) or len(set(indices)) != 3:
            return None
        triangles.append((indices[0], indices[1], indices[2]))
    return nodes, triangles, [_region_group(str(region)) for region in raw_regions]


class _MotorMeshFigure(Flowable):
    """A sharp stored-mesh raster with a searchable PDF legend."""

    def __init__(
        self, png: bytes, *, groups: Sequence[str] = (),
        field_range: tuple[float, float] | None = None,
    ) -> None:
        super().__init__()
        self.width = 180 * mm
        self.height = 103 * mm
        self.png = png
        self.groups = groups
        self.field_range = field_range

    def draw(self) -> None:
        pdf = self.canv
        pdf.drawImage(ImageReader(io.BytesIO(self.png)), 17 * mm, 2 * mm,
                      width=100 * mm, height=100 * mm)
        pdf.setFont("Helvetica", 8)
        if self.field_range is not None:
            low, high = self.field_range
            pdf.setFillColor(_NAVY)
            pdf.drawString(132 * mm, 92 * mm, "Flux density |B| (T)")
            for index, color in enumerate(_HEAT_COLORS):
                pdf.setFillColor(colors.HexColor(color))
                pdf.rect(133 * mm, (13 + index * 9) * mm, 6 * mm, 9 * mm,
                         fill=1, stroke=0)
            pdf.setFillColor(_SLATE)
            for fraction in (0.0, 0.5, 1.0):
                pdf.drawString(143 * mm, (13 + fraction * 72) * mm - 2,
                               f"{low + fraction * (high - low):.3f}")
            pdf.setFont("Helvetica", 7)
            pdf.drawString(132 * mm, 6 * mm, "Yellow: stored field lines")
        else:
            pdf.setFillColor(_NAVY)
            pdf.drawString(132 * mm, 92 * mm, "Material regions")
            for index, group in enumerate(self.groups):
                label, color = _REGION_COLORS[group]
                y = (80 - index * 11) * mm
                pdf.setFillColor(colors.HexColor(color))
                pdf.setStrokeColor(_BORDER)
                pdf.rect(133 * mm, y, 5 * mm, 5 * mm, fill=1, stroke=1)
                pdf.setFillColor(_SLATE)
                pdf.drawString(141 * mm, y + 3, label)


def _motor_mesh_figures(
    plot: Mapping[str, Any],
) -> tuple[_MotorMeshFigure | None, _MotorMeshFigure | None]:
    mesh = _saved_motor_mesh(plot)
    if mesh is None:
        return None, None
    nodes, triangles, groups = mesh
    used = {index for triangle in triangles for index in triangle}
    min_x, max_x = min(nodes[i][0] for i in used), max(nodes[i][0] for i in used)
    min_y, max_y = min(nodes[i][1] for i in used), max(nodes[i][1] for i in used)
    span = max(max_x - min_x, max_y - min_y)
    if span <= 0:
        return None, None
    size = 1200
    scale = size * 0.94 / span
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    def point(x: float, y: float) -> tuple[float, float]:
        # Saved coordinates have +Y upward, image pixels have +Y downward.
        return size / 2 + (x - center_x) * scale, size / 2 - (y - center_y) * scale

    pixels = [point(x, y) for x, y in nodes]
    geometry = PILImage.new("RGB", (size, size), "white")
    geometry_draw = ImageDraw.Draw(geometry)
    edges: dict[tuple[int, int], list[str]] = {}
    for triangle, group in zip(triangles, groups):
        geometry_draw.polygon([pixels[i] for i in triangle], fill=_REGION_COLORS[group][1])
        for a, b in ((triangle[0], triangle[1]), (triangle[1], triangle[2]), (triangle[2], triangle[0])):
            edges.setdefault((min(a, b), max(a, b)), []).append(group)
    for (a, b), adjacent in edges.items():
        if len(adjacent) == 1 or len(set(adjacent)) > 1:
            geometry_draw.line([pixels[a], pixels[b]], fill="#475569", width=2)

    def png(image: PILImage.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    geometry_figure = _MotorMeshFigure(
        png(geometry), groups=[group for group in _REGION_COLORS if group in groups],
    )
    raw_values = _sequence(plot.get("element_b_mag_t"))
    if len(raw_values) != len(triangles):
        return geometry_figure, None
    try:
        values = [float(value) for value in raw_values]
    except (TypeError, ValueError, OverflowError):
        return geometry_figure, None
    if any(not math.isfinite(value) or value < 0 for value in values):
        return geometry_figure, None
    low, high = min(values), max(values)
    heatmap = PILImage.new("RGB", (size, size), "white")
    heat_draw = ImageDraw.Draw(heatmap)
    for triangle, value in zip(triangles, values):
        bucket = min(7, int((value - low) / (high - low) * 8)) if high > low else 0
        heat_draw.polygon([pixels[i] for i in triangle], fill=_HEAT_COLORS[bucket])
    for level in _sequence(plot.get("contour_levels")):
        for raw in _sequence(_mapping(level).get("segments_mm")):
            segment = _sequence(raw)
            if len(segment) != 4:
                continue
            try:
                x0, y0, x1, y1 = map(float, segment)
            except (TypeError, ValueError, OverflowError):
                continue
            if all(math.isfinite(value) for value in (x0, y0, x1, y1)):
                heat_draw.line([point(x0, y0), point(x1, y1)], fill="#f1c232", width=2)
    return geometry_figure, _MotorMeshFigure(png(heatmap), field_range=(low, high))


def _motor_figure_story(
    result: Mapping[str, Any], request: Mapping[str, Any],
    styles: Mapping[str, ParagraphStyle],
) -> list[Any]:
    geometry, heatmap = _motor_mesh_figures(_mapping(result.get("field_line_plot")))
    frames = _sequence(result.get("field_line_frames"))
    angle = _mapping(frames[0]).get("angle_deg") if frames else None
    try:
        pole_count = _mapping(_mapping(request.get("resolved_config")).get("rotor")).get("pole_count")
        if angle is None or pole_count is None:
            raise ValueError("Stored rotor position is incomplete")
        angle = float(angle)
        poles = float(pole_count)
        position = (
            f"{angle:g} deg electrical / {angle * 2 / poles:g} deg mechanical"
            if math.isfinite(angle) and math.isfinite(poles) and poles > 0
            else "angle not recorded"
        )
    except (TypeError, ValueError, OverflowError):
        position = "angle not recorded"
    story: list[Any] = [PageBreak(), _section("2D motor cross-section", styles)]
    if geometry is None:
        story.append(Paragraph("Motor figure unavailable: no complete saved motor mesh and material regions were recorded.", styles["body"]))
    else:
        story.extend([geometry, Paragraph(
            f"Material-colored cross-section of the saved mesh. First loaded position: {escape(position)}. "
            "Mesh edges are hidden; material boundaries are outlined.",
            styles["small"],
        )])
    story.append(_section("Solved flux-density heatmap", styles))
    if heatmap is None:
        story.append(Paragraph("Heatmap unavailable: complete finite flux-density values for the saved mesh were not recorded.", styles["body"]))
    else:
        story.extend([heatmap, Paragraph(
            f"Stored loaded field at {escape(position)}. Colors show per-element flux-density magnitude in tesla "
            "at this position, not the maximum over the sweep. Field lines are from the same stored solution.",
            styles["small"],
        )])
    return story


def build_public_run_pdf(
    *,
    project: Mapping[str, Any],
    request: Mapping[str, Any],
    result: Mapping[str, Any],
    material: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> bytes:
    """Return a deterministic PDF for one immutable stored solve run."""

    styles = _report_styles()
    buffer = io.BytesIO()
    run_id = _plain(manifest.get("run_id"))
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=f"coilEM solve report - {run_id}",
        author="coilEM",
        subject="Immutable local electromagnetic solve record",
    )

    def page_chrome(pdf: canvas.Canvas, doc: SimpleDocTemplate) -> None:
        pdf.saveState()
        pdf.setStrokeColor(_BORDER)
        pdf.setLineWidth(0.4)
        pdf.line(15 * mm, A4[1] - 12 * mm, A4[0] - 15 * mm, A4[1] - 12 * mm)
        pdf.setFont("Helvetica-Bold", 7)
        pdf.setFillColor(_NAVY)
        pdf.drawString(15 * mm, A4[1] - 9 * mm, "coilEM")
        pdf.setFont("Helvetica", 6.5)
        pdf.setFillColor(_SLATE)
        pdf.drawRightString(A4[0] - 15 * mm, A4[1] - 9 * mm, f"Immutable run {run_id}")
        pdf.line(15 * mm, 11 * mm, A4[0] - 15 * mm, 11 * mm)
        pdf.drawString(15 * mm, 7 * mm, _plain(manifest.get("completed_at")) or "Completion time not recorded")
        pdf.drawRightString(A4[0] - 15 * mm, 7 * mm, f"Page {doc.page}")
        pdf.restoreState()

    story: list[Any] = [
        Paragraph("Electromagnetic solve report", styles["title"]),
        Paragraph(
            "A replayable, immutable record generated from the stored project, resolved request, material contract, result, and solve provenance.",
            styles["subtitle"],
        ),
        _key_value_table(
            [
                ("Project", manifest.get("project_name")),
                ("Run ID", manifest.get("run_id")),
                ("Completed (UTC)", manifest.get("completed_at")),
                ("Topology", project.get("topology")),
            ],
            styles,
        ),
    ]

    summary = _mapping(result.get("summary"))
    story.extend([_section("Primary metrics", styles), _metric_table(summary, styles)])
    solve_params = _mapping(_mapping(request.get("resolved_config")).get("solve_params"))
    solve_metadata = _mapping(result.get("solve_metadata"))
    provenance = _mapping(manifest.get("provenance"))
    six_step = solve_params.get("excitation_mode") == "ideal_six_step_120"
    story.extend(
        [
            _section("Operating point and mesh", styles),
            _key_value_table(
                [
                    (
                        "Conducting phase current" if six_step else "Phase current",
                        (f"{_plain(solve_params.get('current_amplitude_A'))} A {_plain(solve_params.get('current_amplitude_convention'))}").strip(),
                    ),
                    (
                        "Commutation advance" if six_step else "Current angle",
                        f"{_plain(solve_params.get('commutation_advance_deg') if six_step else solve_params.get('current_angle_deg'))} deg",
                    ),
                    ("Excitation", "Ideal six-step (120 deg)" if six_step else "Sinusoidal"),
                    ("Phase connection", solve_params.get("phase_connection") if six_step else "Not recorded"),
                    ("Rated speed", f"{_plain(solve_params.get('rated_speed_rpm'))} rpm"),
                    ("Solve quality", solve_params.get("solve_quality")),
                    ("Mesh density", solve_metadata.get("mesh_density") or solve_params.get("mesh_density")),
                    ("Mesh elements", solve_metadata.get("mesh_element_count")),
                    ("Rotor positions", solve_metadata.get("rotor_positions")),
                    ("Torque method used", solve_metadata.get("torque_method") or "Not recorded"),
                    ("Torque method requested", solve_params.get("torque_method")),
                ],
                styles,
            ),
            _section("Solver and build provenance", styles),
            _key_value_table(
                [
                    ("Solver", solve_metadata.get("solver_name") or provenance.get("solver_name")),
                    ("Application version", provenance.get("application_version")),
                    ("Application commit", provenance.get("application_commit")),
                    ("Platform", _plain(provenance.get("platform"))),
                    ("Result SHA-256", _mapping(manifest.get("bindings")).get("result_sha256")),
                    ("Resolved request SHA-256", _mapping(manifest.get("bindings")).get("resolved_request_sha256")),
                ],
                styles,
            ),
        ]
    )

    story.extend(_motor_figure_story(result, request, styles))

    material_records = _sequence(material.get("records"))
    story.extend([PageBreak(), _section("Electrical steel material contract", styles)])
    if material_records:
        for index, record_value in enumerate(material_records):
            record = _mapping(record_value)
            story.extend(
                [
                    Paragraph(f"Material record {index + 1}", styles["body"]),
                    _key_value_table(
                        [
                            ("Material", record.get("material_name") or record.get("material_key")),
                            ("Material ID", record.get("material_key")),
                            (
                                "Roles",
                                ", ".join(map(str, _sequence(record.get("roles")))),
                            ),
                            ("B-H curve", record.get("curve_path")),
                            ("Curve SHA-256", record.get("curve_sha256")),
                            ("Curve points", record.get("point_count")),
                            ("B range", f"{_plain(record.get('b_range_T'))} T"),
                            (
                                "Source",
                                _mapping(record.get("source")).get("description")
                                or _mapping(record.get("source")).get("model_url"),
                            ),
                            (
                                "License",
                                _mapping(record.get("source")).get("license"),
                            ),
                        ],
                        styles,
                    ),
                ]
            )
    else:
        story.append(Paragraph("No material contract was recorded.", styles["body"]))

    torque = _mapping(result.get("torque_waveform"))
    torque_plot = _line_plot(
        title="Torque waveform",
        x_label="Electrical angle (deg)",
        y_label="Torque (N m)",
        series=(("Torque", _numeric_points(torque.get("electrical_angle_deg"), torque.get("torque_Nm")), _BLUE),),
    )
    back_emf = _mapping(result.get("back_emf_waveform"))
    back_emf_plot = _line_plot(
        title="Three-phase back EMF",
        x_label="Electrical angle (deg)",
        y_label="Voltage (V)",
        series=tuple(
            (label, _numeric_points(back_emf.get("electrical_angle_deg"), back_emf.get(field)), color)
            for label, field, color in (
                ("Phase A", "phase_a_V", _RED),
                ("Phase B", "phase_b_V", _GREEN),
                ("Phase C", "phase_c_V", _BLUE),
            )
        ),
    )
    if torque_plot is not None or back_emf_plot is not None:
        story.append(_section("Stored result plots", styles))
        if torque_plot is not None:
            story.extend([torque_plot, Spacer(1, 3 * mm)])
        if back_emf_plot is not None:
            story.append(back_emf_plot)

    settings_rows = [(field, _plain(value)) for field, value in _flatten(_mapping(request.get("resolved_config")))]
    if settings_rows:
        for chunk_index, offset in enumerate(range(0, len(settings_rows), 24)):
            story.extend(
                [
                    PageBreak(),
                    _section(
                        "Exact resolved settings" if chunk_index == 0 else "Exact resolved settings (continued)",
                        styles,
                    ),
                ]
            )
            settings_data = [
                [
                    Paragraph("Setting", styles["table_head"]),
                    Paragraph("Stored value", styles["table_head"]),
                ],
                *[
                    [
                        _safe_paragraph(field, styles["small"]),
                        _safe_paragraph(value, styles["body"]),
                    ]
                    for field, value in settings_rows[offset : offset + 24]
                ],
            ]
            settings_table = Table(
                settings_data,
                colWidths=[82 * mm, 98 * mm],
                hAlign="LEFT",
                repeatRows=1,
            )
            settings_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                        ("BOX", (0, 0), (-1, -1), 0.4, _BORDER),
                        ("INNERGRID", (0, 0), (-1, -1), 0.25, _BORDER),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                        ("TOPPADDING", (0, 0), (-1, -1), 1.4 * mm),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4 * mm),
                    ]
                )
            )
            story.append(settings_table)

    story.append(_section("Warnings", styles))
    warnings = _warnings(result)
    if warnings:
        for warning in warnings:
            story.append(Paragraph(f"- {escape(warning)}", styles["body"]))
    else:
        story.append(Paragraph("No solver warnings were recorded.", styles["body"]))
    story.append(_section("Known limitations", styles))
    for limitation in PUBLIC_REPORT_LIMITATIONS:
        story.append(Paragraph(f"- {escape(limitation)}", styles["body"]))
    if six_step:
        story.append(Paragraph(f"- {escape(SIX_STEP_REPORT_LIMITATION)}", styles["body"]))

    document.build(
        story,
        onFirstPage=page_chrome,
        onLaterPages=page_chrome,
        canvasmaker=_InvariantCanvas,
    )
    return buffer.getvalue()


def write_replayable_run_package(
    run_directory: Path,
    target: Path,
    *,
    completed_at: str,
) -> None:
    """Write a stable ZIP containing the complete replay/evidence record."""

    try:
        parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        zip_time = (
            max(1980, parsed.year),
            parsed.month,
            parsed.day,
            parsed.hour,
            parsed.minute,
            parsed.second,
        )
    except (TypeError, ValueError):
        zip_time = (1980, 1, 1, 0, 0, 0)

    require_contained_path(run_directory, run_directory)
    sources = sorted(run_directory.rglob("*"), key=lambda path: path.relative_to(run_directory).as_posix())
    # Validate directories too: rglob deliberately does not descend through
    # directory symlinks, so filtering to regular files first would miss them.
    for source in sources:
        require_contained_path(run_directory, source)
    if target.is_symlink():
        raise ValueError("replay package target must not be a symbolic link")
    if target.absolute().is_relative_to(run_directory.absolute()):
        require_contained_path(run_directory, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in sources:
            if not source.is_file() or source.resolve() == target.resolve():
                continue
            relative = source.relative_to(run_directory).as_posix()
            info = zipfile.ZipInfo(relative, zip_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0x800
            with (
                source.open("rb") as input_file,
                archive.open(
                    info,
                    "w",
                    force_zip64=True,
                ) as package_file,
            ):
                shutil.copyfileobj(input_file, package_file, length=1024 * 1024)
