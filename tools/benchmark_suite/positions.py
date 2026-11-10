"""Immutable per-position evidence; independent process batches; advisory progress.

External producers implement identity(), cases(), prepare(case_id),
open_batch(case_id, directory, prepared) (a context manager yielding a function
measure(position, directory)), and assemble(case_id, points, prepared).
measure returns (JSON point, list of evidence files). No application imports:
each producer may own an incompatible backend namespace in its worker process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from collections import Counter
from pathlib import Path

from tools.benchmark_suite.external import load_producer, producer_imports, safe_id, stop
from tools.benchmark_suite.external_contract import ROOT, json_bytes, now, read, run_lock, sha, write

SCHEMA = "coilem.reference_positions/v1"


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def immutable(path, payload):
    """Publish a flushed, checksummed document atomically without replacement."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
    try:
        with temporary.open("xb") as stream:
            stream.write(json_bytes({"sha256": canonical(payload), "payload": payload}))
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and refuses an existing destination on
        # Windows and POSIX. Both names are on the same volume/directory.
        deadline = time.monotonic() + 3
        while True:
            try:
                os.link(temporary, path)
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in (5, 32, 33) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
    finally:
        temporary.unlink(missing_ok=True)


def unseal(path):
    value = read(path)
    if not isinstance(value, dict) or value.get("sha256") != canonical(value.get("payload")):
        raise ValueError(f"Evidence checksum mismatch: {path}")
    return value["payload"]


