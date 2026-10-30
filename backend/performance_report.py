"""Performance report (#142): the Torque-speed tab's results as a PDF and CSVs.

A run's own PDF and CSV are written when its solve completes and are bound by
hash to the stored run. Torque-speed results come later, from a flux-linkage
map and the drive limits set on the Torque-speed tab, so this report is built
on demand from the request the tab sends to /performance/drive, with the same
functions: it carries the values the tab shows.

- The PDF: inputs, the headline numbers, the torque- and power-speed curves,
  the efficiency map, the MTPA trajectory, and flux linkage and apparent
  inductance against current, each labelled with its status.
- The performance CSV: every number in the PDF and every sample behind its
  plots, long-form like the run CSV.
- The id/iq table: lambda_d, lambda_q and torque on a rectangular id x iq grid
  inside the map's largest current, for drive-control models.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Optional

import numpy as np
from pydantic import BaseModel, Field
from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.drive_performance import MapModel, efficiency_map, torque_speed_envelope
from backend.export_safety import literal_csv_cell
from backend.flux_linkage_map import map_agreement_pct
from backend.models.performance import (
    DQ_FLUX_LINKAGE_STATUS_REASON,
    MAGNET_TEMPERATURE_STATUS_REASON,
    PHASE_RESISTANCE_STATUS_REASON,
    DriveControl,
    DriveLimits,
    EfficiencyMap,
    FluxLinkageMap,
    TorqueSpeedCurve,
    TorqueSpeedEnvelope,
)
from backend.public_report import (
    _BORDER,
    _LIGHT,
    _NAVY,
    _SLATE,
    _InvariantCanvas,
    _key_value_table,
    _plain,
    _report_styles,
    _safe_paragraph,
    _section,
)
from backend.resources import application_commit

PERFORMANCE_REPORT_SCHEMA = "coilem.performance_report.v1"
IDIQ_TABLE_SCHEMA = "coilem.idiq_table.v1"

# The app's curve colours (frontend/src/public/PerformancePanel.tsx), validated on a white page.
_CURVE_COLORS = {"peak": colors.HexColor("#3987e5"), "continuous": colors.HexColor("#d95926")}
# The app's efficiency blues, reversed for a white page: darker is more efficient.
_EFFICIENCY_RAMP = ("#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95")
_LAMBDA_COLORS = {"d": colors.HexColor("#3987e5"), "q": colors.HexColor("#d95926")}

MTPA_SAMPLES = 21
# The map's d/q values have no benchmark gate yet (DQ_FLUX_LINKAGE_STATUS_REASON).
_DQ_STATUS = "experimental"
IDIQ_STEPS = 21
_MTPA_ANGLE_STEP_DEG = 0.1

_LIMITATIONS = (
    "Interpolated from a flux-linkage map (Catmull-Rom over current and current angle); nothing is extrapolated beyond its "
    "currents and angles. Not yet compared with measured data.",
    "Steady state with sinusoidal current. Inverter voltage drops, dead time and the voltage behind the iron-loss resistance are left out.",
    "Torque is electromagnetic. Shaft output subtracts iron loss and the mechanical loss entered for the design.",
    "Iron loss is scaled from the map's reference speed: hysteresis with frequency, eddy current with its square.",
)


class SolvedPoint(BaseModel):
    """The run's solved operating point, marked on the charts."""

    speed_rpm: float = Field(gt=0)
    torque_Nm: float
    current_angle_deg: Optional[float] = None


class ReportContext(BaseModel):
    """What the tab knows beyond the drive request: names, units and the solved point."""

    design_name: Optional[str] = Field(default=None, max_length=200)
    current_unit: Literal["A rms", "A peak"] = "A rms"
    dc_bus_source: Literal["design", "entered", "estimated"] = "entered"
    map_preset: Optional[str] = Field(default=None, max_length=40)
    solved_point: Optional[SolvedPoint] = None
    magnet_temperature_derated: bool = Field(
        default=False, description="The run derated its magnets for temperature, so every map point did too"
    )


@dataclass(frozen=True)
class InductanceRow:
    current_peak_A: float
    l_d_H: float | None
    l_q_H: float | None


@dataclass(frozen=True)
class TrajectoryRow:
    current_peak_A: float
    gamma_deg: float
    i_d_A: float
    i_q_A: float
    torque_Nm: float
    lambda_d_Wb: float
    lambda_q_Wb: float


@dataclass(frozen=True)
class PerformanceData:
    flux_map: FluxLinkageMap
    limits: DriveLimits
    phase_resistance_ohm: float
    winding_temperature_C: float
    mechanical_loss_W: float
    control: DriveControl
    envelope: TorqueSpeedEnvelope
    efficiency: EfficiencyMap
    agreement_pct: list[float]
    inductance: list[InductanceRow]
    mtpa: list[TrajectoryRow]
    idiq: list[TrajectoryRow]

    def curve(self, limit: str) -> TorqueSpeedCurve | None:
        return next((curve for curve in self.envelope.curves if curve.limit == limit), None)

    @property
    def best_efficiency_pct(self) -> float | None:
        values = [value for row in self.efficiency.efficiency_pct for value in row if value is not None]
        return max(values) if values else None


def _inductance(flux_map: FluxLinkageMap) -> list[InductanceRow]:
    """Secant Ld from the 90 deg points and Lq from the 0 deg points, as the tab's table computes them."""

    points = {(point.current_peak_A, point.gamma_deg): point for point in flux_map.points if point.status == "ok"}
    zero = points.get((0.0, flux_map.gamma_deg[0]))
    lambda_pm = zero.lambda_d_Wb if zero is not None else None
    rows = []
    for current in flux_map.current_peak_A:
        if current <= 0:
            continue
        d_axis, q_axis = points.get((current, 90.0)), points.get((current, 0.0))
        l_d = (d_axis.lambda_d_Wb - lambda_pm) / d_axis.i_d_A if d_axis is not None and lambda_pm is not None and abs(d_axis.i_d_A) > 1e-9 else None
        l_q = q_axis.lambda_q_Wb / q_axis.i_q_A if q_axis is not None and abs(q_axis.i_q_A) > 1e-9 else None
        rows.append(InductanceRow(current, l_d, l_q))
    return rows


