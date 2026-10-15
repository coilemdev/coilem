"""Portable report artifacts with explicit reference provenance and phase labels."""

from __future__ import annotations

import csv
import html
import json
import math
import textwrap
from collections import Counter

from tools.benchmark_suite import PHASE_LABELS
from tools.benchmark_suite.contract import ROOT, read, sha, write

PLANNED_COVERAGE = {
    "ornl_prius_2004_ipm": {
        "label": "Planned coverage (not yet supported)",
        "reason": "The Prius fixture uses HoleM50 rotor geometry; the public API currently accepts flat-buried and V-shape IPM only.",
        "next_step": "Qualify the Prius geometry, native mesh and field solves against matched FEMM evidence before enabling public support.",
    },
}


EXPERIMENTAL_ROTOR_NOTE = "Experimental rotor path (#70): not public support; results carry no qualification claim."
HARDWARE_COLUMNS = ("Speed (rpm)", "Measured LL RMS (V)", "Predicted LL RMS (V)", "RMS error", "Measured LL peak (V)",
                    "Predicted LL peak (V)", "Peak error")


def hardware_table(row):
    """Rows of the exploratory hardware correlation, or None when the case has none."""
    comparison = row.get("hardware_comparison")
    if not comparison:
        return None
    if comparison.get("status") != "NO_VERDICT":
        return [["Hardware correlation", comparison.get("reason", comparison.get("status", ""))]]
    return [
        [f"{r['motor_shaft_rpm']:g}", f"{r['measured_ll_rms_V']:g}", f"{r['predicted_ll_rms_V']:.1f}", f"{r['rms_error_pct']:+.1f}%",
         f"{r['measured_ll_peak_V']:g}", f"{r['predicted_ll_peak_V']:.1f}", f"{r['peak_error_pct']:+.1f}%"]
        for r in comparison["rows"]
    ]


def hardware_html(row):
    rows = hardware_table(row)
    if rows is None:
        return ""
    comparison = row["hardware_comparison"]
    if comparison.get("status") != "NO_VERDICT":
        return f"<p>Hardware correlation: {html.escape(rows[0][1])}</p>"
    head = "".join(f"<th>{html.escape(c)}</th>" for c in HARDWARE_COLUMNS)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in rows)
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in comparison["conversion"] + comparison["allowances"])
    return (
        f"<h4>{html.escape(comparison['label'])}</h4><p>Measured: {html.escape(comparison['reference']['label'])}.</p>"
        f"<table><tr>{head}</tr>{body}</table><ul>{notes}</ul>"
    )


def hardware_markdown(row):
    rows = hardware_table(row)
    if rows is None:
        return []
    comparison = row["hardware_comparison"]
    if comparison.get("status") != "NO_VERDICT":
        return ["", f"Hardware correlation: {rows[0][1]}"]
    return [
        "",
        f"{comparison['label']}. Measured: {comparison['reference']['label']}.",
        "",
        "| " + " | ".join(HARDWARE_COLUMNS) + " |",
        "|" + "---|" * len(HARDWARE_COLUMNS),
        *("| " + " | ".join(r) + " |" for r in rows),
    ]


def coverage_plan(row):
    """A roadmap label applies only to an explicitly planned, rejected case."""
    return PLANNED_COVERAGE.get(row["id"]) if row["status"] == "UNSUPPORTED" else None


def display_outcome(row):
    plan = coverage_plan(row)
    return plan["label"] if plan else row["status"]


def phase_outcomes(rows):
    return ", ".join(f"{n} {label}" for label, n in sorted(Counter(display_outcome(row) for row in rows).items()))


def evaluation_note(manifest):
    contract = manifest.get("comparison", {}).get("evaluation_contract")
    if not contract:
        return ""
    return (
        f"Evaluation protocol {contract['version']}: {contract['current_angle_convention']}. "
        f"Measured protocol remains {contract['measured_protocol_version']}. "
        "Post hoc angle-contract reconciliation; historical FAIL evaluations are retained in JSON. "
        "Scientific review and release qualification remain separate."
    )


