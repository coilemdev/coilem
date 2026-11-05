"""Produce resumable, hashed FEMM angle/current evidence using an owned COM server.

Run with the developer's existing pyFEMM/win32com Python, not the app runtime.
No installation, public API, or application dependency is changed.
"""
from __future__ import annotations

import argparse
import gc
import gzip
import hashlib
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from backend.experimental.femm_outrunner import SOURCE_SHA256
from backend.experimental.outrunner_sweep import SLIDING_SOURCE_SHA256, SweepCase, initial_cases


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    import femm
    import win32com.client

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=48)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--case-timeout", type=float, default=180)
    parser.add_argument("--reuse-from", type=Path, help="Copy only identical verified completed requests from a prior producer run")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cases = [SweepCase.from_dict(x) for x in json.loads(args.manifest.read_text())["cases"]] if args.manifest else initial_cases(args.samples)
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Case IDs must be unique")
    sources = {"full": args.source_dir/"WholeMotor.fem", "sliding": args.source_dir/"WholeMotorSlidingBand.fem"}
    expected = {"full": SOURCE_SHA256, "sliding": SLIDING_SOURCE_SHA256}
    for name, path in sources.items():
        if digest(path) != expected[name]:
            raise ValueError(f"Source hash mismatch: {path}")
    manifest = {"schema": "femm_outrunner_sweep/v1", "source_sha256": expected, "cases": [case.to_dict() for case in cases],
                "angle": "CCW mechanical, outer body", "gap_torque_to_outer_body_sign": -1,
                "bemf": "induced e=-omega_mechanical*d(lambda)/d(theta_mechanical); normalize 1000 rpm"}
    manifest_path = args.out/"manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != json.loads(json.dumps(manifest)):
        raise ValueError("Existing output belongs to a different request")
    write_json(manifest_path, manifest)
    if args.reuse_from:
        previous_manifest = json.loads((args.reuse_from/"manifest.json").read_text())
        if previous_manifest["source_sha256"] != expected:
            raise ValueError("Reused FEMM sources differ")
        previous_cases = {x["id"]: x for x in previous_manifest["cases"]}
        for case in cases:
            old_folder, new_folder = args.reuse_from/case.id, args.out/case.id
            if case.to_dict() != previous_cases.get(case.id) and json.loads(json.dumps(case.to_dict())) != previous_cases.get(case.id):
                continue
            if new_folder.exists() or not (old_folder/"result.json").exists():
                continue
            row = json.loads((old_folder/"result.json").read_text())
            if row["status"] != "COMPLETE" or row["case"] != previous_cases[case.id]:
                continue
            if digest(old_folder/"model.ans.gz") != row["answer_archive_sha256"] or digest(old_folder/"model.fem") != row["model_sha256"]:
                raise ValueError("Reused reference evidence changed")
            with gzip.open(old_folder/"model.ans.gz", "rb") as stream:
                if hashlib.sha256(stream.read()).hexdigest() != row["answer_sha256"]:
                    raise ValueError("Reused uncompressed answer changed")
            new_folder.mkdir()
            for name in ("result.json", "model.fem", "model.ans.gz"):
                shutil.copy2(old_folder/name, new_folder/name)
            write_json(new_folder/"reuse.json", {"from": str(old_folder.resolve()), "exact_case_and_evidence_verified": True})

    def femm_processes():
        # Run process inventory outside pyFEMM's COM apartment. Its server
        # shutdown can invalidate later WMI moniker access in that apartment.
        command = (
            "Get-CimInstance Win32_Process -Filter \"Name='femm.exe'\" | "
            "Select-Object ProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().Ticks.ToString()}} | "
            "ConvertTo-Json -Compress"
        )
        process = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                                 capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        rows = json.loads(process.stdout) if process.stdout.strip() else []
        if isinstance(rows, dict):
            rows = [rows]
        return {int(row["ProcessId"]): row["Created"] for row in rows}

    before = femm_processes()
    femm.HandleToFEMM = win32com.client.DispatchEx("femm.ActiveFEMM")
    owned = {pid: created for pid, created in femm_processes().items() if pid not in before}
    if len(owned) != 1:
        raise RuntimeError("Could not establish exclusive ownership of the FEMM server; refusing process termination")
    pid, created = next(iter(owned.items()))
    write_json(args.out/"producer-session.json", {"owned_femm_pid": pid, "creation_date": created, "status": "RUNNING"})

    def terminate_owned():
        command = (
            f"$ownedServer = Get-CimInstance Win32_Process -Filter \"ProcessId={pid} AND Name='femm.exe'\"; "
            f"if ($ownedServer -and $ownedServer.CreationDate.ToUniversalTime().Ticks.ToString() -eq '{created}') {{ "
            f"Get-CimInstance Win32_Process -Filter \"ParentProcessId={pid}\" | "
            "Where-Object { $_.Name -in @('fkn.exe','triangle.exe') } | Invoke-CimMethod -MethodName Terminate | Out-Null; "
            "$ownedServer | Invoke-CimMethod -MethodName Terminate | Out-Null }"
        )
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                       capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)

    try:
        femm.callfemm("setcompatibilitymode(0)")
        for case in cases:
            folder = args.out/case.id
            if folder.exists() and any(folder.iterdir()) and not (folder/"result.json").exists():
                # Preserve work interrupted by an app/session crash before
                # starting another attempt; completed cases are immutable.
                interrupted = folder.with_name(folder.name+f"_interrupted_{time.time_ns()}")
                folder.rename(interrupted)
            folder.mkdir(exist_ok=True)
            result_path = folder/"result.json"
            if result_path.exists():
                result = json.loads(result_path.read_text())
                if result["status"] == "COMPLETE" and result["case"] == json.loads(json.dumps(case.to_dict())):
                    archive = folder/"model.ans.gz"
                    if digest(archive) != result["answer_archive_sha256"]:
                        raise ValueError("Retained answer archive hash mismatch")
                    continue
                raise ValueError(f"Retain failed attempt and use a new directory: {folder}")
            timer = threading.Timer(args.case_timeout, terminate_owned)
            timer.daemon = True
            timer.start()
            start = time.monotonic()
            try:
                femm.opendocument(str(sources[case.reference_model].resolve()))
                for phase, current in zip("ABC", case.currents_A):
                    femm.mi_setcurrent(phase, current)
                if case.reference_model == "full":
                    if case.angle_ccw_deg:
                        femm.mi_selectgroup(2)
                        femm.mi_moverotate(0, 0, case.angle_ccw_deg)
                        femm.mi_clearselected()
                else:
                    femm.mi_modifyboundprop("myGap", 11, case.angle_ccw_deg)
                model = folder/"model.fem"
                femm.mi_saveas(str(model.resolve()))
                femm.mi_analyze(1)
                femm.mi_loadsolution()
                circuits = {phase: list(femm.mo_getcircuitproperties(phase)) for phase in "ABC"}
                femm.mo_clearblock()
                femm.mo_groupselectblock(2)
                wst = float(femm.mo_blockintegral(22))
                gap = float(femm.mo_gapintegral("myGap", 0)) if case.reference_model == "sliding" else None
                femm.mo_close()
                femm.mi_close()
                answer = folder/"model.ans"
                answer_sha = digest(answer)
                archive = folder/"model.ans.gz"
                with answer.open("rb") as src, gzip.open(archive, "wb", compresslevel=3) as dest:
                    shutil.copyfileobj(src, dest)
                with gzip.open(archive, "rb") as src:
                    if hashlib.sha256(src.read()).hexdigest() != answer_sha:
                        raise RuntimeError("Answer compression verification failed")
                answer.unlink()
                row = {"status": "COMPLETE", "case": case.to_dict(), "circuits": circuits,
                       "phase_linkage_Wb": [circuits[p][2] for p in "ABC"], "rotor_wst_raw_Nm": wst,
                       "gap_torque_raw_Nm": gap, "outer_rotor_torque_Nm": -gap if gap is not None else wst,
                       "source_sha256": expected[case.reference_model], "model_sha256": digest(model),
                       "answer_sha256": answer_sha, "answer_archive_sha256": digest(archive), "elapsed_s": time.monotonic()-start}
                write_json(result_path, row)
                print(json.dumps({"id": case.id, "torque_Nm": row["outer_rotor_torque_Nm"], "elapsed_s": row["elapsed_s"]}), flush=True)
            except Exception as exc:
                write_json(result_path, {"status": "ERROR", "case": case.to_dict(), "error": str(exc)})
                raise
            finally:
                timer.cancel()
    finally:
        timer = threading.Timer(10, terminate_owned)
        timer.daemon = True
        timer.start()
        try:
            femm.callfemm("quit()")
        except Exception:
            pass
        femm.HandleToFEMM = None
        gc.collect()
        time.sleep(0.2)
        terminate_owned()
        timer.cancel()
        write_json(args.out/"producer-session.json", {
            "owned_femm_pid": pid, "creation_date": created,
            "owned_process_exited": pid not in femm_processes(), "status": "CLOSED"})


if __name__ == "__main__":
    main()