def _rows(model: MapModel, currents: np.ndarray, gammas: np.ndarray) -> list[TrajectoryRow]:
    sampled = model.sample_points(currents, gammas)
    radians = np.radians(gammas)
    return [
        TrajectoryRow(
            current_peak_A=float(current),
            gamma_deg=float(gamma),
            i_d_A=float(-current * math.sin(angle)),
            i_q_A=float(current * math.cos(angle)),
            torque_Nm=float(torque),
            lambda_d_Wb=float(lambda_d),
            lambda_q_Wb=float(lambda_q),
        )
        for current, gamma, angle, torque, lambda_d, lambda_q in zip(
            currents, gammas, radians, sampled["torque"], sampled["lambda_d"], sampled["lambda_q"]
        )
    ]


def _mtpa(model: MapModel, current_limit_A: float) -> list[TrajectoryRow]:
    """The current angle of most torque at each current, motoring, on a 0.1 deg grid of the map's angles."""

    low, high = max(0.0, float(model.gammas_deg[0])), min(90.0, float(model.gammas_deg[-1]))
    gammas = np.arange(low, high + _MTPA_ANGLE_STEP_DEG / 2, _MTPA_ANGLE_STEP_DEG)
    currents = np.linspace(0.0, current_limit_A, MTPA_SAMPLES)
    torque = model.sample(currents, gammas)["torque"]
    best = gammas[np.argmax(torque, axis=1)]
    best[0] = low  # no torque at zero current; any angle will do
    return _rows(model, currents, best)


def _idiq(model: MapModel) -> list[TrajectoryRow]:
    """λd, λq and torque on a rectangular id x iq grid, kept where the map covers the point."""

    largest = float(model.currents_A[-1])
    i_d, i_q = np.meshgrid(np.linspace(-largest, 0.0, IDIQ_STEPS), np.linspace(0.0, largest, IDIQ_STEPS))
    i_d, i_q = i_d.ravel(), i_q.ravel()
    currents = np.hypot(i_d, i_q)
    gammas = np.degrees(np.arctan2(-i_d, i_q))
    covered = (currents <= largest * (1 + 1e-9)) & (gammas >= model.gammas_deg[0] - 1e-9) & (gammas <= model.gammas_deg[-1] + 1e-9)
    rows = _rows(model, currents[covered], gammas[covered])
    # Report the grid's own id and iq, not the ones rebuilt from |I| and γ.
    return [
        TrajectoryRow(row.current_peak_A, row.gamma_deg, float(d), float(q), row.torque_Nm, row.lambda_d_Wb, row.lambda_q_Wb)
        for row, d, q in zip(rows, i_d[covered], i_q[covered])
    ]


def performance_data(
    flux_map: FluxLinkageMap,
    limits: DriveLimits,
    *,
    phase_resistance_ohm: float,
    winding_temperature_C: float,
    mechanical_loss_W: float = 0.0,
    control: DriveControl = "mtpa",
) -> PerformanceData:
    """Everything the report shows, computed as /performance/drive computes the tab's curves."""

    envelope = torque_speed_envelope(flux_map, limits, phase_resistance_ohm=phase_resistance_ohm, winding_temperature_C=winding_temperature_C)
    efficiency = efficiency_map(
        flux_map,
        limits,
        phase_resistance_ohm=phase_resistance_ohm,
        winding_temperature_C=winding_temperature_C,
        mechanical_loss_W=mechanical_loss_W,
        envelope=envelope,
        control=control,
    )
    model = MapModel.from_map(flux_map)
    return PerformanceData(
        flux_map=flux_map,
        limits=limits,
        phase_resistance_ohm=phase_resistance_ohm,
        winding_temperature_C=winding_temperature_C,
        mechanical_loss_W=mechanical_loss_W,
        control=control,
        envelope=envelope,
        efficiency=efficiency,
        agreement_pct=[value for value in map_agreement_pct(flux_map) if value is not None and math.isfinite(value)],
        inductance=_inductance(flux_map),
        mtpa=_mtpa(model, min(limits.peak_current_A, float(model.currents_A[-1]))),
        idiq=_idiq(model),
    )


# ── Shared wording ──────────────────────────────────────────────────────────


_CONTROL_LABEL = {
    "mtpa": "MTPA, then field weakening (least current per torque)",
    "least_loss": "Least loss (least copper plus iron loss per torque)",
}
_BUS_SOURCE = {"design": "from the design", "entered": "as entered", "estimated": "estimated from the back EMF"}
_REGION_LABEL = {"mtpa": "MTPA", "field_weakening": "Field weakening", "mtpv": "MTPV"}


def _g(value: float | None, digits: int = 4) -> str:
    """Four significant figures without exponents for the report's quantities; round-off below 1e-9 reads 0."""

    if value is None or not math.isfinite(value):
        return "-"
    if abs(value) < 1e-9:
        return "0"
    if abs(value) >= 10**digits:
        return f"{value:.0f}"
    return f"{value:.{digits}g}"


def _shown(peak_A: float, context: ReportContext) -> float:
    return peak_A / math.sqrt(2) if context.current_unit == "A rms" else peak_A


def _current_text(peak_A: float | None, context: ReportContext) -> str:
    if peak_A is None:
        return "-"
    other = f"{_g(peak_A)} A peak" if context.current_unit == "A rms" else f"{_g(peak_A / math.sqrt(2))} A rms"
    return f"{_g(_shown(peak_A, context))} {context.current_unit} ({other})"


