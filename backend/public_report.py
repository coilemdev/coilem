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
from reportlab.graphics.shapes import Drawing, Rect, String
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
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.export_safety import literal_csv_cell
from backend.local_file_safety import require_contained_path
from backend.magnet_temperature import is_derated_run
from backend.models.performance import (
    DQ_FLUX_LINKAGE_STATUS_REASON,
    MAGNET_TEMPERATURE_STATUS_REASON,
    PHASE_RESISTANCE_STATUS_REASON,
)

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
# Records in the summary that get their own CSV section and PDF table (#136, #138).
_SUMMARY_RECORD_SECTIONS = {
    "dq_flux_linkage": "dq",
    "winding_resistance": "winding",
    "loss_breakdown": "losses",
    "iron_loss": "iron_loss",
}
_RECORD_UNIT_SUFFIXES = (
    ("_per_K", "1/K"), ("_mm2", "mm2"), ("_mm", "mm"), ("_ohm", "Ohm"), ("_Nm", "N m"),
    ("_rpm", "rpm"), ("_pct", "%"), ("_kg", "kg"), ("_Hz", "Hz"), ("_Wb", "Wb"), ("_W", "W"),
    ("_A", "A"), ("_C", "C"), ("_T", "T"), ("_H", "H"), ("_deg", "deg"),
)
# Copper losses in copper shades, iron losses in steel shades, mechanical in green: palette-checked on white.
# Each bar segment is also named in the legend.
_LOSS_SEGMENT_COLORS = ("#943b12", "#c07525", "#14598b", "#3b8cba", "#2f8f4e")
# Iron-loss map on paper: pale steel (little loss) to dark slate (most), one hue, palette-checked on white.
_STEEL_RAMP = ("#9eb8cc", "#7695ad", "#56728a", "#385169", "#203244")
_NOT_MODELLED_FILL = "#eee7d9"
_COIL_SIDE_FILL = "#eceef1"


def _record_unit(name: str) -> str:
    for suffix, unit in _RECORD_UNIT_SUFFIXES:
        if name.endswith(suffix):
            return unit
    return ""


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
    # Stored per peak phase ampere (backend/machine_constants.py); the app's Results show it per rms ampere (#153).
    "Kt_Nm_per_A": "N m/A peak",
    "Ke_Vs_per_rad_mech": "V s/rad (phase peak per mech rad/s)",
    "lambda_pm_Wb": "Wb peak",
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
_KT_RMS_FIELD, _KT_RMS_UNIT, _KT_LABEL = "Kt_Nm_per_A_rms", "N m/A rms", "Torque constant"


def _kt_rms(summary: Mapping[str, Any]) -> float | None:
    """Kt per rms phase ampere, as Results shows it: I_rms = I_peak / sqrt(2), so Kt_rms = sqrt(2) Kt_peak."""

    kt = summary.get("Kt_Nm_per_A")
    if isinstance(kt, bool) or not isinstance(kt, (int, float)) or not math.isfinite(kt):
        return None
    return kt * math.sqrt(2)


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


def _qualification_row(manifest: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """The run's qualification status (backend/qualification.py) for the
    report header; runs stored before it was recorded have none."""

    qualification = _mapping(_mapping(manifest.get("provenance")).get("qualification"))
    status = _plain(qualification.get("status"))
    if not status:
        return []
    return [("Qualification", f"{status.capitalize()}: {_plain(qualification.get('reason'))} ({_plain(qualification.get('basis'))})")]


def _qualification_limitations(manifest: Mapping[str, Any]) -> list[str]:
    qualification = _mapping(_mapping(manifest.get("provenance")).get("qualification"))
    limitations = []
    if qualification.get("status") == "experimental":
        limitations.append(f"Experimental combination: {_plain(qualification.get('reason'))}")
    limitations.extend(_plain(caveat) for caveat in _sequence(qualification.get("caveats")))
    return limitations


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, (list, tuple)) else ()


def _status_text(status: str, reason: str) -> str:
    return f"{status.capitalize()}: {reason}" if reason else status.capitalize()


def _output_statuses(result: Mapping[str, Any]) -> list[tuple[str, str, str, str]]:
    """(key, output, status, reason) of each 0.5.0 output the run recorded (public issue 143).

    d/q and winding records stored before they carried a status, and derated
    magnets recorded without one, were experimental for the reasons the
    current records give.
    """

    summary = _mapping(result.get("summary"))
    metadata = _mapping(result.get("solve_metadata"))
    statuses: list[tuple[str, str, str, str]] = []

    def recorded(key: str, output: str, record: Mapping[str, Any], fallback: str, prefix: str = "") -> None:
        status = _plain(record.get(f"{prefix}status"))
        reason = _plain(record.get(f"{prefix}status_reason"))
        statuses.append((key, output, status or "experimental", reason if status else reason or fallback))

    if summary.get("dq_flux_linkage"):
        recorded("dq_flux_linkage", "d/q flux linkage and inductances", _mapping(summary["dq_flux_linkage"]), DQ_FLUX_LINKAGE_STATUS_REASON)
    if summary.get("winding_resistance"):
        recorded("phase_resistance", "Phase resistance and copper loss", _mapping(summary["winding_resistance"]), PHASE_RESISTANCE_STATUS_REASON)
    iron = _mapping(summary.get("iron_loss"))
    if iron.get("status") in ("qualified", "experimental"):
        statuses.append(("iron_loss", "Iron loss and its density map", iron["status"], _plain(iron.get("status_reason"))))
    losses = _mapping(summary.get("loss_breakdown"))
    if losses.get("efficiency_status") in ("qualified", "experimental"):
        statuses.append(("efficiency", "Efficiency", losses["efficiency_status"], _plain(losses.get("efficiency_status_reason"))))
    if is_derated_run(metadata):
        recorded("magnet_temperature", "Magnet temperature derating", metadata, MAGNET_TEMPERATURE_STATUS_REASON, "magnet_temperature_")
    return statuses


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
        if field in summary and field not in _SUMMARY_RECORD_SECTIONS:
            row("summary", field, summary[field], _SUMMARY_UNITS.get(field, ""))
            if field == "Kt_Nm_per_A" and _kt_rms(summary) is not None:
                row("summary", _KT_RMS_FIELD, _kt_rms(summary), _KT_RMS_UNIT)
    for field, section in _SUMMARY_RECORD_SECTIONS.items():
        for name, value in _flatten(_mapping(summary.get(field))):
            row(section, name, value, _record_unit(name))
    for key, _output, status, reason in _output_statuses(result):
        row("status", key, status)
        row("status", f"{key}_reason", reason)
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
    limitation_index = len(PUBLIC_REPORT_LIMITATIONS)
    if _mapping(resolved_config.get("solve_params")).get("excitation_mode") == "ideal_six_step_120":
        row(
            "known_limitation",
            "message",
            SIX_STEP_REPORT_LIMITATION,
            sample_index=limitation_index,
        )
        limitation_index += 1
    for index, limitation in enumerate(_qualification_limitations(manifest), start=limitation_index):
        row("known_limitation", "message", limitation, sample_index=index)
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
        "group": ParagraphStyle(
            "SettingsGroup",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=_NAVY,
            spaceBefore=2.5 * mm,
            spaceAfter=1.2 * mm,
        ),
    }


