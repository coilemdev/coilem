"""Report a collection without merging protocols or hiding experimental grades."""

from __future__ import annotations

import copy
import html
from collections import Counter
from pathlib import Path

from backend import __version__
from backend.benchmark_suite import HARNESS_VERSION
from backend.benchmark_suite.contract import ROOT, read, sha, write
from backend.benchmark_suite.record import platform_key
from backend.benchmark_suite.report import build, display_overall, export_pdf
from backend.benchmark_suite.share import SHARE_DIR, SHARE_NAME, _case, _redacted, _strings
from backend.local_paths import contains_local_path


def _component_info(child):
    component, summary, comparison = child["component"], child["summary"], child["comparison"]
    run = summary["run"]
    return {"id": component["id"], "phases": component["phases"], "experimental": component["experimental"],
            "protocol_version": run["identity"]["protocol_version"], "measured_commit": run["identity"]["commit"],
            "numerical_status": summary["status"], "record_match": comparison["status"],
            "reference": {key: run[key] for key in ("reference_commit", "reference_id", "reference_identity_kind",
                                                   "reference_review_scope") if key in run},
            "report": child["relative_directory"] + "/report/coilem_benchmark_report.html"}


def _combined_comparison(children, info):
    recorded = [child["comparison"] for child in children if not child["component"]["experimental"]]
    states = {part["status"] for part in recorded}
    status = next((value for value in ("NOT_COMPARABLE", "DIFFERS", "NO_RECORD") if value in states),
                  "MATCH" if recorded else "NO_RECORD")
    cases = {}
    for child in children:
        cases.update(child["comparison"].get("cases", {}))
    return {"schema": "coilem.benchmark_collection_comparison/v1", "status": status, "platform": platform_key(),
            "scope": "Per-component platform-record matching; experimental Phase E has no accepted record.",
            "matched": sum(part.get("matched", 0) for part in recorded),
            "compared": sum(part.get("compared", 0) for part in recorded), "cases": cases, "components": info,
            "experimental_phases": sorted({phase for part in info if part["experimental"] for phase in part["phases"]})}


def _scope_markdown(info, comparison):
    lines = ["", "## Component scopes", "",
             "Each component retains its own protocol, measured identity and reference dataset.",
             "Phase E is experimental: its raw grades remain visible and do not establish qualification.",
             "Record matching is separate from numerical grades and does not qualify unmeasured platforms or settings.", "",
             "| Phases | Protocol | Measured commit | Scope | Numerical outcome | Record match |",
             "|---|---|---|---|---|---|"]
    for part in info:
        scope = "Experimental; no qualification" if part["experimental"] else "Separate reference; platform record where available"
        lines.append(f"| {', '.join(part['phases'])} | {part['protocol_version']} | `{part['measured_commit'][:12]}` | {scope} | "
                     f"{part['numerical_status']} | {part['record_match']} |")
    lines += ["", f"Record-match scope: {comparison['matched']}/{comparison['compared']} recorded cases match. "
              "Experimental cases remain outside that count.", ""]
    return lines


def _scope_html(info, comparison):
    rows = []
    for part in info:
        scope = "Experimental; no qualification" if part["experimental"] else "Separate reference; platform record where available"
        values = (", ".join(part["phases"]), part["protocol_version"], part["measured_commit"][:12], scope,
                  part["numerical_status"], part["record_match"])
        rows.append("<tr>" + "".join("<td>" + html.escape(value) + "</td>" for value in values) + "</tr>")
    return ("<section><h2>Component scopes</h2><p>Each component retains its own protocol, measured identity and reference dataset. "
            "<strong>Phase E is experimental.</strong> Its raw grades remain visible and do not establish qualification. "
            "Record matching does not qualify unmeasured platforms or settings.</p>"
            "<table><tr><th>Phases</th><th>Protocol</th><th>Measured commit</th><th>Scope</th><th>Numerical outcome</th><th>Record match</th></tr>"
            + "".join(rows) + "</table><p>Recorded cases matching: " + str(comparison["matched"]) + "/"
            + str(comparison["compared"]) + ". Experimental cases are outside that count.</p></section>")


