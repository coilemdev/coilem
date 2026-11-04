"""Verify real browser-downloaded Performance exports against the saved analysis.

Run after playwright.performance.config.ts; no solver reruns or rewritten exports.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path

from pypdf import PdfReader

from backend.report_numbers import format_report_number


def check(directory: Path) -> dict:
    analysis = json.loads((directory / "analysis.json").read_text(encoding="utf-8"))
    browser = json.loads((directory / "browser-check.json").read_text(encoding="utf-8"))
    assert browser["passed"]
    contents = (directory / "performance.csv").read_text(encoding="utf-8-sig")
    assert contents.startswith("report_schema,coilem.performance_report.v1")
    rows = list(csv.DictReader(io.StringIO(contents.split("\n", 1)[1])))
    values = {(row["section"], row["field"], row["sample_index"]): row["value"] for row in rows}
    comparisons = 0

    def equal(section, field, expected, index=""):
        nonlocal comparisons
        actual = values[section, field, str(index)]
        if isinstance(expected, (float, int)):
            assert math.isclose(float(actual), expected, rel_tol=1e-10, abs_tol=1e-10), (section, field, index)
        else:
            assert actual == expected, (section, field, index)
        comparisons += 1

    equal("map", "preset", "standard")
    equal("map", "currents", 7)
    equal("map", "current_angles", 10)
    equal("map", "mesh_density", "normal")
    equal("map", "rotor_positions_per_point", 24)
    peak = next(curve for curve in analysis["envelope"]["curves"] if curve["limit"] == "peak")
    equal("result", "peak_torque", peak["torque_Nm"][0])
    equal("result", "peak_power", peak["peak_power_W"])
    efficiency = analysis["efficiency_map"]
    best = max(value for row in efficiency["efficiency_pct"] for value in row if value is not None)
    equal("result", "best_efficiency", best)
    for curve in analysis["envelope"]["curves"]:
        for field, key in (
            ("speed", "speed_rpm"),
            ("torque", "torque_Nm"),
            ("power", "power_W"),
            ("i_d", "i_d_A"),
            ("i_q", "i_q_A"),
            ("phase_voltage_peak", "phase_voltage_peak_V"),
        ):
            for index, value in enumerate(curve[key]):
                equal(f"torque_speed_{curve['limit']}", field, value, index)
    index = 0
    for row_index, torque in enumerate(efficiency["torque_Nm"]):
        for column, speed in enumerate(efficiency["speed_rpm"]):
            value = efficiency["efficiency_pct"][row_index][column]
            if value is None:
                continue
            equal("efficiency_map", "speed", speed, index)
            equal("efficiency_map", "torque", torque, index)
            equal("efficiency_map", "efficiency", value, index)
            index += 1
    reader = PdfReader(directory / "performance.pdf")
    text = "\n".join(page.extract_text() for page in reader.pages)
    for label in ("Key results", "Peak torque", "Peak power", "Best efficiency", "Torque and power against speed", "MTPA"):
        assert label in text, label
    for value in (peak["torque_Nm"][0], peak["peak_power_W"] / 1000, best):
        assert format_report_number(value) in text, value
    assert "Experimental" in text
    assert (directory / "map.csv").stat().st_size > 1000
    assert (directory / "idiq.csv").stat().st_size > 1000
    result = {
        "passed": True,
        "csv_numeric_comparisons": comparisons,
        "efficiency_cells": index,
        "pdf_pages": len(reader.pages),
        "pdf_headlines_match_analysis": True,
        "files": {
            path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(directory.iterdir())
            if path.is_file() and path.name != "export-check.json"
        },
    }
    (directory / "export-check.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path)
    args = parser.parse_args()
    for directory in args.directories:
        result = check(directory)
        print(f"{directory.name}: PASS ({result['csv_numeric_comparisons']} CSV comparisons; {result['pdf_pages']} PDF pages)")


if __name__ == "__main__":
    main()
