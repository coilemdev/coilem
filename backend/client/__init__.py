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
from backend.client._solve import (
    MESH_DENSITIES,
    QUALITIES,
    Sweep,
    SweepPoint,
    build_request,
    check,
    check_main_module,
    solve,
    sweep,
)

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
    "Result",
    "Rotor",
    "SolveError",
    "Stator",
    "Sweep",
    "SweepPoint",
    "Waveform",
    "Winding",
    "Wire",
    "build_request",
    "check",
    "check_main_module",
    "solve",
    "sweep",
]