def output_statuses(data: PerformanceData, context: ReportContext) -> list[tuple[str, str, str, str]]:
    """(key, output, status, reason) of each output in the report (public issue 143)."""

    statuses = [
        ("torque_speed", "Torque-speed envelope", data.envelope.status, data.envelope.status_reason or ""),
        ("efficiency_map", "Efficiency map", data.efficiency.status, data.efficiency.status_reason or ""),
        ("dq_flux_linkage", "Map flux linkage, MTPA trajectory and inductances", "experimental", DQ_FLUX_LINKAGE_STATUS_REASON),
    ]
    if data.phase_resistance_ohm > 0:
        statuses.append(("phase_resistance", "Phase resistance and copper loss", "experimental", PHASE_RESISTANCE_STATUS_REASON))
    if context.magnet_temperature_derated:
        statuses.append(("magnet_temperature", "Magnet temperature derating", "experimental", MAGNET_TEMPERATURE_STATUS_REASON))
    return statuses


def _notes(data: PerformanceData) -> list[str]:
    notes = []
    if data.agreement_pct:
        notes.append(
            f"FEM torque is {min(data.agreement_pct):.1f}-{max(data.agreement_pct):.1f}% of the d/q torque across "
            f"{len(data.agreement_pct)} map points."
        )
    notes.append(
        "Ld from the 90 deg points, (lambda_d - lambda_pm) / i_d; Lq from the 0 deg points, lambda_q / i_q. Both are secant "
        "values and include saturation."
    )
    steps = [later - earlier for earlier, later in zip(data.flux_map.gamma_deg, data.flux_map.gamma_deg[1:])]
    notes.append(
        f"The MTPA angle is read off the interpolated map, whose angles are {max(steps):g} deg apart at most. At low current, "
        "where torque hardly changes with angle, it is approximate; a finer map grid gives a smoother trajectory."
    )
    notes.extend(reason for reason in (data.envelope.status_reason, data.efficiency.status_reason) if reason)
    return notes


# ── CSV ─────────────────────────────────────────────────────────────────────


def _csv_writer() -> tuple[io.StringIO, Callable[..., None]]:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")

    def row(section: str, field: str, value: Any, unit: str = "", sample_index: int | str = "") -> None:
        writer.writerow([_plain(literal_csv_cell(item)) for item in (section, field, unit, value, sample_index)])

    return output, row


