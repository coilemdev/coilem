"""Run this package's FEMM collector on FEMM 5 (femm-qt, macOS or Linux) instead of Windows FEMM 4.2.

    python -m tools.phase_g_femm.femm5_run [--min-angle 33] -m tools.phase_g_femm.collect --history ... --out ...

Importing tools.femm_reference.femm5 swaps only FEMM's execution hooks (an owned headless FEMM 5 over
TCP, binary checks, identity). FEMM 5's server has no Lua, so the collector's Lua export scripts run
through tools.phase_g_femm.femm5_lua. FEMM 5 meshes with its own mesher, so a record collected here
names FEMM 5 as its solver. The Phase G rotor references use the rotor on one fixed mesh and a 33
degree minimum angle, a setting checked against FEMM 4.2 on the inner-rotor Phase G stator points.
"""

from __future__ import annotations

import hashlib
import runpy
import sys
from pathlib import Path


def route_lua_scripts(femm5) -> None:
    from tools.femm_reference import automation, runtime
    from tools.phase_g_femm import femm5_lua

    identity = runtime.identity
    execution = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                 for name, path in (("femm5_run.py", __file__), ("femm5_lua.py", femm5_lua.__file__))}

    def recorded(phase):  # name the execution layer in every reference identity
        value = identity(phase)
        value["phase_g_femm5_execution"] = dict(execution)
        value["solver"] = "FEMM 5"
        return value

    runtime.identity = recorded
    loader = femm5.femm_module

    def femm_module():
        module = loader()
        femm5_lua.install(module)
        return module

    femm5.femm_module = femm_module
    automation.femm_module = femm_module


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    min_angle = None
    if argv[:1] == ["--min-angle"]:
        min_angle, argv = argv[1], argv[2:]
    if argv[:1] != ["-m"] or len(argv) < 2:
        raise SystemExit("usage: python -m tools.phase_g_femm.femm5_run [--min-angle DEG] -m MODULE [ARGS...]")
    from tools.femm_reference import femm5

    if min_angle is not None:
        femm5.set_min_angle(min_angle)
    route_lua_scripts(femm5)
    module = argv[1]
    sys.argv = [module, *argv[2:]]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
