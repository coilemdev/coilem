"""Safe lifecycle management for ElmerGrid and ElmerSolver subprocesses."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from backend.solver_contract import SolveCancelledError

from .errors import ElmerExecutionError, ElmerMeshConversionError

_TRUNCATION_MARKER = b"\n... log truncated by coilEM ...\n"


class _BoundedLogCapture:
    """Continuously drain one process pipe into a bounded memory/file tail."""

    def __init__(self, path: Path, max_bytes: int) -> None:
        self.path = path
        self.max_bytes = max(4096, int(max_bytes))
        available = max(2, self.max_bytes - len(_TRUNCATION_MARKER))
        self._head_limit = available // 2
        self._tail_limit = available - self._head_limit
        self._buffer = bytearray()
        self._head = b""
        self._tail = b""
        self._truncated = False
        self.path.write_bytes(b"")

    def consume(self, stream: object) -> None:
        read = getattr(stream, "read")
        while True:
            chunk = read(64 * 1024)
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                chunk = str(chunk).encode("utf-8", errors="replace")
            self._append(chunk)

    def _append(self, chunk: bytes) -> None:
        if not self._truncated:
            self._buffer.extend(chunk)
            if len(self._buffer) <= self.max_bytes:
                self.path.write_bytes(self._buffer)
                return
            materialized = bytes(self._buffer)
            self._head = materialized[: self._head_limit]
            self._tail = materialized[-self._tail_limit :]
            self._buffer.clear()
            self._truncated = True
        else:
            self._tail = (self._tail + chunk)[-self._tail_limit :]
        self.path.write_bytes(self.payload())

    def payload(self) -> bytes:
        if self._truncated:
            return self._head + _TRUNCATION_MARKER + self._tail
        return bytes(self._buffer)

    def text(self) -> str:
        return self.payload().decode("utf-8", errors="replace")


@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    returncode: int
    elapsed_s: float
    stdout_path: str
    stderr_path: str
    stdout: str
    stderr: str


class ElmerProcessRunner:
    """Run Elmer commands without a shell and cancel their process groups."""

    def __init__(self, *, max_log_bytes: int = 2 * 1024 * 1024) -> None:
        self.max_log_bytes = max(4096, int(max_log_bytes))
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._active: set[subprocess.Popen[bytes]] = set()

    @property
    def active_process_count(self) -> int:
        with self._lock:
            return len(self._active)

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            processes = tuple(self._active)
        for process in processes:
            self._terminate_tree(process)

    def reset(self) -> None:
        self._cancelled.clear()

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path,
        timeout_s: float,
        log_prefix: str,
        conversion: bool = False,
        env: dict[str, str] | None = None,
    ) -> ProcessResult:
        if self._cancelled.is_set():
            raise SolveCancelledError("Elmer solve was cancelled before process start")
        workdir = Path(cwd)
        workdir.mkdir(parents=True, exist_ok=True)
        stdout_path = workdir / f"{log_prefix}.stdout.log"
        stderr_path = workdir / f"{log_prefix}.stderr.log"
        creationflags = 0
        start_new_session = os.name != "nt"
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            env = self._windows_elmer_env(command, env)
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                [str(part) for part in command],
                cwd=workdir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                shell=False,
                start_new_session=start_new_session,
                creationflags=creationflags,
            )
        except OSError as exc:
            error_type = ElmerMeshConversionError if conversion else ElmerExecutionError
            raise error_type(f"Could not start {command[0]}: {exc}") from exc
        with self._lock:
            self._active.add(process)
        assert process.stdout is not None and process.stderr is not None
        stdout_capture = _BoundedLogCapture(stdout_path, self.max_log_bytes)
        stderr_capture = _BoundedLogCapture(stderr_path, self.max_log_bytes)
        stdout_thread = threading.Thread(
            target=stdout_capture.consume,
            args=(process.stdout,),
            name="openem-elmer-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=stderr_capture.consume,
            args=(process.stderr,),
            name="openem-elmer-stderr",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            while True:
                if self._cancelled.is_set():
                    self._terminate_tree(process)
                    raise SolveCancelledError(f"Cancelled external process {command[0]}")
                remaining = float(timeout_s) - (time.monotonic() - started)
                if remaining <= 0.0:
                    self._terminate_tree(process)
                    error_type = ElmerMeshConversionError if conversion else ElmerExecutionError
                    raise error_type(f"{command[0]} timed out after {timeout_s:.1f} seconds")
                try:
                    process.wait(timeout=min(0.25, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            stdout_thread.join(timeout=5.0)
            stderr_thread.join(timeout=5.0)
            with self._lock:
                self._active.discard(process)

        if self._cancelled.is_set():
            raise SolveCancelledError(f"Cancelled external process {command[0]}")

        stdout = stdout_capture.text()
        stderr = stderr_capture.text()
        elapsed = time.monotonic() - started
        result = ProcessResult(
            command=tuple(str(part) for part in command),
            returncode=int(process.returncode or 0),
            elapsed_s=elapsed,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            stdout=stdout,
            stderr=stderr,
        )
        if result.returncode != 0:
            detail = (stderr or stdout).strip().splitlines()
            message = detail[-1] if detail else "no process diagnostics"
            error_type = ElmerMeshConversionError if conversion else ElmerExecutionError
            raise error_type(
                f"{command[0]} exited with code {result.returncode}: {message}; "
                f"logs: {stdout_path}, {stderr_path}"
            )
        return result

    @staticmethod
    def _windows_elmer_env(
        command: Sequence[str], env: dict[str, str] | None
    ) -> dict[str, str]:
        """Make a configured Windows Elmer runtime self-contained for subprocesses."""

        runtime_env = dict(os.environ if env is None else env)
        if not command:
            return runtime_env
        executable = Path(str(command[0])).expanduser()
        if executable.parent.name.lower() != "bin" or not executable.name.lower().startswith(
            "elmer"
        ):
            return runtime_env
        executable_dir = str(executable.parent.resolve())
        current_path = runtime_env.get("PATH", "")
        path_entries = current_path.split(os.pathsep) if current_path else []
        if executable_dir.lower() not in {entry.lower() for entry in path_entries}:
            runtime_env["PATH"] = os.pathsep.join([executable_dir, *path_entries])
        elmer_home = executable.parent.parent.resolve()
        runtime_env["ELMER_HOME"] = str(elmer_home)
        runtime_env["ELMER_LIB"] = str(elmer_home / "share" / "elmersolver" / "lib")
        return runtime_env

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass


def convert_with_elmergrid(
    runner: ElmerProcessRunner,
    *,
    grid_path: str,
    gmsh_path: str | Path,
    mesh_dir: str | Path,
    timeout_s: float,
) -> ProcessResult:
    source = Path(gmsh_path).resolve()
    destination = Path(mesh_dir)
    return runner.run(
        [grid_path, "14", "2", str(source), "-out", destination.name, "-autoclean"],
        cwd=destination.parent,
        timeout_s=timeout_s,
        log_prefix="elmergrid",
        conversion=True,
    )
