"""External-solver logs must be readable while a small-output process is running."""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

from backend.elmer.process import ElmerProcessRunner


def test_live_output_is_captured_before_process_exit(tmp_path):
    release = tmp_path / "release"
    child = (
        "import pathlib, sys, time\n"
        "print('solver ready', flush=True)\n"
        "while not pathlib.Path(sys.argv[1]).exists():\n"
        "    time.sleep(0.01)\n"
    )
    runner = ElmerProcessRunner()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            runner.run, [sys.executable, "-u", "-c", child, str(release)],
            cwd=tmp_path, timeout_s=10, log_prefix="live",
        )
        try:
            log = tmp_path / "live.stdout.log"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if log.exists() and b"solver ready" in log.read_bytes():
                    break
                time.sleep(0.01)
            assert not pending.done(), "the child must still be waiting for release"
            assert b"solver ready" in log.read_bytes()
        finally:
            release.touch()
            result = pending.result(timeout=5)
    assert result.returncode == 0
    assert result.stdout.strip() == "solver ready"
