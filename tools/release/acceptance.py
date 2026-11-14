"""Installed-package acceptance test for a coilEM wheel, independent of any checkout.

Installs the wheel into a fresh virtual environment in a temporary directory,
with PATH, HOME and CARGO set so neither Cargo nor Node can be found, launches
the installed ``coilem --no-browser`` and checks, through HTTP only:

- the UI index, a hashed asset and a deep link; a 404 for an unknown API path;
- that the launcher and health report the installed distribution version;
- that ``coilem benchmark --quick --list`` reads the packaged suite and records;
- a motor Preview solve, cylindrical and linear Halbach solves and a lesson solve;
- the saved run's PDF, CSV and replay-package downloads;
- that a second launch reuses the running server;
- that Ctrl+C (CTRL_BREAK_EVENT on Windows) during a solve, once the solve
  stream reports Magneto2D at work, stops the server, leaves no Magneto2D
  process behind and records the run as cancelled.

This file uses only the standard library and carries its own inputs, so copy it
anywhere and run it with the Python version under test:

    python -I acceptance.py --install WHEEL_OR_REQUIREMENT [--keep]

To test a published release, ``--index-url`` downloads the coilEM wheel from
that index (for example TestPyPI) and ``--expect-sha256`` checks it is the
wheel CI built. Its dependencies still come from PyPI, never from that index.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# A new upload reaches the index's /simple/ pages within its 10-minute CDN cache; wait 25 minutes.
INDEX_ATTEMPTS = 50
INDEX_WAIT_S = 30


class IndexApiUnusable(Exception):
    """The index's JSON API can't be used from this machine; pip is the fallback."""


WINDOWS = os.name == "nt"
# Copies of tests/fixtures/spm_4p12s_simple.json and the schemas/v1/examples
# Halbach configurations; tests/test_release_tools.py keeps them in sync.
MOTOR = json.loads("""
{
  "materials": {
    "conductor": "copper",
    "magnet_grade": "N42",
    "rotor_steel": "M350-50A",
    "stator_steel": "M350-50A"
  },
  "rotor": {
    "OD_mm": 25.0,
    "barrier_widths_mm": null,
    "bridge_thickness_mm": 1.0,
    "flux_barrier_count": null,
    "magnet_embrace": 0.85,
    "magnet_thickness_mm": 3.0,
    "magnet_width_mm": 16.5,
    "pole_count": 4
  },
  "schema_version": "1.0",
  "solve_options": null,
  "solve_params": {
    "current_amplitude_A": 10.0,
    "current_amplitude_convention": "rms",
    "current_angle_deg": 0.0,
    "mesh_density": "normal",
    "mesh_source": "native",
    "mesher": "gmsh",
    "rated_speed_rpm": 3000,
    "rotor_rotation_model": "remesh_per_step",
    "rotor_step_deg": 30.0,
    "rotor_sweep_range_deg": 180,
    "solve_quality": "quick",
    "torque_method": "contour"
  },
  "stator": {
    "ID_mm": 34.0,
    "OD_mm": 50.0,
    "slot_count": 12,
    "slot_opening_mm": 2.5,
    "stack_length_mm": 40.0,
    "tooth_width_mm": 4.5,
    "yoke_thickness_mm": 4.5
  },
  "topology": "SPM",
  "winding": {
    "layers": 1,
    "parallel_paths": 1,
    "turns_per_coil": 10,
    "type": "concentrated"
  }
}
""")
CYLINDRICAL_HALBACH = json.loads("""
{
  "array": {
    "field_direction": 0.0,
    "field_mode": "internal",
    "multipole_order": 1
  },
  "geometry": {
    "axial_length": 100.0,
    "inner_radius": 25.0,
    "outer_radius": 50.0,
    "segment_count": 16,
    "segment_gap_angle": 0.0,
    "segment_start_angle": 0.0
  },
  "kind": "halbach_array_config",
  "magnet": {
    "grade": "N42",
    "source": "catalog",
    "temperature_c": 20.0
  },
  "sample_region": {
    "angular_samples": 96,
    "leakage_probe_radius": 75.0,
    "radial_samples": 31,
    "radius": 20.0
  },
  "solve": {
    "field_line_count": 18,
    "linear": {
      "max_iterations": 5000,
      "pcg_preconditioner": "incomplete_cholesky",
      "solver": "direct",
      "tolerance": 1e-08
    },
    "mesh": {
      "corner_refinement": true,
      "density": "normal",
      "minimum_elements_across_magnet": 6,
      "outer_boundary_radius_factor": 4.0
    },
    "quality": "standard"
  },
  "units": {
    "angle": "deg",
    "length": "mm"
  },
  "version": "1.0"
}
""")
LINEAR_HALBACH = json.loads("""
{
  "array": {
    "phase_deg": 0.0,
    "strong_side": "positive_y"
  },
  "geometry": {
    "block_gap": 0.0,
    "block_width": 10.0,
    "magnet_height": 10.0,
    "out_of_plane_depth": 100.0,
    "period_count": 4
  },
  "kind": "linear_halbach_array_config",
  "magnet": {
    "grade": "N42",
    "source": "catalog",
    "temperature_c": 20.0
  },
  "sample_region": {
    "edge_exclusion_periods": 1,
    "probe_offset": 5.0,
    "samples_per_period": 64
  },
  "solve": {
    "field_line_count": 18,
    "linear": {
      "max_iterations": 5000,
      "pcg_preconditioner": "incomplete_cholesky",
      "solver": "direct",
      "tolerance": 1e-08
    },
    "mesh": {
      "corner_refinement": true,
      "density": "normal",
      "minimum_elements_across_magnet": 6,
      "outer_padding_factor": 2.5
    },
    "quality": "standard"
  },
  "units": {
    "angle": "deg",
    "length": "mm"
  },
  "version": "1.0"
}
""")


class Acceptance:
    def __init__(self, work: Path) -> None:
        self.work = work
        self.venv = work / "venv"
        self.bin = self.venv / ("Scripts" if WINDOWS else "bin")
        self.data_root = work / "user-data"
        self.results: list[tuple[str, bool, str]] = []
        self.log: list[str] = []
        self.version: str | None = None
        home = work / "home"
        home.mkdir(parents=True, exist_ok=True)
        system = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        path = [str(self.bin), str(system / "System32"), str(system)] if WINDOWS else [str(self.bin), "/usr/bin", "/bin"]
        self.env = {
            "PATH": os.pathsep.join(path),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "CARGO": str(work / "no-cargo"),
            "COILEM_USER_DATA_ROOT": str(self.data_root),
            "PYTHONUNBUFFERED": "1",
        }
        for name in ("SystemRoot", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"):
            if name in os.environ:
                self.env[name] = os.environ[name]

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, ok, detail))
        print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)
        return ok

    def download(self, requirement: str, index_url: str, expected_sha256: str | None, python: str) -> str:
        """Fetch only the coilEM wheel from ``index_url``, retrying while a new upload propagates.

        The index's ``/simple/`` pages, which pip reads, are CDN-cached for ten minutes
        (``max-age=600``), so pip often missed a fresh upload for that whole window. Given
        the wheel CI built (``expected_sha256``) and a pinned version, take the wheel from
        the index's JSON API instead: it is current as soon as an upload finishes, and its
        file URLs are immutable. Otherwise fall back to pip, waiting past the cache window.
        """

        destination = self.work / "download"
        destination.mkdir(parents=True, exist_ok=True)
        name, _, version = requirement.partition("==")
        wheel = None
        if expected_sha256 is not None and version:
            try:
                wheel = self.download_by_digest(name.strip(), version.strip(), index_url, expected_sha256, destination)
            except IndexApiUnusable as reason:
                # The JSON API answered with something other than "not yet" or a server error
                # (TLS, DNS, proxy, malformed reply): fall back to pip rather than wait it out.
                print(f"cannot use the index JSON API ({reason}); falling back to pip", flush=True)
            else:
                if wheel is None:
                    return ""
        if wheel is None:
            wheel = self.pip_download(requirement, index_url, python, destination)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if expected_sha256 is not None:
            self.check("the published wheel is the one CI built", digest == expected_sha256, f"{wheel.name} {digest}")
        return str(wheel)

    def download_by_digest(self, name: str, version: str, index_url: str, expected_sha256: str, destination: Path) -> Path | None:
        """Download the wheel whose SHA-256 is ``expected_sha256`` via the index's JSON API."""

        api = f"{index_url.rstrip('/').rsplit('/simple', 1)[0]}/pypi/{name}/{version}/json"
        for attempt in range(INDEX_ATTEMPTS):
            try:
                with urllib.request.urlopen(api, timeout=60) as response:
                    files = json.load(response)["urls"]
                break
            except urllib.error.HTTPError as error:
                # 404: the upload hasn't propagated yet; 5xx: the index is struggling. Both are worth waiting for.
                if error.code != 404 and error.code < 500:
                    raise IndexApiUnusable(f"HTTP {error.code} from {api}") from error
                print(f"waiting for {name} {version} on {api} (attempt {attempt + 1}, HTTP {error.code})", flush=True)
                time.sleep(INDEX_WAIT_S)
            except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
                raise IndexApiUnusable(f"{type(error).__name__}: {error}") from error
        else:
            raise SystemExit(f"{name} {version} never appeared on {api}")
        match = next((f for f in files if f.get("packagetype") == "bdist_wheel" and f.get("digests", {}).get("sha256") == expected_sha256), None)
        if match is None:
            published = ", ".join(f"{f.get('filename')} {f.get('digests', {}).get('sha256')}" for f in files)
            self.check("the published wheel is the one CI built", False, f"no file with {expected_sha256}; published: {published}")
            return None
        wheel = destination / match["filename"]
        try:
            with urllib.request.urlopen(match["url"], timeout=300) as response:
                wheel.write_bytes(response.read())
        except (urllib.error.URLError, OSError) as error:
            raise IndexApiUnusable(f"cannot download {match['url']}: {error}") from error
        return wheel

    def pip_download(self, requirement: str, index_url: str, python: str, destination: Path) -> Path:
        command = [python, "-m", "pip", "download", "--no-deps", "--only-binary", ":all:", "--disable-pip-version-check"]
        command += ["--index-url", index_url, "--dest", str(destination), requirement]
        for attempt in range(INDEX_ATTEMPTS):
            completed = subprocess.run(command, capture_output=True, text=True)
            if completed.returncode == 0:
                break
            print(f"waiting for {requirement} on {index_url} (attempt {attempt + 1})", flush=True)
            time.sleep(INDEX_WAIT_S)
        else:
            raise SystemExit(f"could not download {requirement} from {index_url}:\n{completed.stderr}")
        return next(destination.glob("*.whl"))

    def install(self, requirement: str, python: str) -> None:
        subprocess.run([python, "-m", "venv", str(self.venv)], check=True)
        interpreter = self.bin / ("python.exe" if WINDOWS else "python")
        subprocess.run([str(interpreter), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", requirement], check=True)
        self.version = subprocess.check_output(
            [str(interpreter), "-I", "-c", "from importlib.metadata import version; print(version('coilem'))"],
            cwd=self.work, text=True,
        ).strip()
        reported = subprocess.run(
            [str(self.bin / ("coilem.exe" if WINDOWS else "coilem")), "--version"],
            cwd=self.work, env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.check(
            "launcher reports the installed version",
            reported.returncode == 0 and reported.stdout.strip() == f"coilEM {self.version}",
            (reported.stdout + reported.stderr).strip(),
        )
        missing = [tool for tool in ("cargo", "node", "npm") if shutil.which(tool, path=self.env["PATH"])]
        self.check("Cargo and Node are unavailable to the installed app", not missing, f"found={missing}")
        listed = subprocess.run(
            [str(self.bin / ("coilem.exe" if WINDOWS else "coilem")), "benchmark", "--quick", "--list"],
            cwd=self.work, env=self.env, capture_output=True, text=True, timeout=120,
        )
        self.check(
            "the packaged benchmark lists its quick cases with the record's times",
            listed.returncode == 0 and "spm_4p12s_small" in listed.stdout and "6 cases" in listed.stdout
            and "__cogging" in listed.stdout and "spm_outer_" in listed.stdout,
            (listed.stdout + listed.stderr).strip()[-400:],
        )

    def launch(self, *arguments: str, wait: bool = False) -> subprocess.Popen | subprocess.CompletedProcess:
        command = [str(self.bin / ("coilem.exe" if WINDOWS else "coilem")), "--no-browser", *arguments]
        if wait:
            return subprocess.run(command, cwd=self.work, env=self.env, capture_output=True, text=True, timeout=120)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0
        return subprocess.Popen(
            command, cwd=self.work, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags
        )

    def solver_processes(self) -> list[str]:
        if WINDOWS:
            script = "Get-CimInstance Win32_Process -Filter \"Name='magneto2d.exe'\" | ForEach-Object { \"$($_.ProcessId) $($_.ExecutablePath)\" }"
            output = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout
        else:
            output = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
        marker = str(self.venv).lower()
        return [line.strip() for line in output.splitlines() if marker in line.lower() and "magneto2d" in line.lower()]

    def run(self) -> int:
        server = self.launch()
        assert isinstance(server, subprocess.Popen) and server.stdout is not None
        port = None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            line = server.stdout.readline()
            if not line:
                break
            self.log.append(line.rstrip())
            found = re.search(r"is running at http://127\.0\.0\.1:(\d+)", line)
            if found:
                port = int(found[1])
                break
        if not self.check("launcher becomes ready", port is not None, f"port={port}"):
            server.kill()
            return self.finish()
        threading.Thread(target=lambda: self.log.extend(line.rstrip() for line in server.stdout), daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            self.exercise(base, port)
            self.interrupt(server, base)
        finally:
            if server.poll() is None:
                server.kill()
        return self.finish()

    def exercise(self, base: str, port: int) -> None:
        status, _, body = request("GET", base + "/health")
        health = json.loads(body) if status == 200 else {}
        self.check(
            "health reports the installed version",
            status == 200 and health.get("version") == self.version
            and (health.get("build") or {}).get("application_version") == self.version,
            f"installed={self.version}, health={health.get('version')}",
        )
        status, headers, body = request("GET", base + "/")
        self.check("index", status == 200 and b'<div id="root">' in body and headers.get("cache-control") == "no-store", str(status))
        asset = re.search(rb'src="(/assets/[^"]+\.js)"', body)
        status, headers, _ = request("GET", base + (asset[1].decode() if asset else "/assets/missing.js"))
        immutable = "immutable" in headers.get("cache-control", "")
        self.check("hashed asset", status == 200 and immutable, f"{status} {headers.get('content-type')}")
        status, _, body = request("GET", base + "/tutorials/lesson-1")
        self.check("deep link", status == 200 and b'<div id="root">' in body, str(status))
        status, _, body = request("GET", base + "/solve/not-a-route")
        self.check("unknown API path is 404", status == 404 and b"<div id=\"root\">" not in body, str(status))

        preview = json.loads(json.dumps(MOTOR))
        preview["solve_params"].update({"solve_quality": "quick", "mesh_density": "coarse"})
        status, _, body = request("POST", base + "/solve", preview)
        solved = status == 200 and "summary" in json.loads(body)
        self.check("motor Preview solve", solved, "" if status == 200 else f"{status} {body[:200]!r}")
        for name, route, payload in (
            ("cylindrical Halbach solve", "/halbach/solve", CYLINDRICAL_HALBACH),
            ("linear Halbach solve", "/halbach/linear/solve", LINEAR_HALBACH),
        ):
            status, _, body = request("POST", base + route, payload)
            self.check(name, status == 200, "" if status == 200 else f"{status} {body[:200]!r}")
        status, _, body = request("GET", base + "/tutorials/follow-the-flux/solve?steel_return=true")
        self.check("lesson solve", status == 200, "" if status == 200 else f"{status} {body[:200]!r}")

        status, _, body = request("GET", base + "/runs")
        runs = json.loads(body).get("runs", []) if status == 200 else []
        if self.check("saved run is listed", bool(runs), f"runs={len(runs)}"):
            run = f"{base}/runs/{runs[0]['project_slug']}/{runs[0]['run_id']}"
            for suffix, magic in (("report.pdf", b"%PDF"), ("report.csv", b""), ("package.zip", b"PK")):
                status, _, body = request("GET", f"{run}/{suffix}")
                self.check(f"download {suffix}", status == 200 and body.startswith(magic) and len(body) > 100, f"{status} {len(body)} bytes")

        second = self.launch(wait=True)
        assert isinstance(second, subprocess.CompletedProcess)
        reused = second.returncode == 0 and f"running at {base}" in second.stdout
        self.check("second launch reuses the server", reused, (second.stdout + second.stderr).strip())

    def interrupt(self, server: subprocess.Popen, base: str) -> None:
        standard = json.loads(json.dumps(MOTOR))
        standard["solve_params"].update({"solve_quality": "standard", "mesh_density": "normal"})
        stream = SolveStream(base + "/solve/stream", standard)
        # Interrupt once the stream reports a Magneto2D position solved with more
        # to come. Polling for magneto2d processes missed them: each one can live
        # under a second, less than one process query takes through PowerShell on
        # Windows, so the whole solve could finish before any query saw one.
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and not stream.solving.is_set() and not stream.ended.is_set():
            stream.solving.wait(0.2)
        running = stream.solving.is_set() and not stream.ended.is_set()
        self.check("a solve is running before the interrupt", running, stream.describe())
        started = time.monotonic()
        server.send_signal(signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGINT)
        try:
            code = server.wait(timeout=60)
        except subprocess.TimeoutExpired:
            code = None
        elapsed = time.monotonic() - started
        time.sleep(2)
        self.check("interrupt stops the server cleanly", code == 0, f"exit={code} after {elapsed:.1f}s")
        remaining = self.solver_processes()
        self.check("no Magneto2D process remains", not remaining, f"{remaining}")
        manifests = [path for path in (self.data_root / "solves").rglob("manifest.json") if ".partial" in str(path.parent)]
        self.check("the interrupted run is recorded as cancelled", any("SOLVER_CANCELLED" in path.read_text(encoding="utf-8") for path in manifests))
        self.check("the launcher record is removed", not (self.data_root / "launcher.json").exists())

    def finish(self) -> int:
        failed = [name for name, ok, _ in self.results if not ok]
        if failed:
            print("\n--- launcher output ---\n" + "\n".join(self.log[-60:]))
        print(f"\n{len(self.results) - len(failed)}/{len(self.results)} acceptance checks passed" + (f"; failed: {failed}" if failed else ""))
        return 1 if failed else 0


def request(method: str, url: str, body: object | None = None, timeout: float = 900) -> tuple[int, dict[str, str], bytes]:
    data = None if body is None else json.dumps(body).encode()
    prepared = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(prepared, timeout=timeout) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        return error.code, {key.lower(): value for key, value in error.headers.items()}, error.read()


def sse_events(lines):
    """Yield ``(event, data)`` for each server-sent event in ``lines``; data is parsed JSON or None."""

    event, data = "message", []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line:
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:"):].lstrip())
            continue
        if data:
            try:
                payload = json.loads("\n".join(data))
            except ValueError:
                payload = None
            yield event, payload
        event, data = "message", []


# Progress stages the solver reports after each Magneto2D solve: loaded positions,
# no-load positions and cogging positions.
MAGNETO2D_STAGES = ("magneto2d_", "noload_sweep")


def magneto2d_solving(event: str, payload: object) -> bool:
    """True for a progress event that follows a Magneto2D solve, with positions still to solve."""

    if event != "progress" or not isinstance(payload, dict):
        return False
    try:
        position, total = int(payload.get("position") or 0), int(payload.get("total") or 0)
    except (TypeError, ValueError):
        return False
    return str(payload.get("stage", "")).startswith(MAGNETO2D_STAGES) and 0 < position < total


class SolveStream:
    """Follow one ``/solve/stream`` request in the background."""

    def __init__(self, url: str, body: object) -> None:
        self.solving = threading.Event()
        self.ended = threading.Event()
        self.last: tuple[str, str, object, object] | None = None
        self.outcome: str | None = None
        data = json.dumps(body).encode()
        self.request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
        threading.Thread(target=self.follow, daemon=True).start()

    def follow(self) -> None:
        try:
            with urllib.request.urlopen(self.request, timeout=900) as response:
                self.read(line.decode("utf-8", "replace") for line in response)
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
            pass  # The interrupt closes the connection, possibly mid-event.
        finally:
            self.ended.set()

    def read(self, lines) -> None:
        for event, payload in sse_events(lines):
            fields = payload if isinstance(payload, dict) else {}
            self.last = (event, str(fields.get("stage", "")), fields.get("position"), fields.get("total"))
            if magneto2d_solving(event, payload):
                self.solving.set()
            if event in ("complete", "error"):
                self.outcome = event

    def describe(self) -> str:
        if self.outcome:
            return f"the solve ended with {self.outcome!r} before it could be interrupted"
        if self.last is None:
            return "no stream event yet"
        event, stage, position, total = self.last
        return f"{event} {stage} {position}/{total}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", required=True, help="wheel path or pip requirement to install")
    parser.add_argument("--python", default=sys.executable, help="interpreter for the new environment")
    parser.add_argument("--index-url", help="download the coilEM wheel from this index; dependencies still come from PyPI")
    parser.add_argument("--expect-sha256", help="with --index-url, the SHA-256 the downloaded wheel must have")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    args = parser.parse_args()
    requirement = str(Path(args.install).resolve()) if Path(args.install).is_file() else args.install
    work = Path(tempfile.mkdtemp(prefix="coilem-acceptance-"))
    try:
        acceptance = Acceptance(work)
        if args.index_url:
            requirement = acceptance.download(requirement, args.index_url, args.expect_sha256, args.python)
            if acceptance.results and not acceptance.results[-1][1]:
                return acceptance.finish()
        acceptance.install(requirement, args.python)
        return acceptance.run()
    finally:
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
