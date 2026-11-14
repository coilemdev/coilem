"""Interior-magnet motor from Python: sweep the current angle and read torque and d/q inductances.

Run from a coilEM checkout or an environment with coilEM installed:

    python docs/examples/client_ipm_motor.py [output-folder]

It defines an 8-pole / 12-slot flat-buried interior-magnet motor, solves it
at 50 A peak for five current angles (quick preset, coarse mesh; under a
minute in all), prints torque, ripple and the d/q flux linkages and apparent
inductances at each angle, estimates the maximum-torque-per-ampere angle
from them, and writes the table as CSV.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from backend import client as coilem


def build_motor() -> coilem.Motor:
    return coilem.Motor(
        topology="IPM",
        stator=coilem.Stator(
            OD_mm=160,
            ID_mm=96,
            slot_count=12,
            stack_length_mm=100,
            slot_opening_mm=7.54,
            tooth_width_mm=11.31,
            yoke_thickness_mm=19.2,
        ),
        rotor=coilem.Rotor(
            OD_mm=86,
            pole_count=8,
            ipm_topology="flat_buried",
            magnet_thickness_mm=3.0,
            magnet_width_mm=23.64,
            magnet_embrace=0.8,
            bridge_thickness_mm=1.5,
            side_bridge_thickness_mm=1.2,
            pocket_clearance_mm=0.25,
        ),
        winding=coilem.Winding(type="concentrated", layers=1, turns_per_coil=8),
    )


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("coilem-client-output")
    output.mkdir(parents=True, exist_ok=True)

    motor = build_motor()
    print(motor)
    motor.save(output / "ipm_motor_request.json")

    angles = [0, 15, 30, 45, 60]
    sweep = coilem.sweep(
        motor,
        current_A=50,
        current_angle_deg=angles,
        operating_point=coilem.OperatingPoint(speed_rpm=3000),
        # Back-EMF gives the magnet flux linkage that the apparent L_d needs.
        analyses=["torque", "back_emf"],
        quality="quick",
        mesh="coarse",
        on_point=lambda index, total, point: print(f"  solved {index + 1}/{total} (γ = {point.operating_point.current_angle_deg:g}°)", flush=True),
    )

    print(f"\n{'γ °':>5} {'torque N·m':>11} {'ripple %':>9} {'λd mWb':>8} {'λq mWb':>8} {'Ld µH':>7} {'Lq µH':>7}")
    for point in sweep:
        if not point.ok:
            print(f"{point.operating_point.current_angle_deg:5g}  failed: {point.error}")
            continue
        result, dq = point.result, point.result.dq
        ld = f"{dq.L_d_H * 1e6:7.1f}" if dq.L_d_H is not None else "      –"
        lq = f"{dq.L_q_H * 1e6:7.1f}" if dq.L_q_H is not None else "      –"
        print(
            f"{point.operating_point.current_angle_deg:5g} {result.average_torque_Nm:11.3f} {result.torque_ripple_pct:9.1f} "
            f"{dq.lambda_d_Wb * 1e3:8.2f} {dq.lambda_q_Wb * 1e3:8.2f} {ld} {lq}"
        )

    best = sweep.best("average_torque_Nm")
    print(f"\nMost torque of the angles solved: {best.result.average_torque_Nm:.3f} N·m at γ = {best.operating_point.current_angle_deg:g}°")

    # The d/q numbers give the maximum-torque-per-ampere angle between the
    # solved points: with constant λpm, Ld and Lq, torque ∝ λpm·iq + (Ld − Lq)·id·iq.
    reference = next(point for point in sweep if point.ok and point.result.dq.L_d_H is not None)
    dq = reference.result.dq
    saliency_H = dq.L_q_H - dq.L_d_H
    gamma = 0.0
    if saliency_H > 0:
        current = reference.operating_point.current_A
        root = math.sqrt(dq.lambda_pm_Wb**2 + 8 * (saliency_H * current) ** 2)
        gamma = math.degrees(math.asin((root - dq.lambda_pm_Wb) / (4 * saliency_H * current)))
    print(
        f"Lq − Ld = {saliency_H * 1e6:.1f} µH at γ = {reference.operating_point.current_angle_deg:g}°, so the "
        f"constant-inductance MTPA angle at 50 A is about {gamma:.1f}°: a small saliency leaves little reluctance torque."
    )
    print(f"Wrote {sweep.to_csv(output / 'ipm_angle_sweep.csv')}")


# The solver starts worker processes, which import this file again; the guard
# keeps them from starting another solve. It is required on Windows.
if __name__ == "__main__":
    main()
