"""Contain a Windows Gmsh native-environment side effect."""

from __future__ import annotations

import os
from contextlib import contextmanager


@contextmanager
def preserve_process_path():
    """Keep native PATH consistent with Python's environment after Gmsh exits.

    The tested Windows Gmsh DLL replaces the process PATH without updating
    os.environ. Subsequent CreateProcess calls then cannot find programs which
    shutil.which still reports as available. Reapplying the current Python
    value also preserves intentional Python-side environment changes.
    """
    try:
        yield
    finally:
        if os.name == "nt":
            current = os.environ.get("PATH")
            if current is None:
                os.unsetenv("PATH")
            else:
                os.environ["PATH"] = current
