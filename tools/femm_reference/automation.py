"""Owned Windows COM sessions; only this worker's FEMM processes are closed."""

from __future__ import annotations

import collections
import os
import time
import uuid
from pathlib import Path

from tools.femm_reference.runtime import DATA, binary_hashes, check_environment, read, sha, write


def femm_module():
    import femm

    return femm


class Automation:
    def __init__(self, directory):
        check_environment()
        import femm
        import win32job

        self.femm = femm
        self.directory = directory
        self.original_call = femm.callfemm
        self.original_open = femm.openfemm
        self.calls = collections.defaultdict(lambda: {"count": 0, "elapsed_s": 0.0, "max_s": 0.0})
        self.sessions = []
        self.job = win32job.CreateJobObject(None, "coilem-f112-" + uuid.uuid4().hex)
        limits = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, limits)
        femm.callfemm = self.call
        femm.openfemm = self.open

    def call(self, command):
        name = command.split("(", 1)[0].strip()
        started = time.perf_counter()
        try:
            return self.original_call(command)
        finally:
            elapsed = time.perf_counter() - started
            entry = self.calls[name]
            entry["count"] += 1
            entry["elapsed_s"] += elapsed
            entry["max_s"] = max(entry["max_s"], elapsed)

    def open(self, *args, **kwargs):
        import pythoncom
        import win32api
        import win32com.client
        import win32gui
        import win32job
        import win32process

        pythoncom.CoInitialize()
        started = time.perf_counter()
        self.femm.HandleToFEMM = win32com.client.DispatchEx("femm.ActiveFEMM")
        if args and args[0]:
            self.femm.main_minimize()
        marker = "f112_" + uuid.uuid4().hex[:12]
        self.femm.newdocument(0)
        self.femm.mi_saveas(str(self.directory / (marker + ".fem")))
        matches = []

        def inspect_window(hwnd, _):
            if marker in win32gui.GetWindowText(hwnd):
                matches.append(win32process.GetWindowThreadProcessId(hwnd)[1])

        win32gui.EnumWindows(inspect_window, None)
        assert len(set(matches)) == 1, ("Cannot identify owned FEMM instance", matches)
        pid = matches[0]
        handle = win32api.OpenProcess(0x0001 | 0x0100 | 0x0400 | 0x0010, False, pid)
        try:
            executable = win32process.GetModuleFileNameEx(handle, 0)
            assert Path(executable).name.lower() == "femm.exe", executable
            win32job.AssignProcessToJobObject(self.job, handle)
        finally:
            handle.Close()
        self.sessions.append({"pid": pid, "marker": marker, "startup_s": time.perf_counter() - started})
        # Check the executable COM actually launched, including its mesher and
        # solver, rather than trusting the configured directory alone.
        expected = read(DATA / "femm-binaries.json")
        binary_hashes(required=True)
        actual = {name: sha(Path(executable).parent / name) for name in expected}
        if actual != expected:
            raise ValueError("COM launched a different FEMM reference build")
        write(self.directory / "automation.json", {"worker_pid": os.getpid(), "sessions": self.sessions})
        self.femm.mi_close()

    def close(self):
        try:
            write(
                self.directory / "automation.json",
                {
                    "worker_pid": os.getpid(),
                    "sessions": self.sessions,
                    "commands": dict(sorted(self.calls.items(), key=lambda item: -item[1]["elapsed_s"])),
                },
            )
        finally:
            self.femm.callfemm = self.original_call
            self.femm.openfemm = self.original_open
            self.job.Close()
