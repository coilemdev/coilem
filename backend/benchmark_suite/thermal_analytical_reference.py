"""Independent closed-form references. No production thermal imports or matrix solver.

Derivations, node definitions and applicability are in ANALYTICAL_PROTOCOL.md.
Heat flows are positive out of the domain; temperatures are averages unless named
as boundary/interface values. All lengths, areas, conductivities and powers are SI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Reference:
    values: dict[str, float]
    datum_C: float
    rejection_contains: str | None = None
    details: dict = field(default_factory=dict)


def layered_reference(p):
    """Integrate k*A*T''=-Q/L in each layer; insulated left, cooled right.

    Incoming power F and generated power Q give mean-minus-right temperature
    (F/2+Q/3)*L/(k*A); left-minus-right is (F+Q/2)*L/(k*A).
    These include transported heat separately from heat generated in the layer.
    """
    layers = p["layers"]
    incoming, power = [], 0.0
    for layer in layers:
        incoming.append(power)
        power += layer["heat_W"]
    right = p["ambient_C"] + power * p["outer_resistance_K_W"]
    values = {"Q_ambient": power, "Q_balance": 0.0}
    interfaces = {}
    for i in reversed(range(len(layers))):
        layer = layers[i]
        resistance = layer["length_m"] / (layer["k_W_mK"] * p["area_m2"])
        flow, heat = incoming[i], layer["heat_W"]
        values["T_" + layer["name"]] = right + (flow / 2 + heat / 3) * resistance
        left = right + (flow + heat / 2) * resistance
        interfaces[layer["name"]] = dict(left_C=left, right_C=right, incoming_W=flow, outgoing_W=flow + heat)
        if i:
            right = left + flow * p["contacts_K_W"][i - 1]
    return Reference(values, p["ambient_C"], details={"interfaces": interfaces})


def copper_reference(p, *, two_nodes):
    alpha, ambient = p["alpha_per_K"], p["ambient_C"]
    if not two_nodes:
        heat, resistance = p["heat_20C_W"], p["resistance_K_W"]
        gain = alpha * heat * resistance
        if gain >= 1:
            return Reference({}, ambient, "No stable thermal equilibrium", {"loop_gain": gain})
        rise = resistance * heat * (1 + alpha * (ambient - 20)) / (1 - gain)
        power = heat * (1 + alpha * (ambient + rise - 20))
        return Reference(dict(T_winding=ambient + rise, Q_winding=power, Q_ambient=power,
                              Q_balance=0.0, loop_gain=gain), ambient)
    # Eliminate the housing temperature, then solve two scalar equations by
    # Cramer's rule. The larger eigenvalue of the 2x2 heat-response matrix has
    # an explicit quadratic formula; no production assembly/eigensolver is used.
    qw, qe, qh = p["active_heat_20C_W"], p["end_heat_20C_W"], p["housing_heat_W"]
    rw, re, rh = p["active_resistance_K_W"], p["end_resistance_K_W"], p["housing_resistance_K_W"]
    k11, k12 = alpha * (rh + rw) * qw, alpha * rh * qe
    k21, k22 = alpha * rh * qw, alpha * (rh + re) * qe
    gain = (k11 + k22 + math.sqrt((k11 - k22)**2 + 4 * k12 * k21)) / 2
    if gain >= 1:
        return Reference({}, ambient, "No stable thermal equilibrium", {"loop_gain": gain})
    a, b, c, d = 1 - k11, -k12, -k21, 1 - k22
    u = ambient - 20 + rh * (qw + qe + qh) + rw * qw
    v = ambient - 20 + rh * (qw + qe + qh) + re * qe
    x, y = (u * d - b * v) / (a * d - b * c), (a * v - u * c) / (a * d - b * c)
    pw, pe = qw * (1 + alpha * x), qe * (1 + alpha * y)
    total = pw + pe + qh
    return Reference(dict(T_winding=20 + x, T_end_winding=20 + y, T_housing=ambient + rh * total,
                          Q_winding=pw, Q_end_winding=pe, Q_ambient=total, Q_balance=0.0, loop_gain=gain), ambient)


def reference_for(case):
    p, family = case["parameters"], case["family"]
    if family == "layered":
        return layered_reference(p)
    if family in {"copper_one", "copper_two"}:
        return copper_reference(p, two_nodes=family == "copper_two")
    if family == "disconnected":
        return Reference({}, 20, "disconnected")
    heat = p["heat_W"]
    if family in {"series", "parallel"}:
        ambient, (r1, r2) = p["ambient_C"], p["resistances_K_W"]
        if family == "series":
            values = dict(T_winding=ambient + heat * (r1 + r2), T_housing=ambient + heat * r2)
        else:
            values = dict(T_winding=ambient + heat * r1 * r2 / (r1 + r2))
        return Reference(dict(values, Q_ambient=heat, Q_balance=0.0), ambient)
    if family == "two_boundaries":
        left, right = p["left_C"], p["right_C"]
        r1, r2 = p["resistances_K_W"]
        temperature = (heat * r1 * r2 + left * r2 + right * r1) / (r1 + r2)
        return Reference(dict(T_winding=temperature, Q_left=(temperature - left) / r1,
                              Q_right=(temperature - right) / r2, Q_balance=0.0), min(left, right))
    if family in {"slab", "split_slab"}:
        length, area, k = p["length_m"], p["area_m2"], p["k_W_mK"]
        generation = heat / (length * area)
        if family == "slab":
            rise = generation * length**2 / (k * (12 if p["two_sided"] else 3))
            return Reference(dict(T_mean=p["boundary_C"] + rise, Q_ambient=heat, Q_balance=0.0), p["boundary_C"])
        left, right = p["left_C"], p["right_C"]
        mean = (left + right) / 2 + generation * length**2 / (12 * k)
        left_flow = heat / 2 + k * area * (right - left) / length
        return Reference(dict(T_mean=mean, Q_left=left_flow, Q_right=heat - left_flow, Q_balance=0.0), min(left, right))
    if family == "cylinder":
        inner, outer, k, length = p["inner_radius_m"], p["outer_radius_m"], p["k_W_mK"], p["length_m"]
        # Integral of dT/dr=-Q/(2*pi*k*L*r), from outer to inner surface.
        rise = heat * (math.log(outer) - math.log(inner)) / (2 * math.pi * k * length)
        return Reference(dict(T_inner=p["boundary_C"] + rise, Q_ambient=heat, Q_balance=0.0), p["boundary_C"])
    raise ValueError(f"Unknown analytical family: {family}")
