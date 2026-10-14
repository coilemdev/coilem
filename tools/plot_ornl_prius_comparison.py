"""Plot coilEM's frozen Prius prediction against ORNL's hardware measurements.

Reads comparison.json (written by tools/ornl_prius_comparison.py) and writes
static SVG charts: no-load line-to-line Back-EMF against speed, and
locked-rotor torque against electrical position. coilEM is a solid blue line,
ORNL a set of orange markers; every panel starts its value axis at zero.

    python tools/plot_ornl_prius_comparison.py docs/hardware-validation/ornl-prius-2004/first-comparison
"""

from __future__ import annotations

import html
import json
import math
import sys
from pathlib import Path

SURFACE, INK, INK_2, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1", "#8a8985"
COILEM, ORNL = "#2a78d6", "#eb6834"  # categorical slots 1 and 2, validated together
FONT = "font-family=\"-apple-system,Segoe UI,Helvetica,Arial,sans-serif\""


def nice_ticks(lo, hi, count=5):
    span = max(hi - lo, 1e-9)
    raw = span / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = min((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw), default=magnitude * 10)
    start = math.floor(lo / step) * step
    ticks = []
    value = start
    while value <= hi + step * 1e-6:
        ticks.append(round(value, 10))
        value += step
    return ticks


def text(x, y, value, size=12, color=INK_2, anchor="start", weight="normal"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" text-anchor="{anchor}" '
            f'font-weight="{weight}" {FONT}>{html.escape(str(value))}</text>')


def panel(x0, y0, width, height, title, x_label, y_label, x_range, series, x_ticks=None):
    """One chart panel: series = [(label, xs, ys, kind)] with kind 'line' or 'markers'."""

    values = [v for _, _, ys, _ in series for v in ys]
    y_lo = min(0.0, min(values))
    y_hi = max(values) * 1.08 if max(values) > 0 else 1.0
    y_ticks = nice_ticks(y_lo, y_hi)
    y_lo, y_hi = min(y_ticks[0], y_lo), max(y_ticks[-1], y_hi)
    left, right, top, bottom = 58, 18, 34, 40
    pw, ph = width - left - right, height - top - bottom

    def sx(v):
        return x0 + left + (v - x_range[0]) / (x_range[1] - x_range[0]) * pw

    def sy(v):
        return y0 + top + (y_hi - v) / (y_hi - y_lo) * ph

    out = [text(x0 + left, y0 + 18, title, 13, INK, weight="600")]
    for tick in y_ticks:
        y = sy(tick)
        stroke = AXIS if tick == 0 else GRID
        out.append(f'<line x1="{x0 + left}" y1="{y:.1f}" x2="{x0 + left + pw}" y2="{y:.1f}" stroke="{stroke}" stroke-width="1"/>')
        out.append(text(x0 + left - 8, y + 4, f"{tick:g}", 11, INK_2, "end"))
    for tick in x_ticks or nice_ticks(*x_range):
        if x_range[0] <= tick <= x_range[1]:
            out.append(text(sx(tick), y0 + top + ph + 16, f"{tick:g}", 11, INK_2, "middle"))
    out.append(text(x0 + left + pw / 2, y0 + height - 6, x_label, 11, INK_2, "middle"))
    out.append(f'<text transform="translate({x0 + 14},{y0 + top + ph / 2}) rotate(-90)" font-size="11" fill="{INK_2}" text-anchor="middle" {FONT}>'
               f"{html.escape(y_label)}</text>")
    ends = {}
    for label, xs, ys, kind in series:
        if kind == "line":
            points = " ".join(f"{sx(a):.1f},{sy(b):.1f}" for a, b in zip(xs, ys))
            out.append(f'<polyline points="{points}" fill="none" stroke="{COILEM}" stroke-width="2" stroke-linejoin="round"/>')
        else:
            for a, b in zip(xs, ys):
                out.append(f'<circle cx="{sx(a):.1f}" cy="{sy(b):.1f}" r="4.5" fill="{ORNL}" stroke="{SURFACE}" stroke-width="2"/>')
        # Direct label at the series' highest point, the one least likely to collide.
        peak = max(range(len(ys)), key=lambda i: ys[i])
        ends[label] = (sx(xs[peak]), sy(ys[peak]))
    if len(ends) == 2:
        (upper, (ux, uy)), (lower, (lx, ly)) = sorted(ends.items(), key=lambda item: item[1][1])
        out.append(text(ux - 8, uy - 9, upper, 11, INK, "end"))
        out.append(text(lx - 8, ly + 18, lower, 11, INK, "end"))
    return "".join(out)


