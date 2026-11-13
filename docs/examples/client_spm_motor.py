"""Surface-magnet motor from Python: define it, solve one operating point, read the results.

Run from a coilEM checkout or an environment with coilEM installed:

    python docs/examples/client_spm_motor.py [output-folder]

It solves an 8-pole / 12-slot surface-magnet motor at 20 A, 30° with torque,
back-EMF and cogging at the quick preset on a coarse mesh (about 10 s), then
writes the request and the result as JSON. Use quality="standard" and
mesh="normal" for design numbers.
"""

from __future__ import annotations

import sys
from pathlib import Path

from backend import client as coilem


def build_motor() -> coilem.Motor:
    return coilem.Motor(
        topology="SPM",
        stator=coilem.Stator(
            OD_mm=100,
            ID_mm=60,
            slot_count=12,
            stack_length_mm=50,
            slot_opening_mm=2,
            tooth_width_mm=9,
            yoke_thickness_mm=8,
        ),
        rotor=coilem.Rotor(OD_mm=54, pole_count=8, magnet_thickness_mm=2.5, magnet_width_mm=16.5, magnet_embrace=0.833),
        winding=coilem.Winding(type="concentrated", layers=1, turns_per_coil=12),
        materials=coilem.Materials(magnet_grade="N42"),
    )


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("coilem-client-output")
    output.mkdir(parents=True, exist_ok=True)

    # Inputs are checked as they are made; an error names the field at fault.
    try:
        coilem.Rotor(OD_mm=54, pole_count=8, magnet_thickness_mm=0.1, magnet_width_mm=16.5)
    except coilem.InputError as error:
        print(f"Refused as expected: {error}")

    motor = build_motor()
    print(motor)
    for warning in coilem.check(motor):
        print("warning:", warning)

    point = coilem.OperatingPoint(current_A=20, current_angle_deg=30, speed_rpm=3000)
    request_path = motor.save(output / "spm_motor_request.json")

    stages: list[str] = []

    def report(done: int, total: int, stage: str | None) -> None:
        if stage and stage not in stages:
            stages.append(stage)
            print(f"  {stage} ({done}/{total})", flush=True)

    try:
        result = coilem.solve(
            motor,
            point,
            analyses=["torque", "back_emf", "cogging"],
            quality="quick",
            mesh="coarse",
            on_progress=report,
        )
    except coilem.SolveError as error:
        raise SystemExit(f"Solve failed ({error.error_code}): {error}") from error

    print(result)
    print(f"Average torque     {result.average_torque_Nm:8.3f} N·m")
    print(f"Torque ripple      {result.torque_ripple_pct:8.1f} %")
    print(f"Back-EMF (fund.)   {result.back_emf_fundamental_V:8.2f} V at {point.speed_rpm} rpm")
    dq = result.dq
    print(f"i_d, i_q           {dq.i_d_A:8.2f} A, {dq.i_q_A:.2f} A")
    print(f"λ_d, λ_q, λ_pm     {dq.lambda_d_Wb * 1e3:8.2f} mWb, {dq.lambda_q_Wb * 1e3:.2f} mWb, {dq.lambda_pm_Wb * 1e3:.2f} mWb")
    print(f"L_d, L_q           {dq.L_d_H * 1e6:8.1f} µH, {dq.L_q_H * 1e6:.1f} µH  ({dq.inductance_status})")
    cogging = result.cogging
    print(f"Cogging            {cogging.peak_to_peak_Nm:8.3f} N·m peak to peak, period {cogging.period_mech_deg:g}° mech")

    torque = result.torque
    print(f"Torque waveform    {len(torque)} positions, {torque.values.min():.3f} to {torque.values.max():.3f} N·m")
    emf = result.back_emf
    print(f"Back-EMF waveform  {len(emf)} positions, phase A peak {abs(emf.a).max():.2f} V")

    result_path = result.save(output / "spm_result.json")
    print(f"Wrote {request_path} and {result_path}")


# The solver starts worker processes, which import this file again; the guard
# keeps them from starting another solve. It is required on Windows.
if __name__ == "__main__":
    main()
