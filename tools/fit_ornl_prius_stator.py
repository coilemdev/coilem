"""Map the ORNL 2004 Prius stator slot onto coilEM's stator parameters (#82).

Reads the black stator vector paths of ORNL/TM-2005/33 Fig. 21 from the S5 PDF
(checked against its recorded SHA-256), in the drawing frame fitted by
tools/fit_ornl_prius_holem50.py: centre offset and plot stretch. Every one of
the 48 slots is measured between both walls, so the width does not depend on
locating the slot centre exactly. coilEM's tapered slot with a tooth shoe is
then fitted to the measured walls, with the shoe height and the slot mouth at
the drawing's stated callouts.

    python tools/fit_ornl_prius_stator.py osti-885987.pdf docs/hardware-validation/ornl-prius-2004/stator-slot-mapping.json

Needs pypdf (a development dependency).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from tools.fit_ornl_prius_holem50 import ROOT, calibrate, figure_segments, levenberg_marquardt

FOLDER = ROOT / "docs/hardware-validation/ornl-prius-2004"
BASE_DESIGN = ROOT / "benchmarks/main-20261009-bad71d9/fixtures/ornl_prius_2004_ipm.json"
SLOTS = 48
PITCH_DEG = 360.0 / SLOTS
IN = 25.4
# Fig. 21 callouts. Their association with these slot features is read from the figure.
CALLOUTS_MM = {"mouth": 0.076 * IN, "width_above_tips": 0.124 * IN, "tip_height": 0.040 * IN, "bottom_round_diameter": 0.222 * IN}
# Stated and derived-from-stated values, as input-provenance.json rounds them (G04, G05, G15).
STATED = {"OD_mm": 269.24, "ID_mm": 161.93, "yoke_thickness_mm": 20.13}
# Radial stations (distance from the axis along the slot centreline, mm).
STATIONS = (81.1, 81.6, 82.6, 83.1, 84.2, 86.2, 89.2, 92.2, 95.2, 98.2, 101.2, 104.2, 107.2, 110.2, 111.2, 112.2, 113.2)
WALL_STATIONS = tuple(x for x in STATIONS if 82.5 < x < 110.5)  # straight walls, above the tips and before the round bottom


def drawing_points(pdf: Path, step_mm: float = 0.05) -> np.ndarray:
    """Stator outline points in mm, in the rotor-fit drawing frame."""

    calibration = calibrate(figure_segments(pdf, "blue"))
    frame = json.loads((FOLDER / "holem50-mapping.json").read_text(encoding="utf-8"))["recommended"]["fit"]["drawing"]
    ratio = frame["stretch_x_over_y"]
    stretch = (ratio - 1) / (ratio + 1)
    scale = 25.4 / calibration["pt_per_inch"]
    origin = np.array([calibration["centre_x_pt"], calibration["centre_y_pt"]])
    points = []
    for a, b in figure_segments(pdf, "black"):
        a, b = (np.array(a) - origin) * scale, (np.array(b) - origin) * scale
        n = max(2, math.ceil(np.hypot(*(b - a)) / step_mm) + 1)
        points.extend(a + t * (b - a) for t in np.linspace(0.0, 1.0, n))
    p = (np.array(points) - np.array(frame["centre_offset_mm"])) / np.array([1.0 + stretch, 1.0 - stretch])
    r = np.hypot(*p.T)
    return p[(r > 80.0) & (r < 136.0)]


def slot_widths(points: np.ndarray, centres_deg: np.ndarray) -> dict[float, list[float]]:
    """Width between the two walls of every slot at each station."""

    theta = np.degrees(np.arctan2(points[:, 1], points[:, 0]))
    delta = (theta[:, None] - centres_deg[None, :] + 180.0) % 360.0 - 180.0
    slot = np.abs(delta).argmin(axis=1)
    d = np.radians(delta[np.arange(len(points)), slot])
    r = np.hypot(*points.T)
    x, y = r * np.cos(d), r * np.sin(d)
    widths = {}
    for station in STATIONS:
        values = []
        for k in range(len(centres_deg)):
            m = (slot == k) & (np.abs(x - station) < 0.2)
            left, right = y[m & (y < 0)], y[m & (y > 0)]
            if len(left) and len(right):
                values.append(float(right.min() - left.max()))
        widths[station] = values
    return widths


def drawing_slot_centres(points: np.ndarray) -> np.ndarray:
    """Slot centres: the tooth-tip arcs at the bore are centred between slots."""

    r = np.hypot(*points.T)
    tips = np.degrees(np.arctan2(points[r < 81.6, 1], points[r < 81.6, 0]))
    tooth = math.degrees(np.angle(np.mean(np.exp(1j * np.radians(tips) * SLOTS)))) / SLOTS
    return (tooth + PITCH_DEG / 2 + PITCH_DEG * np.arange(SLOTS)) % 360.0


def coilem_widths(stator: dict) -> dict[float, float]:
    """Median drawn slot width of coilEM's stator at each station."""

    from backend.geometry_drawer import compute_geometry
    from backend.geometry_ir import build_geometry_ir
    from backend.models import MotorConfig

    design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))
    design["stator"].update(stator)
    config = MotorConfig.model_validate(design)
    points = []
    for region in build_geometry_ir(config).regions:
        if region.kind != "StatorTooth":
            continue
        for loop in region.loops:
            for segment in loop.segments:
                if segment.kind == "line":
                    a = np.array([segment.start.x_mm, segment.start.y_mm])
                    b = np.array([segment.end.x_mm, segment.end.y_mm])
                    n = max(2, math.ceil(np.hypot(*(b - a)) / 0.02) + 1)
                    points.extend(a + t * (b - a) for t in np.linspace(0.0, 1.0, n))
    centres = np.array([math.degrees(s.center_angle_rad) for s in compute_geometry(config).slots])
    return {station: float(np.median(v)) if v else float("nan") for station, v in slot_widths(np.array(points), centres).items()}