def display_overall(status, rows):
    rejected = [row for row in rows if row["status"] == "UNSUPPORTED"]
    if status == "PASS_WITH_UNSUPPORTED" and rejected and all(coverage_plan(row) for row in rejected):
        if len(rejected) == len(rows):
            return "Planned coverage (not yet supported)"
        return "PASS with planned coverage (not yet supported)"
    return status


def phase_display_status(outcomes):
    """Presentation only: all PASS green, majority FAIL red, mixed/partial yellow."""
    total = sum(outcomes.values())
    if total and outcomes.get("PASS", 0) == total:
        return "PASS"
    if total and outcomes.get("FAIL", 0) > total / 2:
        return "FAIL"
    return "YELLOW"


def plot(title, x, series, x_unit="°"):
    """Native orange first; dashed FEMM blue last exposes orange through its gaps."""
    if not x or not series:
        return ""
    prepared = [
        (label, x if isinstance(ys, list) else ys["angles"], ys if isinstance(ys, list) else ys["values"], color, dashed)
        for label, ys, color, dashed in series
    ]
    values = [v for _, _, ys, _, _ in prepared for v in ys]
    angles = [a for _, xs, _, _, _ in prepared for a in xs]
    if not values or not all(math.isfinite(v) for v in [*angles, *values]):
        return ""
    lo, hi = min(values), max(values)
    pad = max((hi - lo) * 0.1, abs(hi) * 0.02, 1e-6)
    lo, hi = lo - pad, hi + pad
    xlo, xhi = min(angles), max(angles)
    output = [
        f'<svg role="img" aria-label="{html.escape(title)}" viewBox="0 0 540 230"><title>{html.escape(title)}</title>',
    ]
    for index, line in enumerate(textwrap.wrap(title, width=70)):
        output.append(f'<text x="45" y="{18 + index * 13}" font-size="12">{html.escape(line)}</text>')
    for i in range(4):
        y = 38 + i * 43
        output.append(f'<path d="M45 {y}H525" stroke="#dce3ed"/><text x="2" y="{y + 4}" font-size="10">{hi - (hi - lo) * i / 3:.3g}</text>')
    for label, xs, ys, color, dashed in prepared:
        if len(ys) != len(xs):
            continue
        points = " ".join(
            f"{45 + (a - xlo) / max(xhi - xlo, 1e-12) * 480:.2f},{38 + (hi - b) / (hi - lo) * 129:.2f}" for a, b in zip(xs, ys, strict=True)
        )
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        output.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"{dash}/>')
    output.append(f'<text x="45" y="185">{xlo:g}{x_unit}</text><text x="{490 - 6 * (len(x_unit) - 1)}" y="185">{xhi:g}{x_unit}</text>')
    for i, (label, _, color, dashed) in enumerate(series):
        pos = 15 + i * 170
        output.append(
            f'<text x="{pos}" y="{204 + (i // 3) * 18}" fill="{color}" font-size="11">{html.escape(label)} {"dashed" if dashed else "solid"}</text>'
        )
    return "".join(output) + "</svg>"


