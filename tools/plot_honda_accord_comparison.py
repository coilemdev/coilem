"""Plot coilEM's frozen 2005 Honda Accord prediction against ORNL's measurements (#92).

Reads comparison.json (written by tools/honda_accord_comparison.py) and writes static SVG charts:
no-load back-EMF against speed, and locked-rotor torque (peaks against current, curves against
position). coilEM is a solid blue line, ORNL a set of orange markers.

    python tools/plot_honda_accord_comparison.py docs/hardware-validation/honda-accord-2005/first-comparison
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.plot_ornl_prius_comparison import COILEM, INK, ORNL, SURFACE, panel, svg, text


def legend(x, y, data):
    # The first comparison emulated the #91 tooth coils; later runs wind the motor as built.
    winding = "#91 fix emulated" if "#91 emulated" in data["description"] else "wound as built"
    return (
        f'<line x1="{x}" y1="{y - 4}" x2="{x + 22}" y2="{y - 4}" stroke="{COILEM}" stroke-width="2"/>'
        + text(x + 28, y, f"coilEM prediction (frozen inputs, N35 assumed, {winding})", 12, INK)
        + f'<circle cx="{x + 470}" cy="{y - 4}" r="4.5" fill="{ORNL}" stroke="{SURFACE}" stroke-width="2"/>'
        + text(x + 480, y, "ORNL measured (2005 Accord motor)", 12, INK)
    )


def back_emf_chart(data):
    rows = data["back_emf"]["rows"]
    speeds = [r["motor_shaft_rpm"] for r in rows]
    body = legend(20, 74, data) + panel(10, 86, 880, 300, "No-load back-EMF, line-to-neutral rms", "Motor speed (rpm)", "Volts", (0, 6200), [
        ("coilEM", speeds, [r["predicted_ln_rms_V"] for r in rows], "line"),
        ("ORNL", speeds, [r["measured_ln_rms_V"] for r in rows], "markers"),
    ], x_ticks=[0, 1000, 2000, 3000, 4000, 5000, 6000])
    mean = data["back_emf"]["error_pct"]["mean"]
    return svg(900, 400, "No-load back-EMF: coilEM vs ORNL hardware measurement",
               f"2005 Accord IMA motor · 24 slots / 16 poles, concentrated · coilEM mean {mean:+.1f}% over 18 speeds · "
               "ORNL/TM-2006/535 Table 3.1", body)


def torque_chart(data):
    lr = data["locked_rotor"]
    peaks = lr["peak_by_current"]
    body = legend(20, 74, data)
    body += panel(10, 86, 880, 300, "Peak locked-rotor torque", "DC current Ia (A)", "Torque (N·m)", (0, 240), [
        ("coilEM", [p["current_A"] for p in peaks], [p["coilem_peak_Nm"] for p in peaks], "line"),
        ("ORNL", [p["current_A"] for p in peaks], [p["ornl_peak_Nm"] for p in peaks], "markers"),
    ], x_ticks=[0, 25, 50, 75, 100, 125, 150, 175, 200, 225])
    ornl = {p["current_A"]: p for p in peaks}
    for (x0, y0), current in zip([(10, 400), (455, 400)], ("50", "225")):
        curve = lr["curves"][current]
        peak = ornl[int(current)]
        body += panel(x0, y0, 440, 300, f"Locked rotor, {current} A", "Electrical position δ (deg)", "Torque (N·m)", (0, 180), [
                          ("coilEM", [c["delta_deg"] for c in curve], [c["torque_Nm"] for c in curve], "line"),
                          ("ORNL peak", [peak["coilem_peak_delta_deg"]], [peak["ornl_peak_Nm"]], "markers"),
                      ], x_ticks=[0, 30, 60, 90, 120, 150, 180])
    mean = lr["error_pct"]["mean"]
    return svg(900, 720, "Locked-rotor torque: coilEM vs ORNL hardware measurement",
               f"DC currents Ia, −Ia/2, −Ia/2 · peak over position, coilEM mean {mean:+.1f}% over 9 currents · lower panels: ORNL's peak "
               "(Table 3.2 gives no position) at coilEM's peak position", body)


def main():
    folder = Path(sys.argv[1])
    data = json.loads((folder / "comparison.json").read_text(encoding="utf-8"))
    (folder / "back-emf.svg").write_text(back_emf_chart(data), encoding="utf-8", newline="\n")
    (folder / "locked-rotor-torque.svg").write_text(torque_chart(data), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