def legend(x, y):
    return (
        f'<line x1="{x}" y1="{y - 4}" x2="{x + 22}" y2="{y - 4}" stroke="{COILEM}" stroke-width="2"/>'
        + text(x + 28, y, "coilEM prediction (frozen inputs)", 12, INK)
        + f'<circle cx="{x + 262}" cy="{y - 4}" r="4.5" fill="{ORNL}" stroke="{SURFACE}" stroke-width="2"/>'
        + text(x + 272, y, "ORNL measured (2004 Prius motor)", 12, INK)
    )


def svg(width, height, title, subtitle, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
        f'aria-label="{html.escape(title)}"><title>{html.escape(title)}</title>'
        f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>'
        + text(20, 28, title, 16, INK, weight="600")
        + text(20, 48, subtitle, 12, INK_2)
        + body
        + "</svg>\n"
    )


def back_emf_chart(data):
    rows = data["back_emf"]["rows"]
    speeds = [r["motor_shaft_rpm"] for r in rows]
    width, height = 900, 400
    body = legend(20, 74)
    for i, (key, label) in enumerate((("rms", "Line-to-line RMS"), ("peak", "Line-to-line peak"))):
        body += panel(10 + i * 445, 86, 440, 300, label, "Motor speed (rpm)", "Volts", (0, 6200), [
            ("coilEM", speeds, [r[f"predicted_ll_{key}_V"] for r in rows], "line"),
            ("ORNL", speeds, [r[f"measured_ll_{key}_V"] for r in rows], "markers"),
        ], x_ticks=[0, 1000, 2000, 3000, 4000, 5000, 6000])
    mean = data["back_emf"]["rms_error_pct"]["mean"]
    return svg(width, height, "No-load back-EMF: coilEM vs ORNL hardware measurement",
               f"2004 Prius MG2 · no load, oil 25 °C · coilEM above ORNL at every speed (RMS mean {mean:+.0f}%) · ORNL/TM-2006/423 Table 3.4", body)


def torque_chart(data):
    rows = data["locked_rotor"]["rows"]
    currents = data["locked_rotor"]["currents_A"]
    width, height = 900, 720
    body = legend(20, 74)
    shown = [c for c in (50, 150, 250) if c in currents]
    positions = [(10, 86), (455, 86), (10, 400), (455, 400)]
    for (x0, y0), current in zip(positions, shown):
        deltas = [r["delta_deg"] for r in rows]
        body += panel(x0, y0, 440, 300, f"Locked rotor, {current:g} A", "Electrical position δ (deg)", "Torque (N·m)", (0, 180), [
            ("coilEM", deltas, [r["coilem_Nm"][str(current)] for r in rows], "line"),
            ("ORNL", deltas, [r["ornl_Nm"][str(current)] for r in rows], "markers"),
        ], x_ticks=[0, 30, 60, 90, 120, 150, 180])
    peaks = data["locked_rotor"]["peak_by_current"]
    body += panel(*positions[3], 440, 300, "Peak locked-rotor torque", "Phase A current Ia (A)", "Torque (N·m)", (0, 270), [
        ("coilEM", [p["current_A"] for p in peaks], [p["coilem_peak_Nm"] for p in peaks], "line"),
        ("ORNL", [p["current_A"] for p in peaks], [p["ornl_peak_Nm"] for p in peaks], "markers"),
    ], x_ticks=[0, 50, 100, 150, 200, 250])
    return svg(width, height, "Locked-rotor torque: coilEM vs ORNL hardware measurement",
               "2004 Prius MG2 · DC currents Ia, −Ia/2, −Ia/2 · δ = current angle from the rotor d-axis · ORNL/TM-2006/423 Table 3.2", body)


def main():
    folder = Path(sys.argv[1])
    data = json.loads((folder / "comparison.json").read_text(encoding="utf-8"))
    (folder / "back-emf.svg").write_text(back_emf_chart(data), encoding="utf-8")
    if data.get("locked_rotor"):
        (folder / "locked-rotor-torque.svg").write_text(torque_chart(data), encoding="utf-8")


if __name__ == "__main__":
    main()
