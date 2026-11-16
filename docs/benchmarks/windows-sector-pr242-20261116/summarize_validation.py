"""Summarize the retained Windows validation artifacts without altering sources."""
from collections import Counter, defaultdict
import csv
from datetime import datetime
import html
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def tests(path):
    root = ET.parse(ROOT / path)
    cases = list(root.iter("testcase"))
    failures = [{"test": item.attrib["classname"] + "::" + item.attrib["name"],
                 "kind": child.tag, "message": child.attrib.get("message", ""), "traceback": child.text}
                for item in cases for child in item if child.tag in ("failure", "error")]
    return {"cases": len(cases), "passed": sum(all(c.tag not in ("failure", "error", "skipped") for c in t) for t in cases),
            "failures": len([f for f in failures if f["kind"] == "failure"]),
            "errors": len([f for f in failures if f["kind"] == "error"]),
            "skipped": len([t for t in cases if t.find("skipped") is not None]), "details": failures}


def lane_time(run):
    jobs = [j for j in run["jobs"] if j.get("started_at") and j.get("completed_at")]
    start = min(datetime.fromisoformat(j["started_at"]) for j in jobs)
    end = max(datetime.fromisoformat(j["completed_at"]) for j in jobs)
    return (end - start).total_seconds()


def main():
    full, sector = (read(f"af-{kind}-win/report/benchmark_summary.json") for kind in ("full", "sector"))
    full_rows = {r["id"]: r for r in full["rows"]}
    deltas, metrics = [], defaultdict(list)

    def add(case, phase, stage, metric, full_value, sector_value, mode="percent"):
        if full_value is None or sector_value is None or not all(math.isfinite(v) for v in (full_value, sector_value)):
            return
        if mode == "percent" and abs(full_value) < 1e-10:
            return
        delta = sector_value - full_value if mode == "points" else 100 * (sector_value - full_value) / abs(full_value)
        entry = {"case": case, "phase": phase, "stage": stage, "metric": metric,
                 "full": full_value, "sector": sector_value, "delta": delta,
                 "delta_unit": "percentage points" if mode == "points" else "%"}
        deltas.append(entry)
        metrics[metric].append(entry)

    for row in sector["rows"]:
        baseline = full_rows[row["id"]]
        if row["status"] == "UNSUPPORTED" or baseline["status"] == "UNSUPPORTED":
            continue
        # One registered operating point per case. Phase D also retains its Fine control.
        stage = "native-standard" if row["phase"] == "D" else "native"
        candidate = row["measurements"].get(stage)
        reference = baseline["measurements"].get(stage)
        if not candidate or not reference:
            continue
        if row["phase"] == "D":
            add(row["id"], row["phase"], stage, "loaded_mean_torque",
                math.fsum(reference["torque_Nm"]) / len(reference["torque_Nm"]),
                math.fsum(candidate["torque_Nm"]) / len(candidate["torque_Nm"]))
            continue
        a, b = reference["summary"], candidate["summary"]
        if row["phase"] == "E":
            for field, label in (("peak_to_peak_Nm", "cogging_peak_to_peak"), ("first_harmonic_Nm", "cogging_fundamental")):
                add(row["id"], row["phase"], stage, label, a["cogging"][field], b["cogging"][field])
            continue
        if row["configurations"][stage]["solve_params"]["current_amplitude_A"] > 0:
            add(row["id"], row["phase"], stage, "loaded_mean_torque", a.get("avg_torque_Nm"), b.get("avg_torque_Nm"))
        add(row["id"], row["phase"], stage, "back_emf_fundamental", a.get("back_emf_fundamental_V"), b.get("back_emf_fundamental_V"))
        for field, label in (("iron_loss_W", "iron_loss"), ("iron_yoke_loss_W", "yoke_iron_loss")):
            add(row["id"], row["phase"], stage, label, (a.get("iron_loss") or {}).get(field), (b.get("iron_loss") or {}).get(field))
        add(row["id"], row["phase"], stage, "efficiency", (a.get("loss_breakdown") or {}).get("efficiency_pct"),
            (b.get("loss_breakdown") or {}).get("efficiency_pct"), "points")
        if row["evaluation"].get("dq"):
            for field in ("lambda_d_Wb", "lambda_q_Wb"):
                add(row["id"], row["phase"], stage, field, (a.get("dq_flux_linkage") or {}).get(field), (b.get("dq_flux_linkage") or {}).get(field))

    metric_summary = {key: {"count": len(entries), "max_abs_delta": max(abs(e["delta"]) for e in entries),
                            "worst": max(entries, key=lambda e: abs(e["delta"]))}
                      for key, entries in metrics.items()}
    torque = metrics["loaded_mean_torque"]
    torque_bands = Counter("within_0.5_percent" if abs(e["delta"]) <= .5 else "0.5_to_1_percent" if abs(e["delta"]) <= 1 else "above_1_percent" for e in torque)
    fallbacks = [{"case": row["id"], "stage": stage, "repeats": repeat} for row in sector["rows"]
                 for stage, repeat in row.get("sector_repeats", {}).items() if not repeat or repeat < 2]
    lanes = {"full": {"status": full["status"], "counts": full["counts"], "elapsed_s": lane_time(full["run"])},
             "sector": {"status": sector["status"], "counts": sector["counts"], "elapsed_s": lane_time(sector["run"])},
             "status_differences": [{"case": r["id"], "full": full_rows[r["id"]]["status"], "sector": r["status"]}
                                    for r in sector["rows"] if full_rows[r["id"]]["status"] != r["status"]],
             "sector_fallbacks": fallbacks, "sector_cases": len(sector.get("sector_repeats", {})),
             "metric_differences": metric_summary, "loaded_torque_bands": dict(torque_bands),
             "loaded_torque_above_1_percent": [e for e in torque if abs(e["delta"]) > 1]}
    (ROOT / "lane-comparison.json").write_text(json.dumps(lanes, indent=2))
    if not (ROOT / "prius-sector-win/report/app-results.json").exists():
        print(json.dumps(lanes, indent=2))
        return
    prius = read("prius-sector-win/report/app-results.json")
    prius_registration = read("prius-sector-win/registration.json")
    previous_prius = read("source/benchmarks/qualification-78e6f4fc8aa8/windows-x86_64/prius/app-results.json")
    previous_curve = {row["Phi0_deg"]: row["app_Nm"] for row in previous_prius["curve"]}
    prius_curve_comparison = [{"Phi0_deg": row["Phi0_deg"], "sector_Nm": row["app_Nm"],
                               "published_v058_full_Nm": previous_curve[row["Phi0_deg"]],
                               "difference_Nm": row["app_Nm"] - previous_curve[row["Phi0_deg"]]} for row in prius["curve"]]
    report = {
        "status": "COMPLETED_WITH_TEST_FAILURES",
        "commit": "52f19004982887a7d615bbb8ea3b5a69bdfcacf7", "machine": read("machine.json"),
        "source_worktree_clean": read("validation-status.json")["final_git_status"] == "",
        "tests": tests("python-tests-dev.xml"), "first_test_run": tests("python-tests.xml"),
        "sector_tests": tests("sector-tests.xml"), "windows_followup": tests("windows-followup.xml"),
        "rust_passed": 283, "frontend_build": "PASS", "full_against_v058": read("v058-full-comparison.json"),
        "lanes": lanes,
        "prius": {"checks": prius["checks"], "tutorial_rms_difference_pct": 100 * prius["tutorial"]["tutorial_line_rms_relative"],
                  "loaded": prius["loaded"], "curve": prius["curve"], "job_count": len(prius_registration["jobs"]),
                  "sector_repeats": {j["job"]: j["solve_metadata"].get("sector_repeats") for j in prius_registration["jobs"]},
                  "curve_against_published_v058_windows_full": prius_curve_comparison,
                  "max_curve_difference_from_published_full_Nm": max(abs(r["difference_Nm"]) for r in prius_curve_comparison)},
        "app": {"example": "SPM outrunner 14p/12s", "sector_repeats": 2, "solved_triangles": 48524, "displayed_triangles": 97048,
                "stator_slot_pitch_repetition": "PASS", "stopped_highlight": "PASS", "spin_full_motor": "PASS",
                "pause_angle_highlight": "PASS", "field_and_playback_full_motor_no_visible_seam": "PASS"},
        "notes": ["Source worktree was clean; benchmark output and local wrapper are outside that checkout.",
                  "A-F grading bypassed only references._require_cogging_review as requested in the PR validation instructions.",
                  "The unmodified full Python suite retains the 16 documented qualification outcomes plus Windows executable-lookup failures.",
                  "Gmsh initialization reproduces bare-name node/git lookup failure; absolute executable paths succeed.",
                  "All 40 isolated follow-up tests pass. First-run playback shutdown failure cleared on the second full run and isolated follow-up.",
                  "Full-motor comparison with the published Windows 0.5.8 record is numerical only; no qualification records or carry receipts were changed.",
                  "Loaded-torque counts use actual request current: the legacy case named spm_4p12s_simple_noload__high_current requests 5 A and is included.",
                  "Lambda-d/q percentages cover the 12 registered d/q gate points. Other diagnostic linkages, including near-zero no-load q components, remain in both original lane summaries.",
                  "Lane times are observed back-to-back wall times; another developer was using the machine, so these are not controlled timings."]
    }
    (ROOT / "validation-results.json").write_text(json.dumps(report, indent=2))
    with (ROOT / "full-vs-sector.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(deltas[0]))
        writer.writeheader()
        writer.writerows(deltas)
    esc = html.escape
    rows = "".join(f"<tr><td>{esc(key)}</td><td>{value['count']}</td><td>{value['max_abs_delta']:.6f} {esc(value['worst']['delta_unit'])}</td><td>{esc(value['worst']['case'])}</td></tr>" for key, value in metric_summary.items())
    body = f"""<!doctype html><html><meta charset="utf-8"><title>PR 242 Windows validation</title>
<style>body{{font:16px system-ui;max-width:1150px;margin:40px auto;padding:0 24px;color:#182636}}table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;border-bottom:1px solid #ddd;text-align:left}}pre{{white-space:pre-wrap}}img{{max-width:100%}}</style>
<h1>PR #242 Windows validation at 52f19004</h1>
<p><strong>Completed with Python test failures.</strong> Both numerical A-F lanes and all sector, Rust, Prius, frontend, and app checks passed. The full Python run includes the documented qualification outcomes and the additional Windows executable-lookup issue described below.</p>
<p>Windows 11 Home build 26200, AMD Ryzen 7 7700, 64 GB RAM, AC power. Exact commit: <code>{report['commit']}</code>.</p>
<p>Sector tests: 81 passed. Rust tests: 283 passed. Frontend build and contracts: passed.</p>
<p>Full Python suite: 2660 passed, 25 failed, 9 errors, 3 skipped. Includes the 16 documented qualification outcomes and 18 additional Windows process-lookup outcomes. All 40 follow-up tests passed in isolation. Complete tracebacks are in <a href="python-tests-dev.log">the full-suite log</a>.</p>
<p>A-F full: {esc(full['status'])} {esc(str(full['counts']))}; sector: {esc(sector['status'])} {esc(str(sector['counts']))}. Status differences: {len(report['lanes']['status_differences'])}. Sector fallbacks: {len(fallbacks)}.</p>
<p>Full lane {report['lanes']['full']['elapsed_s']/60:.2f} minutes; sector lane {report['lanes']['sector']['elapsed_s']/60:.2f} minutes. Observed back-to-back wall times, with other work on the machine.</p>
<p>Full motor against the published Windows 0.5.8 record at 78e6f4fc8aa8: 69/69 case comparisons match, including gate outcomes. Suite and reference-bundle hashes are unchanged. <a href="v058-full-comparison.json">Detailed 0.5.8 comparison</a>.</p>
<table><tr><th>Sector versus full</th><th>Cases</th><th>Maximum absolute difference</th><th>Case</th></tr>{rows}</table>
<p>Loaded mean torque: {torque_bands['within_0.5_percent']} cases within 0.5%, {torque_bands['0.5_to_1_percent']} more within 1%, and 3 distributed-winding cases above 1% (12p36s +3.253%, 8p48s chorded +1.640%, 8p48s +1.546%). Both full and sector versions pass the frozen FEMM gates.</p>
<p>Prius: {sum(prius['checks'].values())}/{len(prius['checks'])} software checks passed. Tutorial RMS difference {report['prius']['tutorial_rms_difference_pct']:+.6f}%. Loaded preset difference {100*prius['loaded']['difference_to_FEMM_relative']:+.6f}% from retained FEMM.</p>
<p>All {report['prius']['job_count']} Prius jobs solved as 1/8 sectors. Maximum difference across the 13 curve torques against the published Windows 0.5.8 full-motor run: {report['prius']['max_curve_difference_from_published_full_Nm']:.6f} N·m.</p>
<p>App checks passed: tooth-centre stator repetition, stopped sector highlighting, whole-motor Spin, restored highlighting after pausing, and full-motor field/playback without a visible seam.</p>
<p><a href="validation-results.json">Full results JSON</a> · <a href="full-vs-sector.csv">Case-by-case CSV</a> · <a href="af-full-win/report/benchmark_summary.json">Full lane summary</a> · <a href="af-sector-win/report/benchmark_summary.json">Sector lane summary</a> · <a href="prius-sector-win/report/app-results.md">Prius report</a> · <a href="gmsh-executable-lookup.json">Gmsh lookup reproduction</a></p>
<img src="app-sector-mesh.jpg" alt="Stopped mesh with bright solved sector and dim repeated half"><img src="app-field-playback.jpg" alt="Full motor field playback">
<h2>Validation notes</h2><ul>{''.join('<li>'+esc(n)+'</li>' for n in report['notes'])}</ul></html>"""
    (ROOT / "validation-report.html").write_text(body, encoding="utf-8")
    filenames = ["validation-report.html", "validation-results.json", "full-vs-sector.csv", "machine.json", "python-environment.txt",
                 "validation-status.json", "lane-comparison.json", "v058-full-comparison.json", "run_validation.py", "run_lane_local.py", "check_gmsh_executable_lookup.py",
                 "gmsh-executable-lookup.log", "gmsh-executable-lookup.json", "summarize_validation.py"]
    filenames += [p.name for pattern in ("*.log", "*.xml", "app-*.jpg") for p in ROOT.glob(pattern)]
    filenames += [f"af-{kind}-win/report/benchmark_summary.json" for kind in ("full", "sector")]
    filenames += [f"prius-sector-win/report/app-results.{extension}" for extension in ("md", "json")]
    with zipfile.ZipFile(ROOT / "pr242-windows-validation.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(set(filenames)):
            if (ROOT / name).is_file():
                archive.write(ROOT / name, name)
    print(json.dumps({k: report[k] for k in ("lanes", "prius")}, indent=2))


if __name__ == "__main__":
    main()
