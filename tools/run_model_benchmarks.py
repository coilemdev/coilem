"""Run the matrix, exact Pyleecan Prius, and exploratory Honda benchmarks from a checkout.

This is an additive source workflow. The installed ``coilem benchmark`` command
and the registered A/B/C/D suite/reference IDs retain their existing scope.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from backend.benchmark_suite.contract import checked_path, identity, now, read, run_lock, sha, write
from backend.magneto2d_adapter import ensure_magneto2d_binary
from backend.resources import benchmark_data_files
from tools.prius_benchmark_contract import GRADING_INPUTS

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "coilem.model_benchmarks/v1"
MODELS = {
    "abcd": ("A/B/C/D FEMM matrix", "software comparison; existing numerical gates"),
    "pyleecan-prius": ("Pyleecan Prius 8p48s", "software reproduction; tutorial BEMF, loaded torque, full curve and controls"),
    "honda-accord": ("Honda Accord 2005 16p24s", "exploratory hardware correlation; no hardware pass/fail"),
}
HONDA = "docs/hardware-validation/honda-accord-2005"
STATE_FILE = "model-benchmarks.json"


def input_files(models):
    names = set()
    if "abcd" in models:
        names.update(benchmark_data_files(ROOT))
    if "pyleecan-prius" in models:
        names.update(GRADING_INPUTS.values())
    if "honda-accord" in models:
        names.update(f"{HONDA}/{name}.json" for name in
                     ("request", "target-back-emf", "target-locked-rotor", "sources", "input-provenance"))
    return sorted(names)


def current_identity(models):
    result = identity(ensure_magneto2d_binary())
    # Include every source workflow helper (including transitive imports) as
    # well as the backend/native identity captured by the common harness.
    result["workflow_sources"] = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted((ROOT / "tools").rglob("*.py"))}
    result["grading_inputs"] = {name: sha(ROOT / name) for name in input_files(models)}
    if result["installation"] != "source" or result["dirty"]:
        raise ValueError("Use a clean committed source checkout for model benchmarks")
    return result


def verify_identity(expected, models):
    if current_identity(models) != expected:
        raise ValueError("Source, executable, runtime or grading inputs changed during the model benchmark")


def commands(model, folder):
    """Keep each model's original collector, physical requests and evaluator."""
    if model == "abcd":
        return [("tools.run_benchmarks", ["--phases", "A", "B", "C", "D", "--out-dir", str(folder / "collection"), "--pdf"])]
    if model == "pyleecan-prius":
        return [
            ("tools.benchmark_prius", ["--out", str(folder / "collection"), "--curve", "--refinement"]),
            ("tools.report_prius_benchmark", [str(folder / "collection"), "--out", str(folder / "report")]),
        ]
    return [
        ("tools.honda_accord_comparison", ["no-load", "--out", str(folder / "no-load.json")]),
        ("tools.honda_accord_comparison", ["locked-rotor", "--out", str(folder / "locked-rotor.json")]),
        ("tools.honda_accord_comparison", ["assemble", "--no-load", str(folder / "no-load.json"),
                                           "--locked", str(folder / "locked-rotor.json"), "--out", str(folder / "report")]),
        ("tools.plot_honda_accord_comparison", [str(folder / "report")]),
    ]


def run_step(module, arguments, folder, index):
    env = dict(os.environ)
    # The historical Honda collector discovers/deletes caches. A private root
    # prevents it from touching a live app or another benchmark's solve cache.
    env.update(COILEM_USER_DATA_ROOT=str(folder / "runtime"), PYTHONUTF8="1",
               COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS="1", COILEM_MAGNETO2D_PERSIST_SUMMARY_ARTIFACTS="1")
    with (folder / f"step-{index}.txt").open("w", encoding="utf-8") as log:
        done = subprocess.run([sys.executable, "-m", module, *arguments], cwd=ROOT, env=env,
                              stdout=log, stderr=subprocess.STDOUT, check=False)
    return done.returncode


def inventory(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob("*"))
            if p.is_file() and "runtime" not in p.relative_to(folder).parts}


def verify_completed(output, entry):
    folder = checked_path(output, entry["directory"])
    if inventory(folder) != entry["artifacts"]:
        raise ValueError("Completed model evidence changed; do not resume or overwrite it")


def model_result(model, folder):
    if model == "abcd":
        data = read(folder / "collection/report/benchmark_summary.json")
        return {"status": data["status"], "counts": data["counts"],
                "report": "collection/report/coilem_benchmark_report.html"}
    if model == "pyleecan-prius":
        data = read(folder / "report/app-results.json")
        return {"status": "PASS" if data["all_software_checks_pass"] else "FAIL", "checks": data["checks"],
                "report": "report/app-results.md"}
    data = read(folder / "report/comparison.json")
    points = read(folder / "locked-rotor.json")
    from tools.honda_accord_comparison import locked_rotor_points

    if len(points) != len(locked_rotor_points()) or {(r["current_A"], r["delta_deg"]) for r in points} != set(locked_rotor_points()):
        raise ValueError("Incomplete Honda locked-rotor selection")
    if any(r["coilem_currents_per_Ia"] != [1.0, -0.5, -0.5] for r in points):
        raise ValueError("Missing or incorrect Honda phase-current audit")
    return {"status": "COMPLETE_NO_HARDWARE_VERDICT", "back_emf_error_pct": data["back_emf"]["error_pct"],
            "peak_torque_error_pct": data["locked_rotor"]["error_pct"], "report": "report/comparison.json"}


