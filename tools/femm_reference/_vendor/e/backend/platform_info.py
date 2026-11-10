"""Platform detection shared by the local core and private integrations."""

from __future__ import annotations

import platform
import subprocess
from typing import TypedDict


class PlatformInfo(TypedDict):
    system: str
    machine: str
    is_apple_silicon: bool
    is_rosetta: bool


def get_platform_info() -> PlatformInfo:
    """Return platform facts without importing a solver integration."""

    system = platform.system()
    machine = platform.machine()
    is_apple_silicon = system == "Darwin" and machine == "arm64"
    is_rosetta = False

    if system == "Darwin" and machine == "x86_64":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "sysctl.proc_translated"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            is_rosetta = result.stdout.strip() == "1"
        except (OSError, subprocess.SubprocessError):
            pass

    return {
        "system": system,
        "machine": machine,
        "is_apple_silicon": is_apple_silicon,
        "is_rosetta": is_rosetta,
    }