def build_performance_csv(data: PerformanceData, context: ReportContext) -> bytes:
    """Every number of the performance report, long-form: section, field, unit, value, sample_index."""

    output, row = _csv_writer()
    output.write(f"report_schema,{PERFORMANCE_REPORT_SCHEMA}\r\n")
    row("section", "field", "unit", "value", "sample_index")  # header, written through the same escaping
    flux_map, limits = data.flux_map, data.limits

    row("identity", "design_name", context.design_name)
    row("identity", "application_commit", application_commit())
    row("identity", "map_scope_key", flux_map.scope_key)
    row("identity", "current_unit_shown", context.current_unit)

    row("input", "peak_current_peak", limits.peak_current_A, "A")
    row("input", "peak_current_rms", limits.peak_current_A / math.sqrt(2), "A")
    if limits.continuous_current_A is not None:
        row("input", "continuous_current_peak", limits.continuous_current_A, "A")
        row("input", "continuous_current_rms", limits.continuous_current_A / math.sqrt(2), "A")
    row("input", "dc_bus", limits.dc_bus_V, "V")
    row("input", "dc_bus_source", context.dc_bus_source)
    row("input", "modulation_index_max", limits.modulation_index_max)
    row("input", "phase_voltage_limit_peak", limits.modulation_index_max * limits.dc_bus_V / 2, "V")
    row("input", "max_speed", limits.max_speed_rpm, "rpm")
    row("input", "control", data.control)
    row("input", "phase_resistance", data.phase_resistance_ohm, "ohm")
    row("input", "winding_temperature", data.winding_temperature_C, "degC")
    row("input", "mechanical_loss", data.mechanical_loss_W, "W")

    row("map", "preset", context.map_preset)
    row("map", "pole_pairs", flux_map.pole_pairs)
    row("map", "currents", len(flux_map.current_peak_A))
    row("map", "current_angles", len(flux_map.gamma_deg))
    row("map", "largest_current_peak", flux_map.current_peak_A[-1], "A")
    row("map", "rotor_positions_per_point", flux_map.rotor_positions)
    row("map", "mesh_density", flux_map.mesh_density)
    row("map", "reference_speed", flux_map.reference_speed_rpm, "rpm")
    row("map", "magnet_temperature", flux_map.magnet_temperature_C, "degC")
    row("map", "current_angle_convention", flux_map.current_angle_convention)
    row("map", "transform", flux_map.transform)

    for key, _output, status, reason in output_statuses(data, context):
        row("status", key, status)
        row("status", f"{key}_reason", reason)

    peak = data.curve("peak")
    if peak is not None:
        row("result", "peak_torque", peak.torque_Nm[0], "N m")
        row("result", "base_speed", peak.base_speed_rpm, "rpm")
        row("result", "peak_power", peak.peak_power_W, "W")
        row("result", "top_speed_reached", peak.max_speed_rpm, "rpm")
    row("result", "best_efficiency", data.best_efficiency_pct, "%")
    if context.solved_point is not None:
        row("result", "solved_point_speed", context.solved_point.speed_rpm, "rpm")
        row("result", "solved_point_torque", context.solved_point.torque_Nm, "N m")
        row("result", "solved_point_current_angle", context.solved_point.current_angle_deg, "deg")

    for curve in data.envelope.curves:
        section = f"torque_speed_{curve.limit}"
        row(section, "base_speed", curve.base_speed_rpm, "rpm")
        row(section, "max_speed", curve.max_speed_rpm, "rpm")
        row(section, "peak_power", curve.peak_power_W, "W")
        for index, speed in enumerate(curve.speed_rpm):
            i_d, i_q = curve.i_d_A[index], curve.i_q_A[index]
            current = math.hypot(i_d, i_q)
            row(section, "speed", speed, "rpm", index)
            row(section, "torque", curve.torque_Nm[index], "N m", index)
            row(section, "power", curve.power_W[index], "W", index)
            row(section, "i_d", i_d, "A", index)
            row(section, "i_q", i_q, "A", index)
            row(section, "current_peak", current, "A", index)
            row(section, "current_rms", current / math.sqrt(2), "A", index)
            row(section, "current_angle", math.degrees(math.atan2(-i_d, i_q)) if current > 0 else 0.0, "deg", index)
            row(section, "phase_voltage_peak", curve.phase_voltage_peak_V[index], "V", index)
            row(section, "region", curve.region[index], "", index)

    efficiency = data.efficiency
    index = 0
    for row_index, torque in enumerate(efficiency.torque_Nm):
        for column, speed in enumerate(efficiency.speed_rpm):
            value = efficiency.efficiency_pct[row_index][column]
            if value is None:
                continue
            row("efficiency_map", "speed", speed, "rpm", index)
            row("efficiency_map", "torque", torque, "N m", index)
            row("efficiency_map", "efficiency", value, "%", index)
            row("efficiency_map", "copper_loss", efficiency.copper_loss_W[row_index][column], "W", index)
            row("efficiency_map", "iron_loss", efficiency.iron_loss_W[row_index][column], "W", index)
            if efficiency.phase_current_rms_A is not None:
                row("efficiency_map", "current_rms", efficiency.phase_current_rms_A[row_index][column], "A", index)
            if efficiency.current_angle_deg is not None:
                row("efficiency_map", "current_angle", efficiency.current_angle_deg[row_index][column], "deg", index)
            index += 1
    row("efficiency_map", "mechanical_loss", efficiency.mechanical_loss_W, "W")
    row("efficiency_map", "control", efficiency.control)

    for section, rows in (("mtpa", data.mtpa), ("idiq_table", data.idiq)):
        for index, entry in enumerate(rows):
            row(section, "current_peak", entry.current_peak_A, "A", index)
            row(section, "current_angle", entry.gamma_deg, "deg", index)
            row(section, "i_d", entry.i_d_A, "A", index)
            row(section, "i_q", entry.i_q_A, "A", index)
            row(section, "torque", entry.torque_Nm, "N m", index)
            row(section, "lambda_d", entry.lambda_d_Wb, "Wb", index)
            row(section, "lambda_q", entry.lambda_q_Wb, "Wb", index)

    for index, entry in enumerate(data.inductance):
        row("inductance", "current_peak", entry.current_peak_A, "A", index)
        row("inductance", "L_d", entry.l_d_H, "H", index)
        row("inductance", "L_q", entry.l_q_H, "H", index)

    agreement = map_agreement_pct(flux_map)
    for index, point in enumerate(flux_map.points):
        row("map_point", "current_peak", point.current_peak_A, "A", index)
        row("map_point", "current_angle", point.gamma_deg, "deg", index)
        row("map_point", "i_d", point.i_d_A, "A", index)
        row("map_point", "i_q", point.i_q_A, "A", index)
        row("map_point", "status", point.status, "", index)
        row("map_point", "torque", point.avg_torque_Nm, "N m", index)
        row("map_point", "lambda_d", point.lambda_d_Wb, "Wb", index)
        row("map_point", "lambda_q", point.lambda_q_Wb, "Wb", index)
        row("map_point", "iron_loss", point.iron_loss_W, "W", index)
        row("map_point", "torque_agreement", agreement[index], "%", index)

    for index, note in enumerate(_notes(data)):
        row("note", "message", note, sample_index=index)
    for index, limitation in enumerate(_LIMITATIONS):
        row("known_limitation", "message", limitation, sample_index=index)
    return output.getvalue().encode("utf-8")


def build_idiq_table_csv(data: PerformanceData, context: ReportContext) -> bytes:
    """λd, λq and torque on a rectangular id x iq grid, one row per covered point."""

    flux_map = data.flux_map
    output = io.StringIO(newline="")
    for comment in (
        f"# coilEM id/iq table, {IDIQ_TABLE_SCHEMA}",
        f"# design: {context.design_name or 'unnamed'}; map scope {flux_map.scope_key}; {flux_map.pole_pairs} pole pairs",
        "# Amplitude-invariant Park transform; currents are peak phase amperes; i_d = -I sin(gamma), i_q = I cos(gamma), "
        "gamma from the q-axis toward field weakening",
        f"# {IDIQ_STEPS} x {IDIQ_STEPS} grid over i_d -{_g(flux_map.current_peak_A[-1])}..0 A and i_q 0..{_g(flux_map.current_peak_A[-1])} A, "
        "kept inside the map's largest current; values interpolated (Catmull-Rom over |I| and gamma) from the map's FEM points",
        f"# experimental: {DQ_FLUX_LINKAGE_STATUS_REASON} Generated by coilEM {application_commit()}",
    ):
        output.write(literal_csv_cell(comment).replace("\n", " ") + "\r\n")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(["i_d_A", "i_q_A", "current_peak_A", "current_rms_A", "gamma_deg", "lambda_d_Wb", "lambda_q_Wb", "torque_Nm"])
    for entry in data.idiq:
        writer.writerow(
            [
                format(value, ".10g")
                for value in (
                    entry.i_d_A,
                    entry.i_q_A,
                    entry.current_peak_A,
                    entry.current_peak_A / math.sqrt(2),
                    entry.gamma_deg,
                    entry.lambda_d_Wb,
                    entry.lambda_q_Wb,
                    entry.torque_Nm,
                )
            ]
        )
    return output.getvalue().encode("utf-8")