def contained(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("Evidence paths must be relative")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError("Evidence path escaped the run")
    return path


def advisory(path, value):
    """A status observer or sharing failure cannot cancel committed field work."""
    try:
        write(path, value)
        return True
    except OSError as exc:
        print(f"Advisory status unavailable: {exc}", file=sys.stderr, flush=True)
        return False


def producer_identity(module, path):
    with producer_imports(path):
        physical = module.identity()
    return json.loads(json.dumps({"producer": physical, "producer_sha256": sha(path),
        "runner_sources": {name: sha(ROOT / name) for name in (
            "tools/benchmark_suite/positions.py", "tools/benchmark_suite/external.py",
            "tools/benchmark_suite/external_contract.py", "tools/run_reference_positions.py")},
        "python": sys.version, "python_executable_sha256": sha(sys.executable)}, allow_nan=False))


def registration(producers, selection_path):
    catalog, sources = {}, {}
    for path in producers:
        path = path.resolve()
        module = load_producer(path)
        identity = producer_identity(module, path)
        with producer_imports(path):
            cases = module.cases()
        if not isinstance(cases, dict) or not cases:
            raise ValueError("Producer cases() must return a nonempty mapping")
        source_key = str(path)
        sources[source_key] = identity
        for case_id, case in cases.items():
            safe_id(case_id)
            if case_id.casefold() in {key.casefold() for key in catalog}:
                raise ValueError("Case identifiers collide")
            if not isinstance(case, dict) or not isinstance(case.get("positions"), list) or not case["positions"]:
                raise ValueError("Each case needs registered positions")
            seen = set()
            for position in case["positions"]:
                safe_id(position["id"])
                if position["id"].casefold() in seen:
                    raise ValueError("Position identifiers collide")
                seen.add(position["id"].casefold())
                duration = position.get("estimated_s", 0)
                if type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0:
                    raise ValueError("Position timing must be finite and nonnegative")
            catalog[case_id] = {"producer_path": source_key, **case}
    selection = read(selection_path) if selection_path else {key: [p["id"] for p in c["positions"]] for key, c in catalog.items()}
    if not isinstance(selection, dict) or not selection or set(selection) - catalog.keys():
        raise ValueError("Selection has unknown cases")
    for case_id, positions in selection.items():
        allowed = {p["id"] for p in catalog[case_id]["positions"]}
        if not isinstance(positions, list) or not positions or len(set(positions)) != len(positions) or set(positions) - allowed:
            raise ValueError("Selection has duplicate or unknown positions")
    selected = {key: catalog[key] for key in sorted(selection)}
    needed = {c["producer_path"] for c in selected.values()}
    return {"schema": SCHEMA, "sources": {k: v for k, v in sources.items() if k in needed},
            "cases": selected, "selection": selection}


def validate_receipt(root, case_id, position, contract):
    path = root / "positions" / case_id / (position["id"] + ".json")
    if not path.exists():
        return None
    receipt = unseal(path)
    case = contract["cases"][case_id]
    if (receipt.get("contract_sha256") != canonical(contract) or receipt.get("case_id") != case_id
            or receipt.get("position") != position or receipt.get("status") != "COMPLETE"
            or receipt.get("identity_before") != contract["sources"][case["producer_path"]]
            or receipt.get("identity_after") != receipt.get("identity_before")):
        raise ValueError(f"Position evidence binding changed: {case_id}/{position['id']}")
    if not receipt.get("artifacts"):
        raise ValueError("Position has no retained field artifacts")
    for artifact in receipt["artifacts"]:
        file = contained(root, artifact["path"])
        if file.stat().st_size != artifact["bytes"] or sha(file) != artifact["sha256"]:
            raise ValueError(f"Position artifact changed: {file}")
    return receipt


def selected_positions(contract, case_id):
    wanted = set(contract["selection"][case_id])
    return [p for p in contract["cases"][case_id]["positions"] if p["id"] in wanted]


def completed(root, contract):
    return {(case_id, p["id"]): value for case_id in contract["cases"]
            for p in selected_positions(contract, case_id)
            if (value := validate_receipt(root, case_id, p, contract)) is not None}


def batches(contract, done, batch_size):
    result = []
    for case_id in contract["cases"]:
        positions = [p for p in selected_positions(contract, case_id) if (case_id, p["id"]) not in done]
        for stage in dict.fromkeys(p.get("stage", "field") for p in positions):
            stage_positions = [p for p in positions if p.get("stage", "field") == stage]
            for start in range(0, len(stage_positions), batch_size):
                group = stage_positions[start:start + batch_size]
                result.append({"case_id": case_id, "positions": group,
                               "estimated_s": sum(p.get("estimated_s", 0) for p in group)})
    return sorted(result, key=lambda b: (-b["estimated_s"], b["case_id"], b["positions"][0]["id"]))


def check_identity(module, path, contract):
    identity = producer_identity(module, path)
    if identity != contract["sources"][str(path)]:
        raise ValueError("Producer, runner, solver, input or runtime identity changed")
    return identity


def worker(root, task_path):
    task = unseal(task_path)
    contract = unseal(root / "registration.json")["contract"]
    if task["contract_sha256"] != canonical(contract):
        raise ValueError("Worker task binding changed")
    case_id = task["case_id"]
    path = Path(contract["cases"][case_id]["producer_path"])
    module = load_producer(path)
    before = check_identity(module, path, contract)
    directory = task_path.parent
    started = time.perf_counter()
    try:
        with producer_imports(path):
            if task["mode"] == "prepare":
                prepared = module.prepare(case_id)
                check_identity(module, path, contract)
                immutable(root / "prepared" / (case_id + ".json"), {
                    "contract_sha256": canonical(contract), "case_id": case_id,
                    "identity": before, "data": prepared, "runtime_s": time.perf_counter() - started})
            else:
                preparation = unseal(root / "prepared" / (case_id + ".json"))
                if preparation["contract_sha256"] != canonical(contract) or preparation["identity"] != before:
                    raise ValueError("Preflight binding changed")
                if task["mode"] == "assemble":
                    points = []
                    for p in contract["cases"][case_id]["positions"]:
                        receipt = validate_receipt(root, case_id, p, contract)
                        if receipt is None:
                            raise ValueError("Cannot assemble an incomplete registered grid")
                        points.append(receipt["point"])
                    result = module.assemble(case_id, points, preparation["data"])
                    check_identity(module, path, contract)
                    immutable(root / "assembled" / (case_id + ".json"), {
                        "contract_sha256": canonical(contract), "case_id": case_id, "identity": before,
                        "full_registered_grid": True, "status": "COMPLETE", "result": result})
                else:
                    registered = {p["id"]: p for p in selected_positions(contract, case_id)}
                    with module.open_batch(case_id, directory, preparation["data"]) as measure:
                        for position in task["positions"]:
                            if registered.get(position["id"]) != position:
                                raise ValueError("Unregistered position in worker task")
                            if validate_receipt(root, case_id, position, contract) is not None:
                                continue
                            point_dir = directory / position["id"]
                            point_dir.mkdir(exist_ok=False)
                            tick = time.perf_counter()
                            point, files = measure(position, point_dir)
                            artifacts = []
                            for file in files:
                                file = Path(file).resolve()
                                if not file.is_relative_to(point_dir.resolve()) or not file.is_file() or file.is_symlink():
                                    raise ValueError("Producer returned an invalid field artifact")
                                artifacts.append({"path": file.relative_to(root).as_posix(),
                                                  "bytes": file.stat().st_size, "sha256": sha(file)})
                            after = check_identity(module, path, contract)
                            immutable(root / "positions" / case_id / (position["id"] + ".json"), {
                                "schema": SCHEMA, "status": "COMPLETE", "case_id": case_id,
                                "position": position, "contract_sha256": canonical(contract),
                                "identity_before": before, "identity_after": after,
                                "point": point, "artifacts": artifacts,
                                "runtime_s": time.perf_counter() - tick, "completed_at": now(), "batch": directory.name})
                            print(f"{case_id}/{position['id']}: committed", flush=True)
        immutable(directory / "outcome.json", {"status": "COMPLETE", "runtime_s": time.perf_counter() - started})
        return 0
    except BaseException as exc:
        immutable(directory / "failure.json", {"status": "ERROR", "error": str(exc),
                  "traceback": traceback.format_exc(), "runtime_s": time.perf_counter() - started})
        raise


def launch(root, task, contract):
    directory = root / "batches" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    task_path = directory / "task.json"
    immutable(task_path, {**task, "contract_sha256": canonical(contract)})
    log = (directory / "worker.log").open("xb")
    try:
        environment = {k: v for k, v in os.environ.items()
                       if k == "COILEM_FEMM_BIN" or not k.startswith(("OPENEM_", "COILEM_", "FEMM_"))}
        environment.update(PYTHONDONTWRITEBYTECODE="1", GIT_OPTIONAL_LOCKS="0")
        process = subprocess.Popen([sys.executable, "-B", "-u", "-m", "tools.benchmark_suite.positions",
            "--worker", "--out-dir", str(root), "--task", str(task_path)], cwd=ROOT, env=environment,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt",
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0)
    except BaseException:
        log.close()
        raise
    return {"process": process, "log": log, "task": task, "directory": directory, "started": time.monotonic()}


def run_pool(root, tasks, contract, args, *, interrupt=False):
    pending, running, outcomes = list(tasks), [], []
    started = time.monotonic()
    baseline = sum(1 for case in contract["cases"] for _ in (root / "positions" / case).glob("*.json"))
    status = "COMPLETE"
    session = uuid.uuid4().hex
    last_status, last_status_at = None, 0.0
    try:
        while pending or running:
            while pending and len(running) < args.workers:
                if shutil.disk_usage(root).free < args.min_free_gib * 1024 ** 3:
                    raise ValueError("Free-disk floor reached; committed positions retained")
                job = launch(root, pending.pop(0), contract)
                running.append(job)
                print(f"Starting {job['task']['mode']} {job['task']['case_id']} pid={job['process'].pid}", flush=True)
            for job in list(running):
                code = job["process"].poll()
                if code is None and time.monotonic() - job["started"] > args.timeout_s:
                    stop(job["process"])
                    code = job["process"].returncode
                if code is None:
                    continue
                job["log"].close()
                outcomes.append({"case_id": job["task"]["case_id"], "mode": job["task"]["mode"],
                                 "batch": job["directory"].name, "exit_code": code,
                                 "wall_s": time.monotonic() - job["started"]})
                running.remove(job)
            if any(o["exit_code"] != 0 for o in outcomes):
                status = "ERROR"
                break
            count = sum(1 for case in contract["cases"] for _ in (root / "positions" / case).glob("*.json"))
            status_key = (count, len(pending), tuple(j["process"].pid for j in running))
            if status_key != last_status or time.monotonic() - last_status_at >= 5:
                advisory(root / "status.json", {"status": "RUNNING", "committed_positions": count,
                         "pending_batches": len(pending), "active_pids": list(status_key[2]), "at": now()})
                last_status, last_status_at = status_key, time.monotonic()
            if interrupt and args.interrupt_after is not None and count - baseline >= args.interrupt_after:
                status = "INTERRUPTED_FOR_RESUME_TEST"
                break
            if pending or running:
                time.sleep(0.25)
    except BaseException:
        status = "INTERRUPTED"
        raise
    finally:
        for job in running:
            stop(job["process"])
            job["log"].close()
        record = {"status": status, "workers": args.workers, "batch_size": args.batch_size,
                  "wall_s": time.monotonic() - started, "outcomes": outcomes, "completed_at": now(),
                  "stopped_batches": [j["directory"].name for j in running]}
        immutable(root / "sessions" / (session + ".json"), record)
    return record


def execute(args):
    if not 1 <= args.workers <= 16 or not 1 <= args.batch_size <= 8:
        raise ValueError("Use 1..16 workers and 1..8 positions per process batch")
    if not math.isfinite(args.timeout_s) or args.timeout_s <= 0 or not math.isfinite(args.min_free_gib) or args.min_free_gib < 0:
        raise ValueError("Timeout and disk floor must be finite and positive/nonnegative")
    if args.interrupt_after is not None and args.interrupt_after < 1:
        raise ValueError("Interruption threshold must be positive")
    root = args.out_dir.resolve()
    contract = registration(args.producer, args.selection)
    with run_lock(root):
        path = root / "registration.json"
        if path.exists():
            if not args.resume or unseal(path)["contract"] != contract:
                raise ValueError("Existing run needs --resume with identical sources, requests and selection")
        else:
            if args.resume or any(p.name != "run.lock" for p in root.iterdir()):
                raise ValueError("New collection needs an empty directory")
            immutable(path, {"contract": contract, "created_at": now()})
        done = completed(root, contract)  # Hash-verify field bytes before trusting any checkpoint.
        prepare = []
        for case_id, case in contract["cases"].items():
            prepared_path = root / "prepared" / (case_id + ".json")
            if prepared_path.exists():
                prepared = unseal(prepared_path)
                if (prepared["contract_sha256"] != canonical(contract)
                        or prepared["identity"] != contract["sources"][case["producer_path"]]):
                    raise ValueError("Preflight binding changed")
            else:
                prepare.append({"case_id": case_id, "mode": "prepare"})
        if prepare and run_pool(root, prepare, contract, args)["status"] != "COMPLETE":
            return 2
        if args.prepare_only:
            return 0
        pending = batches(contract, done, args.batch_size)
        print(f"Verified {len(done)} committed positions; scheduling {len(pending)} batches", flush=True)
        session = run_pool(root, [{**b, "mode": "measure"} for b in pending], contract, args, interrupt=True)
        if session["status"] != "COMPLETE":
            return 130 if session["status"].startswith("INTERRUPTED") else 2
        done = completed(root, contract)
        expected = sum(len(p) for p in contract["selection"].values())
        if len(done) != expected:
            raise ValueError("Workers exited without all required position receipts")
        assemble = []
        for case_id, case in contract["cases"].items():
            full = len(contract["selection"][case_id]) == len(case["positions"])
            assembled_path = root / "assembled" / (case_id + ".json")
            if full:
                if assembled_path.exists():
                    assembled = unseal(assembled_path)
                    if (assembled["contract_sha256"] != canonical(contract) or assembled["case_id"] != case_id
                            or assembled["identity"] != contract["sources"][case["producer_path"]]
                            or not assembled["full_registered_grid"] or assembled["status"] != "COMPLETE"):
                        raise ValueError("Assembled reference binding changed")
                else:
                    assemble.append({"case_id": case_id, "mode": "assemble"})
        if assemble and run_pool(root, assemble, contract, args)["status"] != "COMPLETE":
            return 2
        result = {"status": "COMPLETE", "scope": "FULL_COLLECTION" if all(
            len(contract["selection"][k]) == len(c["positions"]) for k, c in contract["cases"].items()) else "NON_GATING_PILOT",
            "committed_positions": len(done), "resumed_positions": len(done) - sum(len(b["positions"]) for b in pending),
            "workers": args.workers, "batch_size": args.batch_size,
            "phase_counts": dict(Counter(contract["cases"][key[0]]["phase"] for key in done)),
            "measurement_session": session, "contract_sha256": canonical(contract), "completed_at": now()}
        immutable(root / "completions" / (uuid.uuid4().hex + ".json"), result)
        advisory(root / "status.json", result)
        print(json.dumps({k: v for k, v in result.items() if k != "measurement_session"}), flush=True)
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", type=Path, action="append", default=[])
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--selection", type=Path, help="Optional case -> registered position IDs; partial grids are NON_GATING_PILOT")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--timeout-s", type=float, default=7200)
    parser.add_argument("--min-free-gib", type=float, default=20)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--interrupt-after", type=int, help="Pilot fault injection: stop own workers after N new position commits")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--task", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            return worker(args.out_dir.resolve(), args.task.resolve())
        if not args.producer:
            raise ValueError("At least one external --producer is required")
        return execute(args)
    except (ValueError, OSError) as exc:
        print(f"Position collection refused: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; immutable position checkpoints retained.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