def _section(title: str, styles: Mapping[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(escape(title), styles["heading"])


def _build_rows(build: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """Installed-package identity; runs from a source checkout have none."""

    if build.get("installation") != "package":
        return []
    return [
        ("Magneto2D build", f"{build.get('magneto2d_version')} for {build.get('magneto2d_target')}"),
        ("Magneto2D binary SHA-256", build.get("magneto2d_sha256")),
        ("UI bundle SHA-256", build.get("ui_bundle_sha256")),
    ]


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


# The PDF lists the settings that define the run's design (#52). The CSV
# ``setting`` rows and request.json keep every stored value.
_SETTING_UNIT_SUFFIXES = (
    ("_mm", "mm"),
    ("_deg", "deg"),
    ("_rpm", "rpm"),
    ("_A", "A"),
    ("_V", "V"),
    ("_C", "degC"),
)
_SETTING_LABELS = {
    "OD_mm": "Outer diameter",
    "ID_mm": "Inner diameter",
    "magnet_embrace": "Magnet coverage",
    "ipm_topology": "IPM rotor type",
    "current_amplitude_A": "Phase current",
    "motor_input_dc_bus_V": "DC bus voltage",
    "linear_steel_mu_rel": "Linear steel relative permeability",
    "mesh_build": "Mesh build",
    "back_emf": "Back EMF",
    "thd_analysis": "THD analysis",
}
_STATOR_SETTINGS = (
    "OD_mm",
    "ID_mm",
    "slot_count",
    "stack_length_mm",
    "slot_opening_mm",
    "tooth_width_mm",
    "yoke_thickness_mm",
    "tooth_shoe_enabled",
    "tooth_shoe_height_mm",
    "tooth_shoe_overhang_mm",
)
_TOOTH_SHOE_SETTINGS = frozenset({"tooth_shoe_height_mm", "tooth_shoe_overhang_mm"})
_ROTOR_SETTINGS = ("pole_count", "OD_mm", "ID_mm", "magnet_thickness_mm", "magnet_width_mm", "magnet_embrace")
# Pocket settings each IPM rotor type builds its geometry from (backend/geometry_drawer.py).
_IPM_ROTOR_SETTINGS = {
    "flat_buried": (
        "flat_buried_magnet_shape",
        "bridge_thickness_mm",
        "side_bridge_thickness_mm",
        "pocket_clearance_mm",
        "magnet_angle_deg",
    ),
    "v_shape": (
        "v_angle_deg",
        "v_depth_mm",
        "inner_web_thickness_mm",
        "outer_bridge_thickness_mm",
        "pocket_clearance_mm",
        "magnet_angle_deg",
    ),
    "pyleecan_holem50": (
        *(f"holem50_w{index}_mm" for index in range(5)),
        *(f"holem50_h{index}_mm" for index in range(5)),
        "magnet_angle_deg",
    ),
}
_ROTOR_TYPE_SETTINGS = frozenset(
    {"ipm_topology", *(name for names in _IPM_ROTOR_SETTINGS.values() for name in names)}
)
_WINDING_SETTINGS = ("type", "layers", "turns_per_coil", "parallel_paths", "coil_span")
_MATERIAL_SETTINGS = ("stator_steel", "rotor_steel", "magnet_grade", "conductor")
_OPERATING_POINT_SETTINGS = (
    "excitation_mode",
    "current_amplitude_A",
    "current_angle_deg",
    "commutation_advance_deg",
    "phase_connection",
    "rated_speed_rpm",
    "magnet_temperature_C",
    "motor_input_dc_bus_V",
)
_SINUSOIDAL_ONLY_SETTINGS = frozenset({"current_angle_deg"})
_SIX_STEP_ONLY_SETTINGS = frozenset({"commutation_advance_deg", "phase_connection"})
_SOLVE_PLAN_SETTINGS = (
    "solve_quality",
    "rotor_step_deg",
    "rotor_sweep_range_deg",
    "mesh_density",
    "mesher",
    "mesh_source",
    "corner_refinement",
    "mesh_build",
    "slot_sidewall_refinement",
    "rotor_rotation_model",
    "torque_method",
    "nonlinear_solver",
    "max_nonlinear_iterations",
    "linear_solver_preconditioner",
    "linear_steel_mu_rel",
    "field_composition_source",
)
# The plans that read these stored values (SolveParams.effective_step_deg and
# effective_native_loaded_sweep_range_deg). Every preset sets its own step;
# Preview caps the stored sweep range at 60 deg, so it uses that range too.
_PLANS_USING_SETTING = {
    "rotor_step_deg": frozenset({"custom"}),
    "rotor_sweep_range_deg": frozenset({"custom", "quick"}),
}
# Execution settings that do not change the solved numbers.
_RUNTIME_ONLY_SETTINGS = frozenset({"magneto2d_workers", "stream_noload_field_lines"})


def _setting_is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return not math.isfinite(value)
    return isinstance(value, (str, list, tuple, Mapping)) and len(value) == 0


def _setting_entry(name: str, value: Any) -> tuple[str, str]:
    label = _SETTING_LABELS.get(name)
    unit = ""
    base = name
    for suffix, suffix_unit in _SETTING_UNIT_SUFFIXES:
        if name.endswith(suffix):
            base, unit = name[: -len(suffix)], suffix_unit
            break
    if label is None:
        if base.startswith("holem50_"):
            label = f"HoleM50 {base.removeprefix('holem50_').upper()}"
        else:
            words = base.replace("_", " ")
            label = words[:1].upper() + words[1:]
    return label, f"{_plain(value)} {unit}".strip()


def _setting_group(
    section: Mapping[str, Any],
    order: Sequence[str],
    *,
    omit: Iterable[str] = (),
    others: bool = True,
) -> list[tuple[str, str]]:
    """Entries for the settings in ``order``, then, with ``others``, the rest.

    Settings this report does not know yet are kept, so a new field is never
    hidden. Nested mappings stay in the CSV and request.json.
    """

    omitted = set(omit)
    names = [name for name in order if name in section]
    if others:
        names += sorted(name for name in section if name not in order)
    entries = []
    for name in names:
        value = section[name]
        if name in omitted or _setting_is_empty(value) or isinstance(value, Mapping):
            continue
        if name == "current_amplitude_A":
            label, text = _setting_entry(name, value)
            convention = section.get("current_amplitude_convention")
            entries.append((label, f"{text} {_plain(convention)}".strip()))
            continue
        entries.append(_setting_entry(name, value))
    return entries


def _design_setting_groups(config: Mapping[str, Any]) -> list[tuple[str, list[tuple[str, str]]]]:
    """The resolved settings that apply to this run's topology, by section.

    Settings of other rotor types or the other excitation, settings the solve
    plan does not use, empty values and runtime-only switches are left out.
    """

    stator = _mapping(config.get("stator"))
    rotor = _mapping(config.get("rotor"))
    solve_params = _mapping(config.get("solve_params"))

    stator_omit = set() if stator.get("tooth_shoe_enabled") else set(_TOOTH_SHOE_SETTINGS)
    rotor_order: list[str] = list(_ROTOR_SETTINGS)
    rotor_type = rotor.get("ipm_topology")
    if config.get("topology") == "IPM":
        rotor_order.append("ipm_topology")
        rotor_order.extend(_IPM_ROTOR_SETTINGS.get(str(rotor_type), sorted(_ROTOR_TYPE_SETTINGS - {"ipm_topology"})))
    rotor_omit = _ROTOR_TYPE_SETTINGS - set(rotor_order)
    six_step = solve_params.get("excitation_mode") == "ideal_six_step_120"
    excitation_omit = _SINUSOIDAL_ONLY_SETTINGS if six_step else _SIX_STEP_ONLY_SETTINGS
    plan = solve_params.get("solve_quality")
    plan_omit = {name for name, plans in _PLANS_USING_SETTING.items() if plan not in plans}
    materials = _mapping(config.get("materials"))
    custom_steels = _mapping(materials.get("custom_steels"))

    groups = [
        ("Stator", _setting_group(stator, _STATOR_SETTINGS, omit=stator_omit)),
        ("Rotor", _setting_group(rotor, rotor_order, omit=rotor_omit)),
        ("Winding", _setting_group(_mapping(config.get("winding")), _WINDING_SETTINGS)),
        (
            "Materials",
            _setting_group(materials, _MATERIAL_SETTINGS)
            + ([("Custom steels", ", ".join(sorted(map(str, custom_steels))))] if custom_steels else []),
        ),
        (
            "Operating point",
            _setting_group(solve_params, _OPERATING_POINT_SETTINGS, omit=excitation_omit, others=False),
        ),
        (
            "Solve plan",
            _setting_group(
                solve_params,
                _SOLVE_PLAN_SETTINGS,
                omit={*_OPERATING_POINT_SETTINGS, *_RUNTIME_ONLY_SETTINGS, *plan_omit, "current_amplitude_convention"},
            ),
        ),
        ("Analyses", _setting_group(_mapping(config.get("solve_options")), ())),
    ]
    if config.get("geometry_reference") == "pyleecan_prius_2004":
        groups.insert(0, ("Published software reference", [
            ("Case ID", _plain(config.get("reference_case"))),
            ("Geometry reference", "pyleecan_prius_2004"),
            ("Current angle convention", "Pyleecan d-axis Phi0"),
            ("Magnet temperature", f"{_plain(solve_params.get('magnet_temperature_C'))} C"),
        ]))
    return [(title, entries) for title, entries in groups if entries]


def _settings_grid(
    entries: Sequence[tuple[str, Any]],
    styles: Mapping[str, ParagraphStyle],
    *,
    columns: int = 3,
    cell_widths: tuple[float, float] = (27 * mm, 33 * mm),
) -> Table:
    data = []
    for offset in range(0, len(entries), columns):
        row: list[Any] = []
        for label, value in entries[offset : offset + columns]:
            row.extend([_safe_paragraph(label, styles["small"]), _safe_paragraph(value, styles["body"])])
        row.extend([""] * (2 * columns - len(row)))
        data.append(row)
    table = Table(data, colWidths=list(cell_widths) * columns, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                *(("BACKGROUND", (column, 0), (column, -1), _LIGHT) for column in range(0, 2 * columns, 2)),
                ("BOX", (0, 0), (-1, -1), 0.4, _BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
            ]
        )
    )
    return table


def _metric_table(
    summary: Mapping[str, Any],
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    # One tile per metric, its label over its value, four to a row.
    cells: list[list[Any]] = []
    metrics = [field for field in _SUMMARY_ORDER if field in summary]
    for offset in range(0, len(metrics), 4):
        tiles: list[Any] = []
        for field in metrics[offset : offset + 4]:
            value = _metric_value(summary[field], _SUMMARY_UNITS[field])
            if field == "Kt_Nm_per_A" and _kt_rms(summary) is not None:
                # Per rms ampere first, as Results shows it, over the stored per-peak value (#153).
                tiles.append([
                    _safe_paragraph(_KT_LABEL, styles["metric_label"]),
                    _safe_paragraph(_metric_value(_kt_rms(summary), _KT_RMS_UNIT), styles["metric_value"]),
                    _safe_paragraph(value, styles["metric_label"]),
                ])
            else:
                tiles.append([
                    _safe_paragraph(_SUMMARY_LABELS[field], styles["metric_label"]),
                    _safe_paragraph(value, styles["metric_value"]),
                ])
        while len(tiles) < 4:
            tiles.append("")
        cells.append(tiles)
    table = Table(cells or [["No primary metrics recorded"]], colWidths=[45 * mm] * 4, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
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


# Same steps as the app's charts (frontend/src/public/chartAxis.ts).
_ELECTRICAL_ANGLE_TICK_STEPS_DEG = (1, 2, 2.5, 3.75, 5, 7.5, 10, 15, 22.5, 30, 45, 60, 90, 180)


def _electrical_angle_ticks(min_deg: float, max_deg: float, max_intervals: int = 8) -> list[float]:
    """Multiples of the smallest step leaving at most ``max_intervals`` intervals."""

    span = max_deg - min_deg
    if not math.isfinite(span) or span <= 0:
        return [min_deg] if math.isfinite(min_deg) else []
    step = next(
        (candidate for candidate in _ELECTRICAL_ANGLE_TICK_STEPS_DEG if span / candidate <= max_intervals + 1e-9),
        span / max_intervals,
    )
    ticks = []
    index = math.ceil(min_deg / step - 1e-9)
    while index * step <= max_deg + 1e-9:
        ticks.append(round(index * step, 6))
        index += 1
    return ticks


def _angle_axis_end(angles: Sequence[float]) -> float:
    """360 for a full cycle sampled from 0, as the app's charts show it; else the last angle."""

    ordered = sorted(set(angles))
    if len(ordered) < 2:
        return ordered[-1] if ordered else 0.0
    step = ordered[-1] - ordered[-2]
    tolerance = max(abs(step) * 0.05, 0.01)
    if abs(ordered[0]) <= tolerance and abs(ordered[-1] + step - 360) <= tolerance:
        return 360.0
    return ordered[-1]


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
    angles = [point[0] for _n, points, _c in valid for point in points]
    plot.xValueAxis.valueMin = min(angles)
    plot.xValueAxis.valueMax = max(max(angles), _angle_axis_end(angles))
    plot.xValueAxis.valueSteps = _electrical_angle_ticks(plot.xValueAxis.valueMin, plot.xValueAxis.valueMax)
    plot.xValueAxis.labelTextFormat = lambda value: f"{value:g}"
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
        legend_title: str = "Flux density |B| (T)",
        legend_note: str | None = "Yellow: stored field lines",
        value_format: str = "{:.3f}",
        legend_colors: Sequence[str] = _HEAT_COLORS,
    ) -> None:
        super().__init__()
        self.width = 180 * mm
        self.height = 103 * mm
        self.png = png
        self.groups = groups
        self.field_range = field_range
        self.legend_title = legend_title
        self.legend_note = legend_note
        self.value_format = value_format
        self.legend_colors = tuple(legend_colors)

    def draw(self) -> None:
        pdf = self.canv
        pdf.drawImage(ImageReader(io.BytesIO(self.png)), 17 * mm, 2 * mm,
                      width=100 * mm, height=100 * mm)
        pdf.setFont("Helvetica", 8)
        if self.field_range is not None:
            low, high = self.field_range
            pdf.setFillColor(_NAVY)
            pdf.drawString(132 * mm, 92 * mm, self.legend_title)
            step = 72 / len(self.legend_colors)
            for index, color in enumerate(self.legend_colors):
                pdf.setFillColor(colors.HexColor(color))
                pdf.rect(133 * mm, (13 + index * step) * mm, 6 * mm, step * mm,
                         fill=1, stroke=0)
            pdf.setFillColor(_SLATE)
            for fraction in (0.0, 0.5, 1.0):
                pdf.drawString(143 * mm, (13 + fraction * 72) * mm - 2,
                               self.value_format.format(low + fraction * (high - low)))
            if self.legend_note:
                pdf.setFont("Helvetica", 7)
                for line_index, line in enumerate(self.legend_note.split("\n")):
                    pdf.drawString(132 * mm, (6 - 3.2 * line_index) * mm, line)
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


def _number(value: Any, digits: int = 3) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "Not recorded"
    # Whole numbers too long for the significant digits print in full, never as 1e+03.
    return f"{value:.0f}" if abs(value) >= 10**digits else f"{value:.{digits}g}"


def _percent(fraction: Any, digits: int = 3) -> str:
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not math.isfinite(fraction):
        return "Not recorded"
    return f"{100 * fraction:.{digits}g}%"


def _resistance_text(ohm: Any) -> str:
    if isinstance(ohm, bool) or not isinstance(ohm, (int, float)) or not math.isfinite(ohm):
        return "Not recorded"
    return f"{ohm * 1000:.3g} mOhm" if abs(ohm) < 1 else f"{ohm:.3g} Ohm"


def _status_paragraphs(result: Mapping[str, Any], keys: Sequence[str], styles: Mapping[str, ParagraphStyle]) -> list[Paragraph]:
    """Each named output's status and reason, as a line under its section."""

    return [
        Paragraph(f"<b>{escape(output)}: {escape(status)}.</b> {escape(reason)}", styles["small"])
        for key, output, status, reason in _output_statuses(result)
        if key in keys
    ]


# Below this phase current (A peak) a run is open-circuit, as backend/dq_flux_linkage.py treats it.
_OPEN_CIRCUIT_CURRENT_A = 1e-6


def _dq_story(result: Mapping[str, Any], styles: Mapping[str, ParagraphStyle]) -> list[Any]:
    summary = _mapping(result.get("summary"))
    dq = _mapping(summary.get("dq_flux_linkage"))
    if not dq:
        return []

    def milli(value: Any, unit: str) -> str:
        return f"{_number(value * 1000)} {unit}" if isinstance(value, (int, float)) and math.isfinite(value) else "Not recorded"

    i_d, i_q = dq.get("i_d_A"), dq.get("i_q_A")
    if isinstance(i_d, (int, float)) and isinstance(i_q, (int, float)) and math.hypot(i_d, i_q) <= _OPEN_CIRCUIT_CURRENT_A:
        # A back-EMF (no-load) run: no current, so no current angle, inductance or torque check.
        return [
            _section("d/q operating point", styles),
            _settings_grid(
                [
                    ("Magnet flux linkage", milli(dq.get("lambda_pm_Wb"), "mWb")),
                    ("Positions averaged", _number(dq.get("positions"))),
                    ("d-axis flux linkage", milli(dq.get("lambda_d_Wb"), "mWb")),
                    ("q-axis flux linkage", milli(dq.get("lambda_q_Wb"), "mWb")),
                ],
                styles,
                columns=2,
                cell_widths=(40 * mm, 50 * mm),
            ),
            Paragraph(
                "Open-circuit run: no current flows, so there is no current angle, inductance or torque check. lambda_d is the "
                "magnet flux linkage lambda_pm and lambda_q is about zero.",
                styles["small"],
            ),
            *_status_paragraphs(result, ("dq_flux_linkage",), styles),
        ]
    agreement = dq.get("torque_agreement_pct")
    l_d, l_q, lambda_pm = dq.get("apparent_L_d_H"), dq.get("apparent_L_q_H"), dq.get("lambda_pm_Wb")
    numbers = all(isinstance(value, (int, float)) and math.isfinite(value) for value in (l_d, l_q, lambda_pm))
    saliency = f"{_number(l_q / l_d)}" if numbers and l_d > 0 else "Needs d-axis current"
    characteristic = (
        f"{_number(lambda_pm / l_d)} A peak ({_number(lambda_pm / l_d / math.sqrt(2))} A rms)" if numbers and l_d > 0 else "Needs d-axis current"
    )
    return [
        _section("d/q operating point", styles),
        _settings_grid(
            [
                ("Current angle", f"{_number(dq.get('current_angle_deg'))} deg"),
                ("Positions averaged", _number(dq.get("positions"))),
                ("d-axis current", f"{_number(dq.get('i_d_A'))} A"),
                ("q-axis current", f"{_number(dq.get('i_q_A'))} A"),
                ("d-axis flux linkage", milli(dq.get("lambda_d_Wb"), "mWb")),
                ("q-axis flux linkage", milli(dq.get("lambda_q_Wb"), "mWb")),
                ("Magnet flux linkage", milli(dq.get("lambda_pm_Wb"), "mWb")),
                ("d/q torque", f"{_number(dq.get('torque_dq_Nm'), 4)} N m"),
                ("Apparent Ld", milli(dq.get("apparent_L_d_H"), "mH") if dq.get("apparent_L_d_H") is not None else "No d-axis current"),
                ("Apparent Lq", milli(dq.get("apparent_L_q_H"), "mH") if dq.get("apparent_L_q_H") is not None else "No q-axis current"),
                ("Saliency Lq/Ld", saliency),
                ("Characteristic current", characteristic),
                ("Torque agreement", f"{_number(agreement, 4)}%" if agreement is not None else "Not recorded"),
            ],
            styles,
            columns=2,
            cell_widths=(40 * mm, 50 * mm),
        ),
        Paragraph(
            "Amplitude-invariant Park transform of the loaded phase flux linkages and the applied phase currents, averaged over the "
            "loaded rotor positions; the d-axis is placed from the no-load flux linkage. d/q torque is "
            "1.5 x pole pairs x (lambda_d i_q - lambda_q i_d); "
            "torque agreement is the solved average torque as a percentage of it. Apparent inductances are secant values at this "
            "operating point, (lambda_d - lambda_pm) / i_d and lambda_q / i_q, and include saturation and cross-coupling. "
            "Saliency near 1 means magnet torque only; well above 1 the rotor adds reluctance torque. The characteristic "
            "current lambda_pm / Ld cancels the magnet flux: a drive whose peak current reaches it can field-weaken to very high speed.",
            styles["small"],
        ),
        *_status_paragraphs(result, ("dq_flux_linkage",), styles),
    ]


def _winding_and_loss_story(result: Mapping[str, Any], styles: Mapping[str, ParagraphStyle]) -> list[Any]:
    summary = _mapping(result.get("summary"))
    winding = _mapping(summary.get("winding_resistance"))
    losses = _mapping(summary.get("loss_breakdown"))
    iron = _mapping(summary.get("iron_loss"))
    story: list[Any] = _dq_story(result, styles)
    if winding:
        wire = (
            f"{winding.get('strands_in_hand')} x {_number(winding.get('strand_diameter_mm'))} mm"
            + (" (derived from the slot)" if winding.get("wire_source") == "derived" else "")
        )
        story.extend([
            _section("Winding", styles),
            _settings_grid(
                [
                    ("Wire", wire),
                    ("Conductor", winding.get("conductor")),
                    ("Series turns per phase", _number(winding.get("series_turns_per_phase"), 4)),
                    ("Parallel paths", winding.get("parallel_paths")),
                    ("Mean turn length", f"{_number(winding.get('mean_turn_length_mm'))} mm"),
                    ("End turn, each end", f"{_number(winding.get('end_turn_length_mm'))} mm"),
                    ("Copper slot fill", f"{_percent(winding.get('copper_fill'))} of {_number(winding.get('slot_area_mm2'))} mm2"),
                    ("Fill limit", _percent(winding.get("copper_fill_limit"))),
                    ("Phase resistance, 20 C", _resistance_text(winding.get("phase_resistance_20C_ohm"))),
                    (f"Phase resistance, {_number(winding.get('winding_temperature_C'))} C", _resistance_text(winding.get("phase_resistance_ohm"))),
                ],
                styles,
                columns=2,
                cell_widths=(40 * mm, 50 * mm),
            ),
            *[Paragraph(escape(str(note)), styles["small"]) for note in _sequence(winding.get("notes"))],
            *_status_paragraphs(result, ("phase_resistance",), styles),
        ])
    if losses:
        efficiency = losses.get("efficiency_pct")
        efficiency_text = (
            f"{_number(efficiency, 4)}% ({losses.get('efficiency_status')})"
            if isinstance(efficiency, (int, float)) else f"Unavailable: {losses.get('efficiency_status_reason') or 'not recorded'}"
        )
        story.extend([
            _section("Losses and efficiency", styles),
            _settings_grid(
                [
                    ("Speed", f"{_number(losses.get('speed_rpm'), 5)} rpm"),
                    ("Phase current", f"{_number(losses.get('phase_current_rms_A'))} A rms"),
                    ("Solved torque", f"{_number(losses.get('electromagnetic_torque_Nm'), 4)} N m"),
                    ("Shaft torque", f"{_number(losses.get('shaft_torque_Nm'), 4)} N m"),
                    ("Copper loss", f"{_number(losses.get('copper_loss_W'))} W"),
                    ("Iron loss", f"{_number(losses.get('iron_loss_W'))} W" if losses.get("iron_loss_W") is not None else "Unavailable"),
                    ("Mechanical loss", f"{_number(losses.get('mechanical_loss_W'))} W"),
                    ("Total loss", f"{_number(losses.get('total_loss_W'))} W"),
                    ("Input power", f"{_number(losses.get('input_power_W'), 4)} W"),
                    ("Shaft power", f"{_number(losses.get('shaft_power_W'), 4)} W"),
                    ("Efficiency", efficiency_text),
                    ("Winding temperature", f"{_number(losses.get('winding_temperature_C'))} C"),
                ],
                styles,
                columns=2,
                cell_widths=(40 * mm, 50 * mm),
            ),
        ])
        bar = _loss_breakdown_drawing(losses)
        if bar is not None:
            story.extend([Spacer(1, 2 * mm), bar])
        status = []
        if iron.get("status") == "experimental":
            above_frequency = _percent(iron.get("share_above_validated_frequency"), 2)
            above_flux = _percent(iron.get("share_above_validated_flux_density"), 2)
            status.append(
                f"Iron loss is experimental: {escape(str(iron.get('status_reason') or ''))} "
                f"{above_frequency} of it comes from harmonics above {_number(iron.get('validated_max_frequency_Hz'))} Hz "
                f"and {above_flux} from flux densities above {_number(iron.get('validated_max_flux_density_T'))} T, "
                "outside the range the model was checked over."
            )
        elif iron.get("status_reason"):
            status.append(f"Iron loss unavailable: {escape(str(iron.get('status_reason')))}")
        status.append(
            "Shaft torque is the solved torque less the iron and mechanical loss torque; the solved torque is unchanged. "
            "Copper loss uses the phase resistance at the winding temperature. "
            "Not modelled: magnet and rotor eddy-current loss, AC copper loss (skin and proximity effects) and inverter loss."
        )
        story.extend(Paragraph(line, styles["small"]) for line in status)
        story.extend(_status_paragraphs(result, ("efficiency",), styles))
    density = _iron_loss_density_figure(result)
    if density is not None:
        peak = _mapping(result.get("iron_loss_density")).get("max_w_per_kg")
        story.extend([
            _section("Where the iron loss is", styles),
            density,
            Paragraph(
                "Iron-loss density: iron loss per kilogram of each stator element (hysteresis and eddy current together) "
                "over one electrical period, on the first stored rotor position's mesh. Darker is more loss. "
                f"The color scale stops at the 98th percentile; the peak is {_number(peak)} W/kg. "
                "Rotor and magnet losses are not modelled. Copper loss is not mapped: the model carries the same "
                "current density in every coil side.",
                styles["small"],
            ),
            *_status_paragraphs(result, ("iron_loss",), styles),
        ])
    return story


def _loss_breakdown_drawing(losses: Mapping[str, Any]) -> Drawing | None:
    """One stacked bar of the loss components, each named with its value."""

    hysteresis = losses.get("iron_hysteresis_loss_W")
    eddy = losses.get("iron_eddy_loss_W")
    segments = [
        ("Copper, stack", losses.get("copper_active_loss_W")),
        ("Copper, end turns", losses.get("copper_end_winding_loss_W")),
        ("Iron, hysteresis", hysteresis),
        ("Iron, eddy current", eddy),
        ("Mechanical", losses.get("mechanical_loss_W")),
    ]
    segments = [
        (label, float(value), color)
        for (label, value), color in zip(segments, _LOSS_SEGMENT_COLORS)
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0
    ]
    total = sum(value for _, value, _ in segments)
    if total <= 0:
        return None
    width, bar_height = 170 * mm, 7 * mm
    drawing = Drawing(width, 26 * mm)
    x = 0.0
    for label, value, color in segments:
        span = width * value / total
        drawing.add(Rect(x, 17 * mm, max(span - 0.7, 0.5), bar_height, fillColor=colors.HexColor(color), strokeColor=None))
        x += span
    drawing.add(String(0, 25.2 * mm, f"Loss breakdown, {total:.3g} W total", fontName="Helvetica-Bold", fontSize=8, fillColor=_NAVY))
    for index, (label, value, color) in enumerate(segments):
        column, line = index % 3, index // 3
        lx, ly = column * 58 * mm, (11 - line * 6) * mm
        drawing.add(Rect(lx, ly, 3 * mm, 3 * mm, fillColor=colors.HexColor(color), strokeColor=None))
        drawing.add(String(lx + 4.5 * mm, ly + 0.6 * mm, f"{label}: {value:.3g} W ({100 * value / total:.0f}%)",
                           fontName="Helvetica", fontSize=7.5, fillColor=_SLATE))
    return drawing


def _density_scale_max(values: Sequence[float]) -> float:
    """98th percentile: a few tooth-tip elements would otherwise flatten the rest of the map."""

    ordered = sorted(values)
    return ordered[int(0.98 * (len(ordered) - 1))]


def _iron_loss_density_figure(result: Mapping[str, Any]) -> _MotorMeshFigure | None:
    density = _mapping(result.get("iron_loss_density"))
    values = _sequence(density.get("element_w_per_kg"))
    plot = _mapping(result.get("field_line_plot"))
    mesh = _saved_motor_mesh(plot)
    if mesh is None or not values:
        return None
    nodes, triangles, groups = mesh
    if len(values) != len(triangles):
        return None
    numbers = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
    if not numbers:
        return None
    high = _density_scale_max(numbers)
    used = {index for triangle in triangles for index in triangle}
    min_x, max_x = min(nodes[i][0] for i in used), max(nodes[i][0] for i in used)
    min_y, max_y = min(nodes[i][1] for i in used), max(nodes[i][1] for i in used)
    span = max(max_x - min_x, max_y - min_y)
    if span <= 0 or high <= 0:
        return None
    size = 1200
    scale = size * 0.94 / span
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2
    pixels = [(size / 2 + (x - center_x) * scale, size / 2 - (y - center_y) * scale) for x, y in nodes]
    image = PILImage.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    for triangle, group, value in zip(triangles, groups, values):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            fill = _ramp_color(_STEEL_RAMP, min(value, high) / high)
        elif group == "air":
            fill = "#FFFFFF"
        elif group == "winding":
            fill = _COIL_SIDE_FILL
        else:
            fill = _NOT_MODELLED_FILL
        draw.polygon([pixels[i] for i in triangle], fill=fill)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return _MotorMeshFigure(
        buffer.getvalue(), field_range=(0.0, high), legend_title="Iron loss (W/kg)",
        legend_note="Cream: not modelled (rotor, magnets)\nLight grey: coil sides (copper loss is uniform)",
        value_format="{:.3g}", legend_colors=_STEEL_RAMP,
    )


def _ramp_color(stops: Sequence[str], fraction: float) -> str:
    """Hex colour at a fraction of a ramp listed from its low end, interpolated between steps."""

    rgb = [tuple(int(stop[i:i + 2], 16) for i in (1, 3, 5)) for stop in stops]
    t = min(1.0, max(0.0, fraction)) * (len(rgb) - 1)
    index = min(len(rgb) - 2, int(t))
    local = t - index
    low, high = rgb[index], rgb[index + 1]
    return "#" + "".join(f"{round(a + (b - a) * local):02x}" for a, b in zip(low, high))


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
                *_qualification_row(manifest),
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
    output_statuses = _output_statuses(result)
    magnet_status = next((status for key, _, status, _ in output_statuses if key == "magnet_temperature"), None)
    story.extend(
        [
            _section("Operating point and mesh", styles),
            # A compact grid, so the provenance below fits on the first page.
            _settings_grid(
                [
                    (
                        "Conducting phase current" if six_step else "Phase current",
                        (f"{_plain(solve_params.get('current_amplitude_A'))} A {_plain(solve_params.get('current_amplitude_convention'))}").strip(),
                    ),
                    (
                        "Commutation advance" if six_step else (
                            "Pyleecan d-axis Phi0" if _mapping(request.get("resolved_config")).get("geometry_reference") else "Current angle"
                        ),
                        f"{_plain(solve_params.get('commutation_advance_deg') if six_step else solve_params.get('current_angle_deg'))} deg",
                    ),
                    ("Excitation", "Ideal six-step (120 deg)" if six_step else "Sinusoidal"),
                    ("Phase connection", solve_params.get("phase_connection") if six_step else "Not recorded"),
                    ("Rated speed", f"{_plain(solve_params.get('rated_speed_rpm'))} rpm"),
                    *(
                        [
                            (
                                "Magnet temperature",
                                f"{_number(solve_metadata.get('magnet_temperature_C'))} C, "
                                + (f"{magnet_status} derating" if magnet_status else "catalogue values"),
                            ),
                            ("Magnet Br at temperature", f"{_number(solve_metadata.get('magnet_remanence_T'), 4)} T"),
                            ("Magnet HcJ at temperature", f"{_number(solve_metadata.get('magnet_intrinsic_coercivity_kA_m'))} kA/m"),
                        ]
                        if solve_metadata.get("magnet_remanence_T") is not None
                        else []
                    ),
                    ("Solve quality", solve_params.get("solve_quality")),
                    ("Mesh density", solve_metadata.get("mesh_density") or solve_params.get("mesh_density")),
                    ("Mesh elements", solve_metadata.get("mesh_element_count")),
                    ("Rotor positions", solve_metadata.get("rotor_positions")),
                    ("Torque method used", solve_metadata.get("torque_method") or "Not recorded"),
                    ("Torque method requested", solve_params.get("torque_method")),
                ],
                styles,
                columns=2,
                cell_widths=(40 * mm, 50 * mm),
            ),
            KeepTogether(
                [
                    _section("Solver and build provenance", styles),
                    _key_value_table(
                        [
                            ("Solver", solve_metadata.get("solver_name") or provenance.get("solver_name")),
                            ("Application version", provenance.get("application_version")),
                            ("Application commit", provenance.get("application_commit")),
                            *_build_rows(_mapping(provenance.get("build"))),
                            ("Platform", _plain(provenance.get("platform"))),
                            ("Result SHA-256", _mapping(manifest.get("bindings")).get("result_sha256")),
                            ("Resolved request SHA-256", _mapping(manifest.get("bindings")).get("resolved_request_sha256")),
                        ],
                        styles,
                    ),
                ]
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
    story.extend(_winding_and_loss_story(result, styles))
    if torque_plot is not None or back_emf_plot is not None:
        story.append(_section("Stored result plots", styles))
        if torque_plot is not None:
            story.extend([torque_plot, Spacer(1, 3 * mm)])
        if back_emf_plot is not None:
            story.append(back_emf_plot)

    setting_groups = _design_setting_groups(_mapping(request.get("resolved_config")))
    if setting_groups:
        topology = _plain(_mapping(request.get("resolved_config")).get("topology")) or "this"
        setting_blocks = [
            [Paragraph(escape(title), styles["group"]), _settings_grid(entries, styles)]
            for title, entries in setting_groups
        ]
        # The section starts a page, which it fits on for the bundled designs;
        # each group stays in one piece if a longer design needs a second page.
        story.append(PageBreak())
        story.append(
            KeepTogether(
                [
                    _section("Resolved settings for this design", styles),
                    Paragraph(
                        escape(
                            f"The stored settings that define this {topology} design and its solve. Settings "
                            "of other rotor types or the other excitation, settings the solve plan does "
                            "not use, empty values and runtime-only switches are left out."
                        ),
                        styles["small"],
                    ),
                    *setting_blocks[0],
                ]
            )
        )
        story.extend(KeepTogether(block) for block in setting_blocks[1:])
        story.extend(
            [
                Spacer(1, 2 * mm),
                Paragraph(
                    escape(
                        "Every stored setting, including those left out here, is in the setting rows of "
                        "report.csv and in request.json, both in the run folder and in run-package.zip. "
                        "The resolved request SHA-256, of request.json as canonical JSON, is "
                        f"{_plain(_mapping(manifest.get('bindings')).get('resolved_request_sha256')) or 'not recorded'}."
                    ),
                    styles["small"],
                ),
            ]
        )

    if output_statuses:
        story.append(
            KeepTogether(
                [
                    _section("Status of the performance outputs", styles),
                    Paragraph(
                        "Qualified outputs pass a benchmark gate against a reference; experimental outputs have none yet. "
                        "A design's qualification covers its torque and back EMF, not these outputs.",
                        styles["small"],
                    ),
                    Spacer(1, 1.5 * mm),
                    _key_value_table([(output, _status_text(status, reason)) for _, output, status, reason in output_statuses], styles),
                ]
            )
        )

    # Keep each closing heading on the page of its first line.
    warnings = _warnings(result)
    warning_lines = [Paragraph(f"- {escape(warning)}", styles["body"]) for warning in warnings] or [
        Paragraph("No solver warnings were recorded.", styles["body"])
    ]
    story.extend([KeepTogether([_section("Warnings", styles), warning_lines[0]]), *warning_lines[1:]])
    limitations = [
        *PUBLIC_REPORT_LIMITATIONS,
        *((SIX_STEP_REPORT_LIMITATION,) if six_step else ()),
        *_qualification_limitations(manifest),
    ]
    limitation_lines = [Paragraph(f"- {escape(limitation)}", styles["body"]) for limitation in limitations]
    story.extend([KeepTogether([_section("Known limitations", styles), limitation_lines[0]]), *limitation_lines[1:]])

    document.build(
        story,
        onFirstPage=page_chrome,
        onLaterPages=page_chrome,
        canvasmaker=_InvariantCanvas,
    )
    return buffer.getvalue()


# Playback layers and field frames are already compressed. Deflating them
# again at level 9 took ~4.7 s per IPM run and shrank ~300 MB by ~1%.
_ALREADY_COMPRESSED_SUFFIXES = frozenset({".gz", ".png", ".webp", ".zip"})


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
            info.compress_type = (
                zipfile.ZIP_STORED
                if source.suffix.lower() in _ALREADY_COMPRESSED_SUFFIXES
                else zipfile.ZIP_DEFLATED
            )
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
