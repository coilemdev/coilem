"""Script coilEM from Python: define a motor, solve it and read the results.

    from backend import client as coilem

    motor = coilem.Motor.load("my_motor.json")
    result = coilem.solve(motor, coilem.OperatingPoint(current_A=20, current_angle_deg=30))
    print(result.average_torque_Nm, result.torque_ripple_pct)

Solves run in this Python process by default, through the same checks and
pipeline as the app's Solve button; ``server="http://127.0.0.1:2645"``
sends them to a running app instead. On Windows, call ``solve`` from under
``if __name__ == "__main__":`` in a saved script. See docs/PYTHON_CLIENT.md.
"""

from backend.client._errors import CoilemError, InputError, MainModuleError, SolveError
from backend.client._inputs import ANALYSES, Materials, Motor, OperatingPoint, Rotor, Stator, Winding, Wire
from backend.client._results import Cogging, DqFluxLinkage, PhaseWaveforms, Result, Waveform
from backend.client._setups import REFERENCE_SETUPS, RunSetup, SetupStatus, SetupUse
from backend.client._solve import (
    MESH_DENSITIES,
    QUALITIES,
    PreparedSolve,
    Sweep,
    SweepPoint,
    build_request,
    check,
    check_main_module,
    prepare,
    setups,
    solve,
    sweep,
)
from backend.client._thermal import ThermalEstimate, thermal, thermal_inputs

__all__ = [
    "ANALYSES",
    "MESH_DENSITIES",
    "QUALITIES",
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
    "REFERENCE_SETUPS",
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