# ── PDF charts ──────────────────────────────────────────────────────────────


def _nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Round ticks covering [low, high] in steps of 1, 2 or 5 x 10^n, as the app's charts use."""

    span = high - low
    if not span > 0:
        return [low]
    raw = span / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next((factor * magnitude for factor in (1, 2, 5, 10) if factor * magnitude >= raw), 10 * magnitude)
    first = math.floor(low / step + 1e-9) * step
    ticks = [first]
    while ticks[-1] < high - step * 1e-9:
        ticks.append(round(ticks[-1] + step, 12))
    return ticks


class _Chart:
    """A titled x-y plot area with round ticks, light grid and a status tag."""

    WIDTH, HEIGHT = 180 * mm, 72 * mm
    LEFT, RIGHT, BOTTOM, TOP = 17 * mm, 5 * mm, 12 * mm, 13 * mm

    def __init__(self, title: str, status: str, x_label: str, y_label: str, x_range: tuple[float, float], y_range: tuple[float, float]):
        self.drawing = Drawing(self.WIDTH, self.HEIGHT)
        self.x_ticks = _nice_ticks(*x_range)
        self.y_ticks = _nice_ticks(*y_range)
        self.x0, self.x1 = self.x_ticks[0], self.x_ticks[-1]
        self.y0, self.y1 = self.y_ticks[0], self.y_ticks[-1]
        d = self.drawing
        d.add(String(0, self.HEIGHT - 4 * mm, title, fontName="Helvetica-Bold", fontSize=9, fillColor=_NAVY))
        tag = status.capitalize()
        width = stringWidth(tag, "Helvetica-Bold", 6.5) + 3 * mm
        d.add(Rect(self.WIDTH - width, self.HEIGHT - 5.2 * mm, width, 4.2 * mm, fillColor=_LIGHT, strokeColor=_BORDER, strokeWidth=0.4))
        d.add(
            String(
                self.WIDTH - width / 2, self.HEIGHT - 4.2 * mm, tag, fontName="Helvetica-Bold", fontSize=6.5, fillColor=_SLATE, textAnchor="middle"
            )
        )
        for tick in self.x_ticks:
            x = self.x(tick)
            d.add(Line(x, self.BOTTOM, x, self.HEIGHT - self.TOP, strokeColor=_BORDER, strokeWidth=0.25))
            d.add(String(x, self.BOTTOM - 3.5 * mm, _g(tick, 6), fontName="Helvetica", fontSize=6, fillColor=_SLATE, textAnchor="middle"))
        for tick in self.y_ticks:
            y = self.y(tick)
            d.add(Line(self.LEFT, y, self.WIDTH - self.RIGHT, y, strokeColor=_BORDER, strokeWidth=0.25))
            d.add(String(self.LEFT - 1.5 * mm, y - 2, _g(tick, 6), fontName="Helvetica", fontSize=6, fillColor=_SLATE, textAnchor="end"))
        d.add(Line(self.LEFT, self.BOTTOM, self.WIDTH - self.RIGHT, self.BOTTOM, strokeColor=_SLATE, strokeWidth=0.6))
        d.add(Line(self.LEFT, self.BOTTOM, self.LEFT, self.HEIGHT - self.TOP, strokeColor=_SLATE, strokeWidth=0.6))
        d.add(
            String(
                (self.LEFT + self.WIDTH - self.RIGHT) / 2,
                1.5 * mm,
                x_label,
                fontName="Helvetica",
                fontSize=6.5,
                fillColor=_SLATE,
                textAnchor="middle",
            )
        )
        d.add(String(0, self.HEIGHT - self.TOP + 2 * mm, y_label, fontName="Helvetica", fontSize=6.5, fillColor=_SLATE))
        self._legend_x = self.LEFT + 30 * mm

    def x(self, value: float) -> float:
        return self.LEFT + (value - self.x0) / (self.x1 - self.x0) * (self.WIDTH - self.LEFT - self.RIGHT)

    def y(self, value: float) -> float:
        return self.BOTTOM + (value - self.y0) / (self.y1 - self.y0) * (self.HEIGHT - self.BOTTOM - self.TOP)

    def line(self, xs: Sequence[float], ys: Sequence[float], color: colors.Color, *, width: float = 1.4, dash: Sequence[float] | None = None) -> None:
        points = [coordinate for x, y in zip(xs, ys) if math.isfinite(x) and math.isfinite(y) for coordinate in (self.x(x), self.y(y))]
        if len(points) >= 4:
            self.drawing.add(PolyLine(points, strokeColor=color, strokeWidth=width, strokeDashArray=dash))

    def legend(self, label: str, color: colors.Color) -> None:
        y = self.HEIGHT - self.TOP + 2 * mm
        self.drawing.add(Line(self._legend_x, y + 2, self._legend_x + 5 * mm, y + 2, strokeColor=color, strokeWidth=1.6))
        self.drawing.add(String(self._legend_x + 6 * mm, y, label, fontName="Helvetica", fontSize=6.5, fillColor=_NAVY))
        self._legend_x += stringWidth(label, "Helvetica", 6.5) + 12 * mm

    def marker(self, x: float, y: float, label: str) -> None:
        cx, cy = self.x(x), self.y(y)
        self.drawing.add(Circle(cx, cy, 4, fillColor=None, strokeColor=_NAVY, strokeWidth=1.1))
        self.drawing.add(Circle(cx, cy, 1.2, fillColor=_NAVY, strokeColor=None))
        right = cx < self.WIDTH * 0.7
        self.drawing.add(
            String(
                cx + (6 if right else -6), cy + 5, label, fontName="Helvetica", fontSize=6, fillColor=_NAVY, textAnchor="start" if right else "end"
            )
        )