def charts(row):
    if row["status"] in ("ERROR", "INCOMPLETE", "UNSUPPORTED"):
        return ""
    data = row.get("measurements", {})
    reference = row.get("reference")
    if row["phase"] != "D":
        native = data.get("native")
        if not native:
            return ""
        out = []
        for key, field, title in (("torque_waveform", "torque_Nm", "Torque (N m)"), ("back_emf_waveform", "phase_a_V", "Phase A Back-EMF (V)")):
            wave = native.get(key) or {}
            x, y = wave.get("electrical_angle_deg", []), wave.get(field, [])
            series = [("Coilem", y, "#d66a00", False)]
            if reference and (reference.get(key) or {}).get("electrical_angle_deg") == x:
                ry = reference[key][field]
                series.append(("Frozen FEMM", ry, "#245dcc", True))
                out.append(plot(title + " residual: Coilem − FEMM", x, [("Residual", [a - b for a, b in zip(y, ry, strict=True)], "#7653a2", False)]))
            out.append(plot(title, x, series))
        hardware = row.get("hardware_comparison") or {}
        if hardware.get("status") == "NO_VERDICT":
            speeds = [r["motor_shaft_rpm"] for r in hardware["rows"]]
            out.append(
                plot(
                    "No-load line-to-line Back-EMF (V) against speed: ORNL measured and Coilem predicted",
                    speeds,
                    [
                        ("Coilem RMS", [r["predicted_ll_rms_V"] for r in hardware["rows"]], "#d66a00", False),
                        ("ORNL RMS", [r["measured_ll_rms_V"] for r in hardware["rows"]], "#245dcc", True),
                        ("Coilem peak", [r["predicted_ll_peak_V"] for r in hardware["rows"]], "#8a4500", False),
                        ("ORNL peak", [r["measured_ll_peak_V"] for r in hardware["rows"]], "#12357a", True),
                    ],
                    x_unit=" rpm",
                )
            )
        return "".join(out)
    standard = data.get("native-standard")
    if not standard:
        return ""
    x, y = standard["electrical_angle_deg"], standard["torque_Nm"]
    series = [("Coilem standard", y, "#d66a00", False)]
    if reference:
        series.append(("Frozen FEMM", reference["torque_Nm"], "#245dcc", True))
    out = [plot("BLDC torque (N m)", x, series)]
    if reference and reference["electrical_angle_deg"] == x:
        out.append(
            plot(
                "Torque residual: Coilem − FEMM (N m)",
                x,
                [("Residual", [a - b for a, b in zip(y, reference["torque_Nm"], strict=True)], "#7653a2", False)],
            )
        )
    currents = standard["phase_current_waveform"]
    out.append(
        plot(
            "Commanded phase currents / commutation (A)",
            currents["electrical_angle_deg"],
            [
                (f"Phase {p.upper()}", currents[f"phase_{p}_A"], color, False)
                for p, color in zip("abc", ("#d66a00", "#245dcc", "#29945d"), strict=True)
            ],
        )
    )
    if reference:
        ref_current = reference["phase_current_waveform"]
        out.append(
            plot(
                "Phase A current: native / frozen reference (A)",
                x,
                [("Coilem", currents["phase_a_A"], "#d66a00", False), ("Frozen FEMM", ref_current["phase_a_A"], "#245dcc", True)],
            )
        )
    fine = data.get("native-fine")
    if fine:
        out.append(
            plot(
                "Angular convergence: normal spatial mesh (N m)",
                x,
                [
                    ("Standard", y, "#d66a00", False),
                    ("Fine angular", {"angles": fine["electrical_angle_deg"], "values": fine["torque_Nm"]}, "#29945d", True),
                ],
            )
        )
    low = data.get("analytical")
    if low and low.get("back_emf_waveform"):
        emf, current = low["back_emf_waveform"], low["phase_current_waveform"]
        omega = row["protocol"]["matrix"]["low_current_power_discriminator"]["rated_speed_rpm"] * 2 * math.pi / 60
        power_torque = [
            sum(emf[f"phase_{p}_V"][i] * current[f"phase_{p}_A"][i] for p in "abc") / omega for i in range(len(low["electrical_angle_deg"]))
        ]
        out.append(
            plot(
                "Low-current power / speed and field torque (N m); gate uses cycle means",
                low["electrical_angle_deg"],
                [("Field torque", low["torque_Nm"], "#d66a00", False), ("Power / speed", power_torque, "#29945d", True)],
            )
        )
    return "".join(out)


