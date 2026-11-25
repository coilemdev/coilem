"""coilEM from Python: load a design, choose a saved run setup, check it, solve it and read the results.

    import coilem

    if __name__ == "__main__":
        motor = coilem.Motor.load("motor.coilem")
        print([status.setup.name for status in coilem.setups(motor)])
        result = coilem.solve(motor, setup="High Speed")
        print(result.average_torque_Nm, result.setup["name"])

Importing ``coilem`` never starts the app, a server or a solve. Solves run in
this Python process; ``server="http://127.0.0.1:2645"`` sends them to a
running app instead. On Windows, call :func:`solve` from under
``if __name__ == "__main__":`` in a saved script. The same steps are terminal
commands: ``coilem check``, ``coilem solve``, ``coilem thermal``,
``coilem setups``, ``coilem schema`` and ``coilem version``. See
docs/PYTHON_CLIENT.md.

This package is the public name of :mod:`backend.client`, which keeps working.
"""

from backend import __version__
from backend.client import (
    ANALYSES,
    MESH_DENSITIES,
    QUALITIES,
    REFERENCE_SETUPS,
    Cogging,
    CoilemError,
    DqFluxLinkage,
    InputError,
    MainModuleError,
    Materials,
    Motor,
    OperatingPoint,
    PhaseWaveforms,
    PreparedSolve,
    Result,
    Rotor,
    RunSetup,
    SetupStatus,
    SetupUse,
    SolveError,
    Stator,
    Sweep,
    SweepPoint,
    ThermalEstimate,
    Waveform,
    Winding,
    Wire,
    build_request,
    check,
    check_main_module,
    prepare,
    setups,
    solve,
    sweep,
    thermal,
    thermal_inputs,
)

__all__ = [
    "ANALYSES",
    "MESH_DENSITIES",
    "QUALITIES",
    "REFERENCE_SETUPS",
    "CoilemError",
    "Cogging",
    "DqFluxLinkage",
    "InputError",
    "MainModuleError",
    "Materials",
    "Motor",
    "OperatingPoint",
    "PhaseWaveforms",
    "PreparedSolve",
    "Result",
    "Rotor",
    "RunSetup",
    "SetupStatus",
    "SetupUse",
    "SolveError",
    "Stator",
    "Sweep",
    "SweepPoint",
    "ThermalEstimate",
    "Waveform",
    "Winding",
    "Wire",
    "__version__",
    "build_request",
    "check",
    "check_main_module",
    "prepare",
    "setups",
    "solve",
    "sweep",
    "thermal",
    "thermal_inputs",
]
