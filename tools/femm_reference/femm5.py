"""FEMM 5 (femm-qt) execution for the preserved E/F collectors on macOS or Linux.

FEMM 5 replaces FEMM 4.2's Windows ActiveX server with TCP and ships a
drop-in pyFEMM binding. Importing this module swaps only the execution hooks
the Windows collectors use: owned COM processes (`automation.Automation`),
the binary/dependency checks in `runtime`, and the launched-executable proof
in `phase_f`. Lowering, meshes, materials, extraction and normalization are
unchanged. Records name the FEMM 5 build and stay REVIEW_REQUIRED.

Use the producers `femm5_e_producer.py` and `femm5_f_producer.py` with
`tools.run_reference_positions`; set COILEM_FEMM5_APP to the femm_gui.app
bundle if it is not in ~/Applications. The `_ma33` producers (or
COILEM_FEMM5_MIN_ANGLE for direct collectors) replace the adapters' default
30 degree mesh minimum angle with 33 degrees; records name the override.
"""

from __future__ import annotations

import collections
import hashlib
import importlib.util
import os
import platform
import plistlib
import socket
import subprocess
import sys
import time
from pathlib import Path

from tools.femm_reference import automation, phase_f, runtime

APP = Path(os.environ.get("COILEM_FEMM5_APP", "~/Applications/femm_gui.app")).expanduser().resolve()
EXECUTABLES = APP / "Contents" / "MacOS"
BINDING = APP / "Contents" / "Resources" / "bindings" / "pyfemm" / "femm.py"
original_identity = runtime.identity

# Optional FEMM 5 mesh-quality override. The E/F/G adapters pass FEMM's
# default 30 degree minimum angle (or omit it). FEMM 5's mesher makes coarser
# meshes than FEMM 4.2's Triangle at the same angle; 33 degrees gives about
# FEMM 4.2's element counts. None leaves every adapter call unchanged.
# The positions runner strips COILEM_* from its workers, so its producers set
# the value in code (femm5_*_producer_ma33.py); direct collectors may use the
# environment variable, which is read at import because they clear COILEM_*.
ADAPTER_MIN_ANGLE_DEG = 30.0
MIN_ANGLE_DEG = None


def set_min_angle(value):
    global MIN_ANGLE_DEG
    value = None if value in (None, "") else float(value)
    if value is not None and not 1.0 <= value <= 33.8:
        raise ValueError("The FEMM 5 minimum angle must be between 1 and 33.8 degrees")
    MIN_ANGLE_DEG = value