def residuals(stator: dict, measured: dict[float, float], stations=STATIONS) -> dict:
    model = coilem_widths(stator)
    diff = {s: model[s] - measured[s] for s in stations if s in measured and math.isfinite(model[s])}
    values = np.array(list(diff.values()))
    return {"rms_mm": round(float(np.sqrt((values**2).mean())), 3), "max_mm": round(float(np.abs(values).max()), 3),
            "per_station_mm": {f"{s:g}": round(v, 3) for s, v in diff.items()}}


def shoe(slot_opening: float, tooth_width: float) -> dict:
    return {
        **STATED,
        "slot_opening_mm": slot_opening,
        "tooth_shoe_enabled": True,
        "tooth_shoe_height_mm": round(CALLOUTS_MM["tip_height"], 2),
        "tooth_shoe_overhang_mm": (slot_opening - CALLOUTS_MM["mouth"]) / 2,
        "tooth_width_mm": tooth_width,
    }


def main() -> None:
    pdf, out = Path(sys.argv[1]), Path(sys.argv[2])
    points = drawing_points(pdf)
    per_slot = slot_widths(points, drawing_slot_centres(points))
    measured = {s: float(np.median(v)) for s, v in per_slot.items()}
    walls = {s: measured[s] for s in WALL_STATIONS}

    def fun(x):
        model = coilem_widths(shoe(float(x[0]), float(x[1])))
        return np.array([model[s] - walls[s] for s in WALL_STATIONS])

    fitted = levenberg_marquardt(fun, [3.15, 9.35], step=1e-4)
    opening, tooth = round(float(fitted[0]), 2), round(float(fitted[1]), 2)
    recommended = shoe(opening, tooth)
    recommended["tooth_shoe_overhang_mm"] = round(recommended["tooth_shoe_overhang_mm"], 2)
    callouts = shoe(round(CALLOUTS_MM["width_above_tips"], 2), 9.35)
    callouts["tooth_shoe_overhang_mm"] = round(callouts["tooth_shoe_overhang_mm"], 2)
    existing = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))["stator"]
    result = {
        "description": (
            "coilEM stator slot parameters fitted to the ORNL 2004 Prius stator lamination (#82). "
            "Inferred from a figure where not stated."
        ),
        "source": {"id": "S5", "report": "ORNL/TM-2005/33", "figure": "Fig. 21, p.25 (PDF 32)", "paths": "black stator vector paths"},
        "tool": "tools/fit_ornl_prius_stator.py",
        "drawing_frame": "holem50-mapping.json recommended.fit.drawing (centre offset and plot stretch)",
        "callouts_mm": {k: round(v, 3) for k, v in CALLOUTS_MM.items()},
        "measured_slot_width_mm": {
            f"{s:g}": {"median": round(measured[s], 3), "p10": round(float(np.percentile(v, 10)), 3), "p90": round(float(np.percentile(v, 90)), 3),
                       "slots": len(v)}
            for s, v in per_slot.items()
        },
        "candidates": {
            "existing_fixture": {"stator": existing, "fit": residuals(existing, measured, WALL_STATIONS)},
            "callouts": {"stator": callouts, "fit": residuals(callouts, measured, WALL_STATIONS)},
            "fitted_to_walls": {"stator": recommended, "fit": residuals(recommended, measured, WALL_STATIONS)},
        },
        "recommended": "fitted_to_walls",
    }
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    for name, candidate in result["candidates"].items():
        print(f"{name}: rms {candidate['fit']['rms_mm']} max {candidate['fit']['max_mm']} mm")
    print("recommended:", recommended)


if __name__ == "__main__":
    main()