def _speed_charts(data: PerformanceData, context: ReportContext) -> list[Drawing]:
    curves = data.envelope.curves
    top_speed = max(curve.speed_rpm[-1] for curve in curves)
    status = data.envelope.status
    charts = []
    for quantity, label, scale in (("torque", "Torque (N m)", 1.0), ("power", "Power (kW)", 1e-3)):
        values = [value * scale for curve in curves for value in (curve.torque_Nm if quantity == "torque" else curve.power_W)]
        chart = _Chart(
            f"{'Torque' if quantity == 'torque' else 'Power'} against speed",
            status,
            "Speed (rpm)",
            label,
            (0.0, top_speed),
            (0.0, max(values) * 1.05 if values else 1.0),
        )
        peak = data.curve("peak")
        if peak is not None:
            chart.line([peak.base_speed_rpm] * 2, [chart.y0, chart.y1], _SLATE, width=0.6, dash=(2, 2))
        for curve in curves:
            ys = [value * scale for value in (curve.torque_Nm if quantity == "torque" else curve.power_W)]
            chart.line(curve.speed_rpm, ys, _CURVE_COLORS[curve.limit])
            limit_A = data.limits.peak_current_A if curve.limit == "peak" else data.limits.continuous_current_A
            chart.legend(f"{curve.limit.capitalize()}, {_g(_shown(limit_A or 0, context))} {context.current_unit}", _CURVE_COLORS[curve.limit])
        solved = context.solved_point
        if solved is not None and quantity == "torque":
            chart.marker(solved.speed_rpm, solved.torque_Nm, f"Solved point, {_g(solved.torque_Nm)} N m")
        elif solved is not None:
            chart.marker(solved.speed_rpm, solved.torque_Nm * solved.speed_rpm * math.pi / 30 * scale, "Solved point")
        charts.append(chart.drawing)
    return charts


def efficiency_bands(values: Sequence[float]) -> tuple[float, float, float]:
    """The app's bands (frontend/src/public/performanceView.ts efficiencyBands): 2 points from a floor within 16 of the peak."""

    ordered = sorted(values)
    if not ordered:
        return 0.0, 100.0, 2.0
    low = ordered[int(math.floor(0.05 * (len(ordered) - 1)))]
    top = min(100.0, math.ceil(ordered[-1]))
    floor = max(0.0, top - 16, min(top - 10, math.floor(low / 2) * 2))
    return floor, top, 2.0


def _ramp(fraction: float) -> colors.Color:
    position = min(max(fraction, 0.0), 1.0) * (len(_EFFICIENCY_RAMP) - 1)
    index = min(int(position), len(_EFFICIENCY_RAMP) - 2)
    low, high = colors.HexColor(_EFFICIENCY_RAMP[index]), colors.HexColor(_EFFICIENCY_RAMP[index + 1])
    t = position - index
    return colors.Color(low.red + (high.red - low.red) * t, low.green + (high.green - low.green) * t, low.blue + (high.blue - low.blue) * t)


def _band_color(value: float, bands: tuple[float, float, float]) -> colors.Color:
    floor, top, step = bands
    banded = math.floor((max(value, floor) - floor) / step) * step + floor
    return _ramp((banded - floor) / max(top - floor, step))


def _efficiency_chart(data: PerformanceData, context: ReportContext) -> Drawing:
    efficiency = data.efficiency
    speeds, torques = efficiency.speed_rpm, efficiency.torque_Nm
    values = [value for row in efficiency.efficiency_pct for value in row if value is not None]
    bands = efficiency_bands(values)
    chart = _Chart(
        f"Efficiency map, {_CONTROL_LABEL[efficiency.control].split(' (')[0]}",
        efficiency.status,
        "Speed (rpm)",
        "Torque (N m)",
        (0.0, speeds[-1]),
        (0.0, torques[-1] * 1.05),
    )
    width = (chart.x(speeds[1]) - chart.x(speeds[0])) if len(speeds) > 1 else 1
    height = (chart.y(torques[1]) - chart.y(torques[0])) if len(torques) > 1 else 1
    for row_index, torque in enumerate(torques):
        for column, speed in enumerate(speeds):
            value = efficiency.efficiency_pct[row_index][column]
            if value is None:
                continue
            color = _band_color(value, bands)
            chart.drawing.add(
                Rect(chart.x(speed) - width / 2, chart.y(torque) - height / 2, width, height, fillColor=color, strokeColor=color, strokeWidth=0.1)
            )
    peak = data.curve("peak")
    if peak is not None:
        chart.line(peak.speed_rpm, peak.torque_Nm, _NAVY, width=1.0)
    if context.solved_point is not None:
        chart.marker(context.solved_point.speed_rpm, context.solved_point.torque_Nm, "Solved point")
    floor, top, step = bands
    x = chart.LEFT + 30 * mm
    y = chart.HEIGHT - chart.TOP + 1.6 * mm
    steps = int(round((top - floor) / step))
    for index in range(steps):
        start = floor + index * step
        chart.drawing.add(Rect(x, y, 6 * mm, 2.4 * mm, fillColor=_band_color(start, bands), strokeColor=None))
        if index in (0, steps - 1) or index % 2 == 0:
            chart.drawing.add(String(x, y + 3.2 * mm, f"{start:g}", fontName="Helvetica", fontSize=5.5, fillColor=_SLATE))
        x += 6 * mm
    chart.drawing.add(String(x + 1 * mm, y + 0.3 * mm, f"{top:g}% (bands of {step:g} points)", fontName="Helvetica", fontSize=6, fillColor=_SLATE))
    return chart.drawing