set_min_angle(os.environ.get("COILEM_FEMM5_MIN_ANGLE"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build():
    info = plistlib.loads((APP / "Contents" / "Info.plist").read_bytes())
    signature = subprocess.run(["codesign", "-dv", "--verbose=2", str(APP)], capture_output=True, text=True)
    team = [line for line in signature.stderr.splitlines() if line.startswith(("Authority=Developer ID Application", "TeamIdentifier="))]
    return {"version": info.get("CFBundleShortVersionString"), "bundle_id": info.get("CFBundleIdentifier"), "signature": team}


def binary_hashes(*, required=False):
    names = ("femm_headless", "fkn")
    if not BINDING.is_file() or not all((EXECUTABLES / name).is_file() for name in names):
        if required:
            raise ValueError(f"FEMM 5 not found at {APP}; set COILEM_FEMM5_APP to the femm_gui.app bundle")
        return None
    hashes = {name: sha(EXECUTABLES / name) for name in names}
    hashes["bindings/pyfemm/femm.py"] = sha(BINDING)
    return hashes


def check_environment():
    if sys.platform == "win32":
        raise ValueError("Use the FEMM 4.2 COM collectors on Windows")
    binary_hashes(required=True)
    for name in ("numpy", "pydantic"):
        if importlib.util.find_spec(name) is None:
            raise ValueError("Missing FEMM reference dependency: " + name)


def identity(phase):
    value = original_identity(phase)
    import numpy
    import pydantic

    value.update(
        femm_binaries=binary_hashes(),
        femm_build=build(),
        dependencies={"numpy": numpy.__version__, "pydantic": pydantic.VERSION, "femm_binding": "FEMM 5 bundled pyfemm"},
        execution="femm5_owned_headless_tcp_v1",
        femm5_execution_sha256=sha(Path(__file__)),
        mesh_override=None if MIN_ANGLE_DEG is None else {
            "min_angle_deg": MIN_ANGLE_DEG, "replaces_adapter_min_angle_deg": ADAPTER_MIN_ANGLE_DEG,
            "reason": "FEMM 5 mesher is coarser than FEMM 4.2 at the default angle"},
        platform={"system": platform.system(), "release": platform.release(), "mac_ver": platform.mac_ver()[0], "machine": platform.machine()},
    )
    return value


def femm_module():
    loaded = sys.modules.get("femm")
    if loaded is not None:
        assert Path(loaded.__file__).resolve() == BINDING, ("another femm module is loaded", loaded.__file__)
        return loaded
    spec = importlib.util.spec_from_file_location("femm", BINDING)
    module = importlib.util.module_from_spec(spec)
    sys.modules["femm"] = module
    spec.loader.exec_module(module)
    module.windowsOS = True  # no Wine file link: the vendored adapters' file-link guards stay off
    module.fixpath = module._fixpath
    module.mi_probdef = probdef_with_min_angle(module.mi_probdef)
    return module


def probdef_with_min_angle(probdef):
    """Replace only the adapters' default minimum angle; any other value is refused."""

    def call(*args):
        if MIN_ANGLE_DEG is None:
            return probdef(*args)
        args = list(args)
        if len(args) == 5:
            args.append(MIN_ANGLE_DEG)
        elif len(args) >= 6 and float(args[5]) == ADAPTER_MIN_ANGLE_DEG:
            args[5] = MIN_ANGLE_DEG
        else:
            raise ValueError(f"Unexpected mi_probdef arguments for the FEMM 5 min-angle override: {args}")
        return probdef(*args)

    return call


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Automation:
    """One owned femm_headless per open; same records as the COM automation."""

    def __init__(self, directory):
        check_environment()
        self.femm = femm_module()
        self.directory = directory
        self.calls = collections.defaultdict(lambda: {"count": 0, "elapsed_s": 0.0, "max_s": 0.0})
        self.sessions = []
        self.live = []
        self.session_class = self.femm.FemmSession
        self.original_call = self.session_class.callfemm
        self.original_open = self.femm.openfemm
        self.original_close = self.femm.closefemm
        owner = self

        def call(session, command):
            name = command.split("(", 1)[0].strip()
            started = time.perf_counter()
            try:
                return owner.original_call(session, command)
            finally:
                elapsed = time.perf_counter() - started
                entry = owner.calls[name]
                entry["count"] += 1
                entry["elapsed_s"] += elapsed
                entry["max_s"] = max(entry["max_s"], elapsed)

        self.session_class.callfemm = call
        self.femm.openfemm = self.open
        self.femm.closefemm = self.close_session

    def open(self, *args, **kwargs):
        if self.femm._default is not None:
            raise RuntimeError("A FEMM 5 session is already open for this worker")
        started = time.perf_counter()
        os.environ["FEMM_DIR"] = str(EXECUTABLES)
        port = free_port()
        session = self.session_class(port=port, headless=True)
        process = session._proc
        if process is None:
            session.close()
            raise RuntimeError(f"Port {port} reached a FEMM instance this worker did not start")
        executable = subprocess.run(["ps", "-o", "comm=", "-p", str(process.pid)], capture_output=True, text=True).stdout.strip()
        if Path(executable).resolve() != (EXECUTABLES / "femm_headless").resolve():
            session.close()
            raise ValueError(f"Launched an unexpected FEMM executable: {executable}")
        self.femm._default = session
        self.live.append(session)
        self.sessions.append({"pid": process.pid, "port": port, "executable": str(Path(executable).name),
                              "startup_s": time.perf_counter() - started})
        runtime.write(self.directory / "automation.json", {"worker_pid": os.getpid(), "sessions": self.sessions})
        return session

    def close_session(self):
        session = self.femm._default
        self.femm._default = None
        if session is not None:
            self.stop(session)

    def stop(self, session):
        process = session._proc
        try:
            session.close()
        finally:
            if process is not None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                for record in self.sessions:
                    if record["pid"] == process.pid:
                        record["exit_code"] = process.returncode
            if session in self.live:
                self.live.remove(session)

    def close(self):
        try:
            for session in list(self.live):
                self.stop(session)
            self.femm._default = None
            runtime.write(self.directory / "automation.json", {
                "worker_pid": os.getpid(), "sessions": self.sessions,
                "transport": "FEMM 5 TCP binding; one owned femm_headless per open, killed on close",
                "commands": dict(sorted(self.calls.items(), key=lambda item: -item[1]["elapsed_s"])),
            })
        finally:
            self.session_class.callfemm = self.original_call
            self.femm.openfemm = self.original_open
            self.femm.closefemm = self.original_close


def actual_session_identity(owner, expected):
    session = dict(owner.sessions[-1])
    actual = binary_hashes(required=True)
    return {**session, "actual_femm5_binary_sha256": actual}


def femm_version():
    return "FEMM " + str(build()["version"])


ANSWER_COMPRESSION = "xz -6 (lossless); <name>.ans.json records the original bytes and SHA-256"


def compress_answer(file):
    """Compress one FEMM answer in place; return the compressed file and its original-hash record."""
    file = Path(file)
    record = file.with_name(file.name + ".json")
    record.write_text(json_dumps({"file": file.name, "bytes": file.stat().st_size, "sha256": sha(file),
                                  "compression": ANSWER_COMPRESSION}), encoding="utf-8")
    subprocess.run(["xz", "-6", "-T1", "--", str(file)], check=True)
    return [file.with_name(file.name + ".xz"), record]


def json_dumps(value):
    import json

    return json.dumps(value, indent=2) + "\n"


def compressed_answers(open_batch):
    """Wrap a producer's open_batch so retained FEMM answers are stored xz-compressed.

    FEMM 5 answers are 6-11 MB per position; the receipts then hash the
    compressed file plus a record of the original answer's bytes and SHA-256.
    `unxz` restores the exact answer FEMM wrote.
    """
    import contextlib

    @contextlib.contextmanager
    def wrapped(case_id, directory, prepared):
        with open_batch(case_id, directory, prepared) as measure:
            def measure_and_compress(position, point_dir):
                point, files = measure(position, point_dir)
                kept = []
                for file in files:
                    kept += compress_answer(file) if Path(file).suffix == ".ans" else [file]
                return point, kept

            yield measure_and_compress

    return wrapped


runtime.binary_hashes = binary_hashes
runtime.check_environment = check_environment
runtime.identity = identity
automation.Automation = Automation
automation.femm_module = femm_module
automation.binary_hashes = binary_hashes
automation.check_environment = check_environment
phase_f.actual_session_identity = actual_session_identity
