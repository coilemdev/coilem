"""Independent direct-DFT loss oracle for fixed material-point reference data.

No production backend imports or production FFT/loss helpers are permitted here.
Inputs are full-turn B queries with an explicit frame, signed native mechanical
poses, and the first mesh's integration areas. Coefficients use Hz, peak T and W/kg.
"""

from __future__ import annotations

import math

import numpy as np


def reference_loss(field_queries, angles_deg, areas_m2, *, speed_rpm, stack_m, coefficients, stacking_factor=1.0, field_frame="global"):
    fields = np.asarray(field_queries, dtype=float)
    angles = np.asarray(angles_deg, dtype=float)
    areas = np.asarray(areas_m2, dtype=float)
    if fields.shape != (len(angles), len(areas), 2) or len(angles) < 8:
        raise ValueError("reference field dimensions are inconsistent")
    if not all(np.isfinite(x).all() for x in (fields, angles, areas)) or np.any(areas <= 0):
        raise ValueError("reference needs finite fields and positive areas")
    step = np.diff(angles)
    if not np.allclose(np.abs(step), 360/len(angles), rtol=0, atol=1e-8) or not np.allclose(step, step[0]):
        raise ValueError("reference needs an ordered half-open full mechanical turn")
    if field_frame == "global":
        c, s = np.cos(angles*np.pi/180)[:, None], np.sin(angles*np.pi/180)[:, None]
        x, y = c*fields[:, :, 0] + s*fields[:, :, 1], -s*fields[:, :, 0] + c*fields[:, :, 1]
    elif field_frame == "rotor_material":
        # The independent oracle reads raw material-frame queries directly.
        x, y = fields[:, :, 0], fields[:, :, 1]
    else:
        raise ValueError("reference field frame must be global or rotor_material")
    count = len(angles)
    orders = np.arange(1, (count-1)//2 + 1)
    # Explicit DFT projections are independent of the production rFFT path.
    phase = 2*np.pi*orders[:, None]*np.arange(count)[None, :]/count
    cosine, sine = 2/count*np.cos(phase), 2/count*np.sin(phase)
    amplitudes = np.sqrt((cosine @ x)**2 + (sine @ x)**2 + (cosine @ y)**2 + (sine @ y)**2)
    mass = areas * stack_m * coefficients["density_kg_m3"] * stacking_factor
    h = e = 0.0
    harmonic_losses = []
    for index, order in enumerate(orders):
        f = speed_rpm/60 * order
        ph = float(np.sum(mass * coefficients["kh"] * f * amplitudes[index]**coefficients["alpha"]))
        pe = float(np.sum(mass * coefficients["kc"] * f*f * amplitudes[index]**2))
        h, e = h + ph, e + pe
        harmonic_losses.append({"mechanical_order": int(order), "frequency_Hz": f, "hysteresis_W": ph, "eddy_W": pe})
    if not math.isfinite(h+e):
        raise ValueError("reference loss is nonfinite")
    return {"hysteresis_W": h, "lamination_eddy_W": e, "total_W": h+e,
            "mass_kg": float(mass.sum()), "harmonics": harmonic_losses}