def build(output, manifest, rows, *, pdf=False):
    rows = sorted(rows, key=lambda row: list(PHASE_LABELS).index(row["phase"]))
    report = output / "report"
    report.mkdir(exist_ok=True)
    for row in rows:
        configurations = row.get("configurations") or {"registered": read(ROOT / row["fixture"])}
        row["fixture_files"] = {}
        for stage, config in configurations.items():
            name = f"fixtures/{row['id']}__{stage}.json"
            write(report / name, config)
            row["fixture_files"][stage] = name
    counts = Counter(row["status"] for row in rows)
    overall = (
        "INCOMPLETE"
        if any(s in counts for s in ("INCOMPLETE", "ERROR"))
        else "NON_GATING_SMOKE"
        if manifest["smoke"]
        else "FAIL"
        if "FAIL" in counts
        else "NOT_COMPARED"
        if "NOT_COMPARED" in counts
        else "YELLOW"
        if "YELLOW" in counts
        else "PASS_WITH_UNSUPPORTED"
        if "UNSUPPORTED" in counts
        else "PASS"
    )
    summary = {
        "schema": "coilem.benchmark_summary/v1",
        "status": overall,
        "counts": dict(counts),
        "phase_labels": PHASE_LABELS,
        "phase_order": list(PHASE_LABELS),
        "phase_summary_presentation": {
            phase: phase_display_status(Counter(row["status"] for row in rows if row["phase"] == phase))
            for phase in PHASE_LABELS
            if any(row["phase"] == phase for row in rows)
        },
        "run": manifest,
        "rows": rows,
        "planned_coverage": {row["id"]: {**coverage_plan(row), "numerical_status": row["status"]} for row in rows if coverage_plan(row)},
        "unsupported_capabilities": {"thermal": "No public thermal benchmark in this A/B/C/D protocol"},
    }
    write(report / "benchmark_summary.json", summary)
    styles = (
        "body{font:15px Arial;max-width:1150px;margin:35px auto;padding:0 24px;color:#182636}table{border-collapse:collapse;width:100%}"
        "td,th{padding:10px;border-bottom:1px solid #dce3ed;text-align:left}th{background:#e4eaf2}"
        ".PASS{background:#effcf3;color:#16713d}.FAIL,.ERROR{background:#fff0f0;color:#aa2020}"
        ".YELLOW,.INCOMPLETE,.UNSUPPORTED,.NOT_COMPARED,.NOT_EVALUATED,.PASS_WITH_UNSUPPORTED{background:#fff8e6;color:#835900}"
        "svg{width:49%;min-width:360px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.case{break-before:page}"
        "@media print{svg{min-width:0}a{color:inherit}}"
    )
    title = "Coilem A/B/C/D benchmark"
    parts = [
        f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title><style>{styles}</style><body><h1>{title}</h1>',
        f'<p class="{overall}">Outcome: {display_overall(overall, rows)}</p><p>Harness {manifest["identity"]["harness_version"]}; '
        f"protocol {manifest['identity']['protocol_version']}; Coilem commit {html.escape(manifest['identity']['commit'])}.</p>",
        f"<p>{html.escape(evaluation_note(manifest))}</p>" if evaluation_note(manifest) else "",
        "<p>Orange solid = Coilem. Blue dashed = saved FEMM reference, drawn last so overlaps remain visible. "
        "Residual plots show small differences. Reference data is already in public clockwise coordinates.</p>",
        f"<p>Reference mode: {manifest['reference_mode']}; reference commit: {manifest.get('reference_commit') or 'none'}. "
        "No FEMM solves were executed in this run.</p><table><tr><th>Phase</th><th>Recorded outcomes</th></tr>",
    ]
    markdown = [
        f"# {title}",
        "",
        f"Outcome: **{display_overall(overall, rows)}**",
        "",
        f"Harness {manifest['identity']['harness_version']}; protocol {manifest['identity']['protocol_version']}.",
        f"Candidate commit: `{manifest['identity']['commit']}`. Reference mode: `{manifest['reference_mode']}`.",
        f"Reference commit: `{manifest.get('reference_commit') or 'none'}`. No reference solves executed.",
        evaluation_note(manifest),
        "",
        "| Phase | Outcomes |",
        "|---|---|",
    ]
    for phase, label in PHASE_LABELS.items():
        selected = [r for r in rows if r["phase"] == phase]
        if not selected:
            continue
        text = phase_outcomes(selected)
        display_status = summary["phase_summary_presentation"][phase]
        parts.append(f'<tr class="{display_status}"><td>{phase} – {label}</td><td>{text}</td></tr>')
        markdown.append(f"| {phase} – {label} | {text} |")
    parts.append("</table>")
    parts.append(
        "<p>Phase summary colors: green when every fixture passes; yellow for mixed outcomes or incomplete coverage; "
        "red when more than 50% of recorded fixtures fail. Individual numerical verdicts retain their own status.</p>"
    )
    for phase, label in PHASE_LABELS.items():
        selected = [r for r in rows if r["phase"] == phase]
        if not selected:
            continue
        parts.append(f"<h2>Phase {phase} – {label} results</h2><table><tr><th>Fixture</th><th>Outcome</th></tr>")
        for row in selected:
            link = next(iter(row["fixture_files"].values()))
            parts.append(
                f'<tr class="{row["status"]}"><td><a href="{html.escape(link, quote=True)}">{html.escape(row["id"])}</a></td>'
                f"<td>{display_outcome(row)}</td></tr>"
            )
            markdown.extend(["", f"- [{row['id']}]({link}): **{display_outcome(row)}**{energy_balance_text(row)}"])
            plan = coverage_plan(row)
            if plan:
                markdown.extend(["", f"{plan['reason']} {plan['next_step']} Numerical status remains UNSUPPORTED; no comparison was performed."])
            if row.get("experimental_rotor"):
                markdown.extend(["", EXPERIMENTAL_ROTOR_NOTE])
            markdown.extend(hardware_markdown(row))
        parts.append("</table>")
        for row in selected:
            parts.extend(
                [
                    f'<section class="case"><h3>{phase} – {html.escape(row["id"])}</h3>',
                    "<p>Frozen inputs: "
                    + ", ".join(f'<a href="{html.escape(link, quote=True)}">{html.escape(stage)}</a>' for stage, link in row["fixture_files"].items())
                    + "</p>",
                    f"<p>{html.escape(display_outcome(row))}{html.escape(energy_balance_text(row))}</p>",
                    (
                        f"<p>{html.escape(coverage_plan(row)['reason'])} {html.escape(coverage_plan(row)['next_step'])} "
                        "Numerical status: UNSUPPORTED; no comparison was performed.</p>"
                        if coverage_plan(row)
                        else ""
                    ),
                    f"<p>{html.escape(EXPERIMENTAL_ROTOR_NOTE)}</p>" if row.get("experimental_rotor") else "",
                    charts(row),
                    gate_table(row["evaluation"]),
                    hardware_html(row),
                    "<details><summary>Metrics and diagnostics</summary><pre>"
                    f"{html.escape(json.dumps(row['evaluation'], indent=2, allow_nan=False))}</pre></details></section>",
                ]
            )
    parts.append("<p>Thermal analysis is outside this A/B/C/D protocol. Smoke results never establish numerical parity.</p></body></html>")
    (report / "coilem_benchmark_report.html").write_text("".join(parts), encoding="utf-8", newline="\n")
    (report / "benchmark_report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8", newline="\n")
    with (report / "benchmark_results.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["phase", "topology", "fixture", "status", "coverage_label", "gate", "gate_status", "value"])
        for row in rows:
            gates = row["evaluation"].get("gates", [])
            if isinstance(gates, dict):
                gates = [{"id": name, "status": value} for name, value in gates.items()]
            for gate in gates or [{}]:
                writer.writerow(
                    [
                        row["phase"],
                        PHASE_LABELS[row["phase"]],
                        row["id"],
                        row["status"],
                        display_outcome(row),
                        gate.get("id", ""),
                        gate.get("status", ""),
                        gate.get("value", ""),
                    ]
                )
    if pdf:
        export_pdf(report, summary)
    write(
        report / "artifact_manifest.json",
        {p.relative_to(report).as_posix(): sha(p) for p in sorted(report.rglob("*")) if p.is_file() and p.name != "artifact_manifest.json"},
    )
    return overall


def energy_balance_text(row):
    """Torque over 3*E*I*cos(gamma)/omega_m for coilEM and the reference; diagnostic, never a gate (#80)."""

    balance = row.get("energy_balance") or {}
    values = [(label, balance.get(key)) for label, key in (("coilEM", "candidate_ratio"), ("reference", "reference_ratio"))]
    shown = [f"{label} {value:.3f}" for label, value in values if isinstance(value, (int, float))]
    return f". Energy balance, torque / (3·E·I·cos γ / ω): {', '.join(shown)}" if shown else ""


def gate_table(evaluation):
    gates = evaluation.get("gates", [])
    if isinstance(gates, dict):
        gates = [{"id": k, "status": v} for k, v in gates.items()]
    if not gates:
        return f"<p>{html.escape(evaluation.get('reason', evaluation['status']))}</p>"
    out = ["<table><tr><th>Gate</th><th>Outcome</th><th>Value</th><th>Limit</th></tr>"]
    for gate in gates:
        value = gate.get("value", "")
        if isinstance(value, float):
            value = f"{value:.6g}"
        out.append(
            f'<tr class="{gate["status"]}"><td>{html.escape(gate["id"])}</td><td>{gate["status"]}</td>'
            f"<td>{html.escape(str(value))}</td><td>{html.escape(str(gate.get('maximum', '')))}</td></tr>"
        )
    return "".join(out) + "</table>"


def export_pdf(report, summary):
    """Export the same vector charts and gate verdicts, without extra packages."""
    import xml.etree.ElementTree as ET

    from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    story = [
        Paragraph("Coilem A/B/C/D benchmark", styles["Title"]),
        Paragraph(display_overall(summary["status"], summary["rows"]), styles["Heading2"]),
    ]
    run = summary["run"]
    if evaluation_note(run):
        story.extend([Paragraph(html.escape(evaluation_note(run)), styles["BodyText"]), Spacer(1, 8)])
    for text in (
        f"Harness {run['identity']['harness_version']}; protocol {run['identity']['protocol_version']}.",
        f"Candidate commit: {run['identity']['commit']}",
        f"Reference: {run['reference_mode']}; commit {run.get('reference_commit') or 'none'}.",
        "Orange solid: Coilem; blue dashed: saved FEMM. No reference solves executed.",
    ):
        story.extend([Paragraph(html.escape(text), styles["BodyText"]), Spacer(1, 8)])

    def table(data, statuses):
        formatted = [[Paragraph(html.escape(str(cell)), styles["BodyText"]) for cell in row] for row in data]
        result = Table(formatted, colWidths=[330, 138], repeatRows=1, hAlign="LEFT")
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4eaf2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]
        for i, status in enumerate(statuses, 1):
            shade = "#effcf3" if status == "PASS" else "#fff0f0" if status in ("FAIL", "ERROR") else "#fff8e6"
            commands.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(shade)))
        result.setStyle(TableStyle(commands))
        return result

    overview = [["Phase", "Recorded outcomes"]]
    presentation = []
    for phase, label in PHASE_LABELS.items():
        selected = [r for r in summary["rows"] if r["phase"] == phase]
        if selected:
            counts = Counter(r["status"] for r in selected)
            overview.append([f"{phase} – {label}", phase_outcomes(selected)])
            presentation.append(phase_display_status(counts))
    story.append(table(overview, presentation))
    story.append(
        Paragraph("Phase summary: green for all PASS; yellow for mixed or missing coverage; red for more than 50% FAIL.", styles["BodyText"])
    )
    for phase, label in PHASE_LABELS.items():
        rows = [r for r in summary["rows"] if r["phase"] == phase]
        if rows and phase != "D":
            story.append(Paragraph(f"Phase {phase} – {label} results", styles["Heading2"]))
            story.append(table([["Fixture", "Outcome"], *[[r["id"], display_outcome(r)] for r in rows]], [r["status"] for r in rows]))
    phase_d_shown = False
    for row in summary["rows"]:
        first_phase_d = row["phase"] == "D" and not phase_d_shown
        if first_phase_d:
            drows = [r for r in summary["rows"] if r["phase"] == "D"]
            story.extend(
                [
                    PageBreak(),
                    Paragraph("Phase D – BLDC results", styles["Heading2"]),
                    table([["Fixture", "Outcome"], *[[r["id"], display_outcome(r)] for r in drows]], [r["status"] for r in drows]),
                ]
            )
            phase_d_shown = True
        story.extend(
            [Spacer(1, 12) if first_phase_d else PageBreak(), Paragraph(f"Phase {row['phase']} – {html.escape(row['id'])}", styles["Heading2"])]
        )
        for stage, name in row["fixture_files"].items():
            fixture_url = html.escape((report / name).as_uri(), quote=True)
            story.append(Paragraph(f'<a href="{fixture_url}" color="blue">Frozen {html.escape(stage)} fixture JSON</a>', styles["BodyText"]))
        story.append(Spacer(1, 8))
        plan = coverage_plan(row)
        if plan:
            note = f"{plan['label']}. {plan['reason']} {plan['next_step']} Numerical status: UNSUPPORTED; no comparison was performed."
            story.append(Paragraph(html.escape(note), styles["BodyText"]))
        for svg in ET.fromstring("<root>" + charts(row) + "</root>"):
            drawing = Drawing(540, 230)
            for element in svg:
                attr = element.attrib
                if element.tag == "text":
                    drawing.add(
                        String(
                            float(attr["x"]),
                            230 - float(attr["y"]),
                            (element.text or "").replace("−", "-"),
                            fontName="Helvetica",
                            fontSize=float(attr.get("font-size", 12)),
                            fillColor=colors.HexColor(attr.get("fill", "#182636")),
                        )
                    )
                elif element.tag == "polyline":
                    points = [float(c) for p in attr["points"].split() for c in p.split(",")]
                    points[1::2] = [230 - y for y in points[1::2]]
                    drawing.add(
                        PolyLine(
                            points,
                            strokeColor=colors.HexColor(attr["stroke"]),
                            strokeWidth=2,
                            strokeDashArray=[6, 4] if "stroke-dasharray" in attr else None,
                        )
                    )
                elif element.tag == "path":
                    y = float(attr["d"].split()[1].split("H")[0])
                    drawing.add(Line(45, 230 - y, 525, 230 - y, strokeColor=colors.HexColor("#dce3ed")))
            drawing.scale(0.86, 0.86)
            drawing.width, drawing.height = 464.4, 197.8
            story.append(drawing)
        gates = row["evaluation"].get("gates", [])
        if isinstance(gates, dict):
            gates = [{"id": k, "status": v} for k, v in gates.items()]
        if gates:
            story.append(table([["Gate", "Outcome"], *[[g["id"], g["status"]] for g in gates]], [g["status"] for g in gates]))
        else:
            story.append(Paragraph(html.escape(row["evaluation"].get("reason", row["status"])), styles["BodyText"]))
        if row.get("experimental_rotor"):
            story.append(Paragraph(html.escape(EXPERIMENTAL_ROTOR_NOTE), styles["BodyText"]))
        hardware = hardware_table(row)
        if hardware is not None:
            comparison = row["hardware_comparison"]
            story.append(Spacer(1, 8))
            story.append(Paragraph(html.escape(comparison.get("label", "Hardware correlation")), styles["Heading3"]))
            header = [list(HARDWARE_COLUMNS)] if comparison.get("status") == "NO_VERDICT" else []
            cells = [[Paragraph(html.escape(c), styles["BodyText"]) for c in r] for r in header + hardware]
            story.append(Table(cells, repeatRows=1, hAlign="LEFT"))
    SimpleDocTemplate(
        str(report / "coilem_benchmark_report.pdf"),
        title="Coilem A/B/C/D benchmark",
        author="Coilem",
        rightMargin=60,
        leftMargin=60,
        topMargin=40,
        bottomMargin=40,
    ).build(story)