def _mtpa_chart(data: PerformanceData) -> Drawing:
    largest = data.mtpa[-1].current_peak_A if data.mtpa else 1.0
    chart = _Chart("MTPA trajectory in the id-iq plane (peak A)", data.envelope.status, "i_d (A)", "i_q (A)", (-largest, 0.0), (0.0, largest))
    angles = np.radians(np.linspace(0.0, 90.0, 61))
    chart.line(list(-largest * np.sin(angles)), list(largest * np.cos(angles)), _SLATE, width=0.6, dash=(2, 2))
    chart.line([row.i_d_A for row in data.mtpa], [row.i_q_A for row in data.mtpa], _CURVE_COLORS["peak"])
    chart.legend("MTPA", _CURVE_COLORS["peak"])
    chart.legend("Current limit", _SLATE)
    return chart.drawing


def _flux_chart(data: PerformanceData) -> Drawing:
    rows = data.mtpa
    currents = [row.current_peak_A for row in rows]
    values = [value for row in rows for value in (row.lambda_d_Wb * 1e3, row.lambda_q_Wb * 1e3)]
    chart = _Chart(
        "Flux linkage along the MTPA trajectory",
        _DQ_STATUS,
        "Phase current (A peak)",
        "Flux linkage (mWb)",
        (0.0, currents[-1] if currents else 1.0),
        (min(0.0, min(values, default=0.0)), max(values, default=1.0) * 1.05),
    )
    chart.line(currents, [row.lambda_d_Wb * 1e3 for row in rows], _LAMBDA_COLORS["d"])
    chart.line(currents, [row.lambda_q_Wb * 1e3 for row in rows], _LAMBDA_COLORS["q"])
    chart.legend("lambda_d", _LAMBDA_COLORS["d"])
    chart.legend("lambda_q", _LAMBDA_COLORS["q"])
    return chart.drawing


def _inductance_chart(data: PerformanceData) -> Drawing | None:
    rows = [row for row in data.inductance if row.l_d_H is not None or row.l_q_H is not None]
    if len(rows) < 2:
        return None
    values = [value * 1e3 for row in rows for value in (row.l_d_H, row.l_q_H) if value is not None]
    chart = _Chart(
        "Apparent inductance against current",
        _DQ_STATUS,
        "Phase current (A peak)",
        "Inductance (mH)",
        (0.0, rows[-1].current_peak_A),
        (0.0, max(values) * 1.1),
    )
    for name, read, color in (("Ld", lambda row: row.l_d_H, _LAMBDA_COLORS["d"]), ("Lq", lambda row: row.l_q_H, _LAMBDA_COLORS["q"])):
        pairs = [(row.current_peak_A, read(row) * 1e3) for row in rows if read(row) is not None]
        chart.line([x for x, _ in pairs], [y for _, y in pairs], color)
        chart.legend(name, color)
    return chart.drawing


# ── PDF ─────────────────────────────────────────────────────────────────────


def _table(header: Sequence[str], body: Sequence[Sequence[Any]], styles: Any) -> Table:
    data = [[_safe_paragraph(cell, styles["small"]) for cell in header]]
    data.extend([_safe_paragraph(cell, styles["body"]) for cell in line] for line in body)
    table = Table(data, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.4, _BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
            ]
        )
    )
    return table


def _selected(count: int, wanted: int) -> list[int]:
    if count <= wanted:
        return list(range(count))
    return sorted({round(index * (count - 1) / (wanted - 1)) for index in range(wanted)})


def _map_description(flux_map: FluxLinkageMap, context: ReportContext) -> str:
    grid = f", {context.map_preset} grid" if context.map_preset else ""
    derating = ", experimental derating" if context.magnet_temperature_derated else ""
    magnets = f"; magnets at {_g(flux_map.magnet_temperature_C)} degC{derating}" if flux_map.magnet_temperature_C is not None else ""
    return (
        f"{len(flux_map.current_peak_A)} currents up to {_g(flux_map.current_peak_A[-1])} A peak x {len(flux_map.gamma_deg)} angles "
        f"({_g(flux_map.gamma_deg[0])} to {_g(flux_map.gamma_deg[-1])} deg), {flux_map.rotor_positions} rotor positions each, "
        f"{flux_map.mesh_density} mesh{grid}; iron loss at {_g(flux_map.reference_speed_rpm)} rpm{magnets}"
    )