def build_collection_report(output, manifest, children, *, pdf=False):
    """Return (summary, comparison); native/reference inputs are never modified."""
    output = Path(output)
    rows, seen = [], set()
    for child in children:
        component = child["component"]
        if "E" in component["phases"] and component.get("experimental") is not True:
            raise ValueError("Phase E must remain explicitly experimental")
        for original in child["summary"]["rows"]:
            if original["id"] in seen or original["phase"] not in component["phases"]:
                raise ValueError("Collection reports contain a duplicate or misassigned case")
            seen.add(original["id"])
            row = copy.deepcopy(original)
            row.update(collection_component=component["id"], experimental=bool(component["experimental"]))
            rows.append(row)
    info = [_component_info(child) for child in children]
    comparison = _combined_comparison(children, info)
    identity = copy.deepcopy(children[0]["summary"]["run"]["identity"]) if children else {}
    commits = {part["measured_commit"] for part in info}
    identity.update(harness_version=HARNESS_VERSION, protocol_version="collection/1",
                    commit=next(iter(commits)) if len(commits) == 1 else "per-component")
    display = {**copy.deepcopy(manifest), "identity": identity, "smoke": False,
               "reference_mode": "INDEPENDENT_COMPONENT_DATASETS", "collection_components": info or [{"status": "PENDING"}]}
    output.mkdir(parents=True, exist_ok=True)
    build(output, display, rows, pdf=False)
    path = output / "report/benchmark_summary.json"
    summary = read(path)
    previous_status = summary["status"]
    if manifest.get("status") not in ("COMPLETE", "COMPLETE_WITH_ERRORS") or len(children) != len(manifest.get("components", children)):
        summary["status"] = "INCOMPLETE"
    summary.update(schema="coilem.benchmark_collection_summary/v1", collection={"components": info,
                   "evidence_mode": manifest.get("evidence_mode", "CURRENT_COLLECTION"),
                   "experimental_phases": comparison["experimental_phases"],
                   "experimental_counts": dict(Counter(row["status"] for row in rows if row["experimental"])),
                   "recorded_counts": dict(Counter(row["status"] for row in rows if not row["experimental"]))},
                   record_comparison=comparison)
    write(path, summary)
    write(output / "record-comparison.json", comparison)
    markdown_path = output / "report/benchmark_report.md"
    retained_note = ("Retained evidence: the components were measured at the candidates shown below. "
                     "This report reused their saved data and did not rerun solves."
                     if manifest.get("evidence_mode") == "RETAINED_MIXED_CANDIDATES" else "")
    markdown = markdown_path.read_text(encoding="utf-8")
    markdown = markdown.replace(f"Outcome: **{display_overall(previous_status, rows)}**",
                                f"Outcome: **{display_overall(summary['status'], rows)}**", 1)
    markdown_path.write_text(markdown + "\n" + retained_note + "\n" + "\n".join(_scope_markdown(info, comparison)), encoding="utf-8")
    html_path = output / "report/coilem_benchmark_report.html"
    page = html_path.read_text(encoding="utf-8")
    page = page.replace(f'<p class="{previous_status}">Outcome: {display_overall(previous_status, rows)}</p>',
                        f'<p class="{summary["status"]}">Outcome: {display_overall(summary["status"], rows)}</p>', 1)
    page = page.replace("</h1>", "</h1><p>" + html.escape(retained_note) + "</p>" + _scope_html(info, comparison), 1)
    html_path.write_text(page, encoding="utf-8")
    payload = {"schema": "coilem.benchmark_collection_share/v1", "coilem_version": __version__,
               "platform": comparison["platform"], "status": summary["status"], "raw_counts": summary["counts"],
               "evidence_mode": manifest.get("evidence_mode", "CURRENT_COLLECTION"),
               "experimental_phases": comparison["experimental_phases"], "components": info,
               "record_match": {key: comparison[key] for key in ("status", "scope", "matched", "compared")},
               "cases": [_case(row, comparison) for row in rows]}
    payload = _redacted(payload, [str(output), str(ROOT), str(Path.home())])
    share_lines = [f"# coilEM A–F benchmark: {summary['status']}", "", "All numerical grades are retained.", retained_note]
    share_lines += _scope_markdown(info, comparison)
    share_lines += ["| Phase | Case | Numerical verdict | Scope |", "|---|---|---|---|"]
    for case in payload["cases"]:
        scope = "Experimental" if case.get("experimental") else "Per-component record comparison"
        share_lines.append(f"| {case['phase']} | `{case['id']}` | {case['status']} | {scope} |")
    phases = sorted({row["phase"] for row in rows})
    options = manifest.get("selection", {}).get("options", {})
    command = "coilem benchmark" + (" --quick" if options.get("quick") else "")
    if phases != list("ABCDEF"):
        command += "".join(" --phase " + phase for phase in phases)
    share_lines += ["", "Reproduce with `" + command + "`. Each component is graded against its own reference identity.", ""]
    share_text = "\n".join(share_lines)
    if any(contains_local_path(value) for value in (share_text, *_strings(payload))):
        raise ValueError("The collection share report contains a local path")
    directory = output / SHARE_DIR
    directory.mkdir(exist_ok=True)
    write(directory / (SHARE_NAME + ".json"), payload)
    (directory / (SHARE_NAME + ".md")).write_text(share_text, encoding="utf-8")
    report = output / "report"
    if pdf:
        export_pdf(report, summary)
    write(report / "artifact_manifest.json", {item.relative_to(report).as_posix(): sha(item)
          for item in sorted(report.rglob("*")) if item.is_file() and item.name != "artifact_manifest.json"})
    return summary, comparison