def write_index(output, state):
    lines = ["# Motor benchmark report", "", f"Measured source: `{state['identity']['commit']}`.", "",
             "Each model retains its own inputs, reference contract and verdict. Hardware correlation has no pass/fail.", "",
             "| Model | Scope | Outcome | Evidence |", "| --- | --- | --- | --- |"]
    for model in state["models"]:
        entry = state["results"].get(model)
        if entry:
            result = entry["result"]
            link = f"{entry['directory']}/{result['report']}"
            outcome, evidence = result["status"], f"[Full report]({link})"
        else:
            outcome, evidence = state["states"][model], "See retained attempt logs"
        label, scope = MODELS[model]
        lines.append(f"| {label} | {scope} | {outcome} | {evidence} |")
    lines += ["", "The unsupported legacy ORNL Prius HoleM50 row is deferred hardware coverage for v0.5.0. "
              "It is a different model from Pyleecan Prius 8p48s. Its recorded UNSUPPORTED verdict remains intact. "
              "The V-shape back-EMF YELLOW is a separate measured numerical warning.", "",
              "Selection, exact runtime/source identities, grading-input hashes and every portable artifact hash "
              "are recorded in model-benchmarks.json. Interrupted model attempts are retained; resume starts a fresh "
              "attempt for that model and verifies completed models before skipping them."]
    (output / "benchmark-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=list(MODELS), action="append", help="repeat to select several; default: all three")
    parser.add_argument("--out", type=Path, help="new output directory outside the checkout")
    parser.add_argument("--list", action="store_true", help="list selections without building or solving")
    parser.add_argument("--resume", action="store_true", help="verify completed models, retry interrupted models in new attempt folders")
    args = parser.parse_args(argv)
    models = list(dict.fromkeys(args.model or MODELS))
    if args.list:
        for name in models:
            print(f"{name}: {MODELS[name][0]} — {MODELS[name][1]}")
        return 0
    if args.out is None:
        parser.error("--out is required to collect fields")
    output = args.out.resolve()
    if output.is_relative_to(ROOT):
        parser.error("Keep benchmark evidence outside the checkout")
    if not args.resume and output.exists():
        parser.error("Output already exists; use a new directory or --resume")
    if args.resume and not (output / STATE_FILE).is_file():
        parser.error("--resume needs a registered model-benchmark directory")
    with run_lock(output):
        if args.resume:
            state = read(output / STATE_FILE)
            if args.model is None:
                models = state["models"]
            if not models or any(m not in MODELS for m in models) or len(models) != len(set(models)):
                raise ValueError("Invalid registered model selection")
        expected = current_identity(models)
        if args.resume:
            if state["schema"] != SCHEMA or state["models"] != models or state["identity"] != expected:
                raise ValueError("Resume selection or execution identity differs from the registered run")
            for entry in state["results"].values():
                verify_completed(output, entry)
            for name, digest in expected["grading_inputs"].items():
                if sha(output / "frozen-inputs" / name) != digest:
                    raise ValueError("Frozen model grading inputs changed")
        else:
            state = {"schema": SCHEMA, "started_utc": now(), "models": models, "identity": expected,
                     "states": dict.fromkeys(models, "PENDING"), "attempts": {m: [] for m in models}, "results": {}}
            for name in expected["grading_inputs"]:
                target = output / "frozen-inputs" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
                if sha(target) != expected["grading_inputs"][name]:
                    raise ValueError("Model grading inputs changed while freezing")
        state["complete"] = False
        verify_identity(expected, models)
        write(output / STATE_FILE, state)
        for model in models:
            if model in state["results"]:
                print(f"Verified {model}; skipping its fields", flush=True)
                continue
            directory = f"{model}/attempt-{len(state['attempts'][model]) + 1}"
            folder = output / directory
            folder.mkdir(parents=True, exist_ok=False)
            attempt = {"directory": directory, "started_utc": now(), "status": "RUNNING"}
            if state["attempts"][model] and state["attempts"][model][-1]["status"] == "RUNNING":
                state["attempts"][model][-1].update(status="INTERRUPTED", finished_utc=now())
            state["attempts"][model].append(attempt)
            state["states"][model] = "RUNNING"
            write(output / STATE_FILE, state)
            try:
                for index, (module, arguments) in enumerate(commands(model, folder), 1):
                    verify_identity(expected, models)
                    print(f"{model}: {module} (step {index}); log {folder / f'step-{index}.txt'}", flush=True)
                    code = run_step(module, arguments, folder, index)
                    verify_identity(expected, models)
                    # A completed scientific evaluation may fail its gates.
                    if code != 0 and not (module in {"tools.report_prius_benchmark", "tools.run_benchmarks"} and code == 1):
                        raise RuntimeError(f"{module} exited {code}; see step-{index}.txt")
                result = model_result(model, folder)
                state["results"][model] = {"directory": directory, "result": result, "artifacts": inventory(folder)}
                attempt.update(status="COMPLETE", finished_utc=now())
                state["states"][model] = "COMPLETE"
            except BaseException:
                attempt.update(status="INTERRUPTED_OR_FAILED", finished_utc=now())
                state["states"][model] = "INCOMPLETE"
                raise
            finally:
                write(output / STATE_FILE, state)
                write_index(output, state)
        verify_identity(expected, models)
        state.update(complete=True, finished_utc=now())
        write(output / STATE_FILE, state)
    return int(any(entry["result"]["status"] in {"FAIL", "INCOMPLETE", "NOT_COMPARED"} for entry in state["results"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
