"""Create a separate numerical-sensitivity review without regrading saved results."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections import Counter
from pathlib import Path

from backend.benchmark_suite.numerical_resolution import scalar_resolution
from backend.benchmark_suite.report import numerical_resolution_text


def review(payload):
    if not isinstance(payload, dict) or payload.get("schema") != "coilem.numerical_resolution_request/v1":
        raise ValueError("Expected a numerical-resolution request with an explicit schema")
    comparisons = payload.get("comparisons")
    if not isinstance(comparisons, list) or not comparisons:
        raise ValueError("At least one scalar comparison is required")
    rows, seen = [], set()
    for item in comparisons:
        if not isinstance(item, dict):
            raise ValueError("Each comparison must be a mapping")
        identifier, original_status = item.get("id"), item.get("original_gate_status")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("Comparison IDs must be nonempty and unique")
        if original_status not in {"PASS", "YELLOW", "FAIL", "MISSING", "INCOMPLETE", "NOT_EVALUATED"}:
            raise ValueError("Each comparison must retain its original gate status")
        if item.get("unit") not in ("N m", "N·m", "Nm", "mNm", "V"):
            raise ValueError("Report units must be N m, N·m, Nm, mNm or V")
        seen.add(identifier)
        assessment = scalar_resolution(
            item["candidate"], item["reference"], unit=item["unit"],
            relative_floor_abs=item.get("relative_floor_abs", 0.0),
            context=item.get("context"), studies=item.get("studies", ()),
        )
        rows.append({"id": identifier, "original_gate_status": original_status,
                     "original_gate_details": item.get("original_gate_details"),
                     "numerical_resolution": assessment})
    return {"schema": "coilem.numerical_resolution_review/v1", "diagnostic_only": True,
            "original_gate_counts": dict(Counter(row["original_gate_status"] for row in rows)),
            "new_gate_verdict_assigned": False, "registration_or_qualification_changed": False,
            "field_solves_executed": 0, "rows": rows}


def write_report(report, output):
    output = Path(output)
    if output.exists():
        raise ValueError("Preserve existing reports; choose a new output directory")
    output.mkdir(parents=True)
    (output / "numerical-resolution.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    introduction = (
        "Original gate verdicts are retained. These deterministic controls show observed sensitivity; "
        "they do not establish an uncertainty bound, a confidence interval, or that a discrepancy is noise."
    )
    markdown = ["Numerical resolution review", "", introduction, ""]
    sections = []
    for row in report["rows"]:
        note = numerical_resolution_text({"numerical_resolution": row["numerical_resolution"]})
        markdown.extend([row["id"], "", "Original gate: " + row["original_gate_status"], "", note, ""])
        sections.append(
            "<section><h2>" + html.escape(row["id"]) + "</h2><p>Original gate: <strong>"
            + html.escape(row["original_gate_status"]) + "</strong></p><p>" + html.escape(note) + "</p></section>"
        )
    (output / "numerical-resolution.md").write_text("\n".join(markdown), encoding="utf-8")
    page = (
        "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' "
        "content='width=device-width,initial-scale=1'><title>Numerical resolution review</title>"
        "<style>body{font:16px/1.6 system-ui;max-width:900px;margin:32px auto;padding:0 20px;color:#182636}"
        "section{border-top:1px solid #ccd5df;margin-top:24px}strong{font-weight:650}</style>"
        "<h1>Numerical resolution review</h1><p>" + html.escape(introduction) + "</p>" + "".join(sections) + "</html>"
    )
    (output / "numerical-resolution.html").write_text(page, encoding="utf-8")
    files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(output.iterdir()) if path.is_file()}
    (output / "artifact-manifest.json").write_text(json.dumps(files, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Scalar comparisons and explicitly scoped numerical controls")
    parser.add_argument("--out-dir", type=Path, required=True, help="New directory; original reports are never rewritten")
    args = parser.parse_args(argv)
    try:
        contents = args.input.read_bytes()

        def reject_constant(value):
            raise ValueError("Nonfinite JSON number: " + value)

        payload = json.loads(contents.decode("utf-8"), parse_constant=reject_constant)
        report = review(payload)
        report["source_input_sha256"] = hashlib.sha256(contents).hexdigest()
        write_report(report, args.out_dir)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"Numerical-resolution review failed: {error}\n")
    print(json.dumps({"out_dir": str(args.out_dir), "original_gate_counts": report["original_gate_counts"],
                      "new_gate_verdict_assigned": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