def build_performance_pdf(data: PerformanceData, context: ReportContext) -> bytes:
    """The Torque-speed tab's results as a PDF; the same numbers as build_performance_csv."""

    styles = _report_styles()
    buffer = io.BytesIO()
    name = context.design_name or "Unnamed design"
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=f"coilEM performance report - {name}",
        author="coilEM",
        subject="Torque-speed and efficiency from a flux-linkage map",
    )
    flux_map, limits = data.flux_map, data.limits

    def page_chrome(pdf: Any, doc: SimpleDocTemplate) -> None:
        pdf.saveState()
        pdf.setStrokeColor(_BORDER)
        pdf.setLineWidth(0.4)
        pdf.line(15 * mm, A4[1] - 12 * mm, A4[0] - 15 * mm, A4[1] - 12 * mm)
        pdf.setFont("Helvetica-Bold", 7)
        pdf.setFillColor(_NAVY)
        pdf.drawString(15 * mm, A4[1] - 9 * mm, "coilEM")
        pdf.setFont("Helvetica", 6.5)
        pdf.setFillColor(_SLATE)
        pdf.drawRightString(A4[0] - 15 * mm, A4[1] - 9 * mm, f"Performance report - map {flux_map.scope_key[:12]}")
        pdf.line(15 * mm, 11 * mm, A4[0] - 15 * mm, 11 * mm)
        pdf.drawString(15 * mm, 7 * mm, "Experimental: interpolated from a flux-linkage map, not yet compared with measured data")
        pdf.drawRightString(A4[0] - 15 * mm, 7 * mm, f"Page {doc.page}")
        pdf.restoreState()

    peak = data.curve("peak")
    best = data.best_efficiency_pct
    continuous = limits.continuous_current_A
    story: list[Any] = [
        Paragraph("Torque-speed and efficiency report", styles["title"]),
        _safe_paragraph(
            f"{name}. Built on demand from the design's flux-linkage map and the drive limits set on the Torque-speed tab, "
            "with the same calculation the tab uses. The run's own report records the single solved operating point.",
            styles["subtitle"],
        ),
        _section("Key results", styles),
        _key_value_table(
            [
                ("Peak torque", f"{_g(peak.torque_Nm[0])} N m" if peak else "-"),
                ("Base speed", f"{_g(peak.base_speed_rpm)} rpm" if peak else "-"),
                ("Peak power", f"{_g(peak.peak_power_W / 1000)} kW" if peak else "-"),
                ("Top speed reached", f"{_g(peak.max_speed_rpm)} rpm" if peak else "-"),
                ("Best efficiency", f"{best:.1f}%" if best is not None else "-"),
                *(
                    [("Solved point", f"{_g(context.solved_point.torque_Nm)} N m at {_g(context.solved_point.speed_rpm)} rpm")]
                    if context.solved_point
                    else []
                ),
            ],
            styles,
        ),
        _section("Status", styles),
        _safe_paragraph(
            "Qualified outputs pass a benchmark gate against a reference; experimental outputs have none yet.",
            styles["small"],
        ),
        Spacer(1, 1.5 * mm),
        _key_value_table(
            [(output, f"{status.capitalize()}: {reason}" if reason else status.capitalize())
             for _, output, status, reason in output_statuses(data, context)],
            styles,
        ),
        _section("Drive inputs", styles),
        _key_value_table(
            [
                ("Peak current", _current_text(limits.peak_current_A, context)),
                ("Continuous current", _current_text(continuous, context) if continuous is not None else "Not set"),
                ("DC bus", f"{_g(limits.dc_bus_V)} V, {_BUS_SOURCE[context.dc_bus_source]}"),
                (
                    "Phase voltage limit",
                    f"{_g(limits.modulation_index_max * limits.dc_bus_V / 2)} V peak (modulation index {_g(limits.modulation_index_max)})",
                ),
                ("Top speed", f"{_g(limits.max_speed_rpm)} rpm"),
                ("Drive control", _CONTROL_LABEL[data.control]),
                (
                    "Phase resistance",
                    f"{_g(data.phase_resistance_ohm)} ohm at {_g(data.winding_temperature_C)} degC, experimental"
                    if data.phase_resistance_ohm > 0 else "Not recorded: copper loss and IR drop are left out",
                ),
                ("Mechanical loss", f"{_g(data.mechanical_loss_W)} W"),
                ("Flux-linkage map", _map_description(flux_map, context)),
                ("Map scope key", flux_map.scope_key),
                ("coilEM", application_commit()),
            ],
            styles,
        ),
    ]
    charts = _speed_charts(data, context)
    story.extend([KeepTogether([_section("Torque and power against speed", styles), charts[0]]), Spacer(1, 2 * mm), charts[1]])
    if peak is not None:
        indices = _selected(len(peak.speed_rpm), 12)
        body = []
        for index in indices:
            current = math.hypot(peak.i_d_A[index], peak.i_q_A[index])
            body.append(
                [
                    _g(peak.speed_rpm[index]),
                    _g(peak.torque_Nm[index]),
                    _g(peak.power_W[index] / 1000),
                    _g(_shown(current, context)),
                    _g(math.degrees(math.atan2(-peak.i_d_A[index], peak.i_q_A[index])) if current > 0 else 0.0, 3),
                    _g(peak.phase_voltage_peak_V[index]),
                    _REGION_LABEL[peak.region[index]],
                ]
            )
        story.append(
            KeepTogether(
                [
                    Paragraph("Peak curve at selected speeds (every sample is in the performance CSV)", styles["small"]),
                    _table(
                        [
                            "Speed (rpm)",
                            "Torque (N m)",
                            "Power (kW)",
                            f"Current ({context.current_unit})",
                            "Angle (deg)",
                            "Voltage (V peak)",
                            "Region",
                        ],
                        body,
                        styles,
                    ),
                ]
            )
        )
    story.extend(
        [
            KeepTogether([_section("Efficiency map", styles), _efficiency_chart(data, context)]),
            Paragraph(
                "Efficiency = shaft power / input power, with shaft power = T x omega - iron loss - mechanical loss and input power = "
                "T x omega + copper loss. Cells above the peak curve are outside the drive's reach. The current and angle of every cell "
                "are in the performance CSV.",
                styles["small"],
            ),
            KeepTogether([_section("MTPA trajectory and flux linkage", styles), _mtpa_chart(data)]),
            Spacer(1, 2 * mm),
            _flux_chart(data),
        ]
    )
    inductance_chart = _inductance_chart(data)
    if inductance_chart is not None:
        story.append(KeepTogether([_section("Apparent inductance", styles), inductance_chart]))
    if data.inductance:
        story.append(
            _table(
                ["Current (A peak)", f"Current ({context.current_unit})", "Ld (mH)", "Lq (mH)"],
                [
                    [
                        _g(row.current_peak_A),
                        _g(_shown(row.current_peak_A, context)),
                        _g(row.l_d_H * 1e3) if row.l_d_H is not None else "-",
                        _g(row.l_q_H * 1e3) if row.l_q_H is not None else "-",
                    ]
                    for row in data.inductance
                ],
                styles,
            )
        )
    notes = [_safe_paragraph(f"- {note}", styles["body"]) for note in _notes(data)]
    story.extend([KeepTogether([_section("Notes", styles), notes[0]]), *notes[1:]])
    limitations = [_safe_paragraph(f"- {limitation}", styles["body"]) for limitation in _LIMITATIONS]
    story.extend([KeepTogether([_section("Known limitations", styles), limitations[0]]), *limitations[1:]])
    document.build(story, onFirstPage=page_chrome, onLaterPages=page_chrome, canvasmaker=_InvariantCanvas)
    return buffer.getvalue()
