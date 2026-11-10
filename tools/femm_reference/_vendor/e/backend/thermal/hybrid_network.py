"""S50-04 hybrid end-region + coolant network (steady-state).

Couples active-stack 2D FEA observables to a typed lumped network so
end-winding copper from ``thermal_loss_map/v2`` is injected exactly once
into the end node and never re-concentrated into the 2D slots.

Hard rule: every conductance / coolant correlation must be user-supplied
or cited (``EXTRACTED``). Missing values stay ``PENDING_SOURCE`` — this
module never invents film coefficients or Prius-tuned resistances.
"""

from __future__ import annotations

import math
from typing import Any, Literal, Mapping

PROVENANCE_TAG = "s50_04_hybrid_end_network_v1"
SCHEMA_VERSION = "s50_04_v1"

NetworkStatus = Literal["pending", "partial", "solved"]
PathStatus = Literal["pending", "user_supplied", "modeled"]

# Sign convention (documented for API consumers):
#   Positive heat into a node = source or inbound conductance flow.
#   Positive heat leaving the machine = rejected to ambient / coolant.
#   Steady state: Σ sources = Σ rejected (whole-machine closure).
SIGN_UNIT_CONVENTION = {
    "temperature": "K",
    "power": "W",
    "conductance": "W/K",
    "mass_flow": "kg/s",
    "specific_heat": "J/(kg·K)",
    "heat_into_node_positive": True,
    "heat_rejected_from_machine_positive": True,
    "note": (
        "End-winding copper from thermal_loss_map/v2 is injected once at "
        "the end_winding node. Active-stack copper+core remain in the 2D "
        "FEA source term only."
    ),
}

OBSERVABLE_MAP = {
    "active_stack_hotspot_k": "2D FEA max nodal temperature (active stack)",
    "active_stack_mean_k": "2D FEA mean nodal temperature",
    "end_winding_hotspot_k": "Network end_winding node temperature",
    "end_winding_mean_k": "Same as end_winding node (0-D lump)",
    "housing_k": "Network housing/end-cap node temperature",
    "coolant_outlet_k": "Coolant outlet from energy balance on coolant node",
    "coolant_inlet_k": "User/cited coolant inlet boundary",
    "total_rejected_heat_w": "Σ heat leaving machine (FEA BC + network sinks)",
}


class HybridNetworkError(ValueError):
    """Invalid hybrid network inputs or solve failure."""


def _finite_positive(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise HybridNetworkError(f"{name} must be a finite number") from exc
    if not math.isfinite(out) or out <= 0.0:
        raise HybridNetworkError(f"{name} must be finite and strictly positive")
    return out


def _finite(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise HybridNetworkError(f"{name} must be a finite number") from exc
    if not math.isfinite(out):
        raise HybridNetworkError(f"{name} must be finite")
    return out


def end_winding_copper_w_from_loss_map(loss_map: Mapping[str, Any] | None) -> float | None:
    """Extract end-winding copper watts retained for the hybrid network.

    The network's conductances, coolant loop, and ambient path describe the
    whole machine, so full-machine watts are preferred. Sector-scaled totals
    are only a fallback for legacy maps without ``symmetry`` bookkeeping —
    on a sector mesh those under-inject end heat by the sector factor.
    """
    if not isinstance(loss_map, Mapping):
        return None
    symmetry = loss_map.get("symmetry")
    if (
        isinstance(symmetry, Mapping)
        and symmetry.get("end_winding_copper_loss_full_w") is not None
    ):
        return float(symmetry["end_winding_copper_loss_full_w"])
    totals = loss_map.get("totals_w")
    if isinstance(totals, Mapping) and totals.get("end_winding_copper_loss_w") is not None:
        return float(totals["end_winding_copper_loss_w"])
    temp = loss_map.get("temperature_model")
    if isinstance(temp, Mapping) and temp.get("unresolved_end_winding_copper_w") is not None:
        return float(temp["unresolved_end_winding_copper_w"])
    return None


def _path_status(value: float | None, *, modeled: bool) -> PathStatus:
    if value is None:
        return "pending"
    if modeled:
        return "modeled"
    return "user_supplied"


def solve_hybrid_end_network(
    *,
    end_winding_copper_w: float,
    active_stack_hotspot_k: float | None = None,
    active_stack_mean_k: float | None = None,
    fea_boundary_outflow_w: float | None = None,
    fea_injected_power_w: float | None = None,
    # Network parameters — None means PENDING (no invented defaults).
    g_end_to_housing_w_per_k: float | None = None,
    g_housing_to_ambient_w_per_k: float | None = None,
    ambient_k: float | None = None,
    # Coolant path (Prius water-jacket style). All required together.
    coolant_inlet_k: float | None = None,
    coolant_mass_flow_kg_per_s: float | None = None,
    coolant_cp_j_per_kg_k: float | None = None,
    g_housing_to_coolant_w_per_k: float | None = None,
    # Optional FEA housing coupling temperature (K). When set, housing is
    # anchored toward this value through g_housing_to_fea_w_per_k.
    fea_housing_k: float | None = None,
    g_housing_to_fea_w_per_k: float | None = None,
) -> dict[str, Any]:
    """Solve (or report pending) the steady-state hybrid network.

    Analytic / user-supplied parameters only. Coolant outlet is predicted
    only when inlet, flow, cp, and housing→coolant conductance are all set.
    """
    p_end = _finite(end_winding_copper_w, "end_winding_copper_w")
    if p_end < 0.0:
        raise HybridNetworkError("end_winding_copper_w must be >= 0")

    unresolved: list[str] = []
    paths: dict[str, Any] = {
        "g_end_to_housing_w_per_k": {
            "status": _path_status(g_end_to_housing_w_per_k, modeled=False),
            "value": g_end_to_housing_w_per_k,
        },
        "g_housing_to_ambient_w_per_k": {
            "status": _path_status(g_housing_to_ambient_w_per_k, modeled=False),
            "value": g_housing_to_ambient_w_per_k,
        },
        "coolant": {
            "status": "pending",
            "inlet_k": coolant_inlet_k,
            "mass_flow_kg_per_s": coolant_mass_flow_kg_per_s,
            "cp_j_per_kg_k": coolant_cp_j_per_kg_k,
            "g_housing_to_coolant_w_per_k": g_housing_to_coolant_w_per_k,
            "correlation_status": "PENDING_SOURCE",
            "note": (
                "Coolant outlet requires cited/user inlet, flow, cp, and "
                "housing→coolant conductance. water_jacket_h film slot stays "
                "PENDING_SOURCE until a geometry-aware correlation is transcribed."
            ),
        },
    }

    coolant_ready = all(
        v is not None
        for v in (
            coolant_inlet_k,
            coolant_mass_flow_kg_per_s,
            coolant_cp_j_per_kg_k,
            g_housing_to_coolant_w_per_k,
        )
    )
    if coolant_ready:
        paths["coolant"]["status"] = "user_supplied"
        paths["coolant"]["correlation_status"] = "user_supplied"
    else:
        unresolved.append("coolant_path")

    has_ambient_path = (
        g_housing_to_ambient_w_per_k is not None and ambient_k is not None
    )
    has_fea_couple = (
        fea_housing_k is not None and g_housing_to_fea_w_per_k is not None
    )
    core_ready = g_end_to_housing_w_per_k is not None and (
        has_ambient_path or coolant_ready or has_fea_couple
    )
    if g_end_to_housing_w_per_k is None:
        unresolved.append("g_end_to_housing_w_per_k")
    if g_housing_to_ambient_w_per_k is not None and ambient_k is None:
        unresolved.append("ambient_k")
    if not has_ambient_path and not coolant_ready and not has_fea_couple:
        unresolved.append("housing_heat_rejection_path")

    base: dict[str, Any] = {
        "openem_convention_tag": PROVENANCE_TAG,
        "schema_version": SCHEMA_VERSION,
        "sign_unit_convention": SIGN_UNIT_CONVENTION,
        "observable_map": OBSERVABLE_MAP,
        "end_winding_copper_injected_w": p_end,
        "end_winding_injection": {
            "source": "thermal_loss_map/v2",
            "node": "end_winding",
            "watts": p_end,
            "injected_once": True,
            "not_in_2d_slots": True,
        },
        "paths": paths,
        "unresolved_paths": unresolved,
        "status": "pending",
        "observables": {
            "active_stack_hotspot_k": active_stack_hotspot_k,
            "active_stack_mean_k": active_stack_mean_k,
            "end_winding_hotspot_k": None,
            "end_winding_mean_k": None,
            "housing_k": None,
            "magnet_k": None,
            "coolant_inlet_k": coolant_inlet_k,
            "coolant_outlet_k": None,
            "total_rejected_heat_w": None,
            "fea_boundary_outflow_w": fea_boundary_outflow_w,
            "fea_injected_power_w": fea_injected_power_w,
        },
        "heat_balance": None,
        "absolute_temperature_status": "not_validated",
        "note": (
            "Hybrid network pending cited/user conductances and/or coolant "
            "correlation. End-winding copper is retained for injection and is "
            "not dropped."
        ),
    }

    if not core_ready:
        return base

    # --- Linear 2-node (end, housing) + optional coolant / FEA anchors ---
    g_eh = _finite_positive(g_end_to_housing_w_per_k, "g_end_to_housing_w_per_k")
    t_amb = _finite(ambient_k, "ambient_k") if ambient_k is not None else None
    # The ambient path participates only when BOTH conductance and ambient
    # temperature are supplied. A conductance without its temperature must
    # not enter the nodal equations — including it in the denominator while
    # omitting its RHS term is an implicit 0 K sink that silently depresses
    # every temperature in a payload still labelled "solved".
    g_ha = (
        _finite_positive(g_housing_to_ambient_w_per_k, "g_housing_to_ambient_w_per_k")
        if (g_housing_to_ambient_w_per_k is not None and t_amb is not None)
        else 0.0
    )

    g_hc = 0.0
    t_in = None
    m_dot = None
    cp = None
    if coolant_ready:
        g_hc = _finite_positive(
            g_housing_to_coolant_w_per_k, "g_housing_to_coolant_w_per_k"
        )
        t_in = _finite(coolant_inlet_k, "coolant_inlet_k")
        m_dot = _finite_positive(
            coolant_mass_flow_kg_per_s, "coolant_mass_flow_kg_per_s"
        )
        cp = _finite_positive(coolant_cp_j_per_kg_k, "coolant_cp_j_per_kg_k")

    g_hf = 0.0
    t_fea = None
    if fea_housing_k is not None and g_housing_to_fea_w_per_k is not None:
        g_hf = _finite_positive(
            g_housing_to_fea_w_per_k, "g_housing_to_fea_w_per_k"
        )
        t_fea = _finite(fea_housing_k, "fea_housing_k")

    # Effective coolant node: for steady state with prescribed inlet and
    # capacity rate C = m_dot*cp, heat to coolant Q_c = G_hc (T_h - T_c_eff)
    # with T_c_eff ≈ T_in when C >> G (cold-fluid limit) or more generally
    # the NTU lump T_c_eff = T_in + Q_c / C  ⇒  Q_c = G_eff (T_h - T_in)
    # where G_eff = 1 / (1/G_hc + 1/C).
    g_cool_eff = 0.0
    if coolant_ready and m_dot is not None and cp is not None and t_in is not None:
        capacity = m_dot * cp
        g_cool_eff = 1.0 / (1.0 / g_hc + 1.0 / capacity)

    # Housing equation:
    #   G_eh (T_e - T_h) + G_ha (T_amb - T_h) + G_cool_eff (T_in - T_h)
    #   + G_hf (T_fea - T_h) = 0
    # End equation:
    #   P_end + G_eh (T_h - T_e) = 0  ⇒  T_e = T_h + P_end / G_eh
    #
    # Substitute into housing:
    #   P_end + G_ha (T_amb - T_h) + G_cool_eff (T_in - T_h) + G_hf (T_fea - T_h) = 0
    denom = g_ha + g_cool_eff + g_hf
    if denom <= 0.0:
        base["status"] = "partial"
        base["unresolved_paths"] = list(dict.fromkeys([*unresolved, "housing_heat_rejection_path"]))
        base["note"] = (
            "End→housing conductance present but no housing rejection path "
            "(ambient, coolant, or FEA coupling)."
        )
        return base

    rhs = p_end
    if g_ha > 0.0 and t_amb is not None:
        rhs += g_ha * t_amb
    if g_cool_eff > 0.0 and t_in is not None:
        rhs += g_cool_eff * t_in
    if g_hf > 0.0 and t_fea is not None:
        rhs += g_hf * t_fea

    t_housing = rhs / denom
    t_end = t_housing + p_end / g_eh

    q_amb = g_ha * (t_housing - t_amb) if (g_ha > 0.0 and t_amb is not None) else 0.0
    q_cool = g_cool_eff * (t_housing - t_in) if (g_cool_eff > 0.0 and t_in is not None) else 0.0
    q_fea_couple = (
        g_hf * (t_housing - t_fea) if (g_hf > 0.0 and t_fea is not None) else 0.0
    )
    # Heat from end into housing equals P_end at steady state.
    q_end_to_housing = p_end

    t_cool_out = None
    if coolant_ready and m_dot is not None and cp is not None and t_in is not None:
        t_cool_out = t_in + q_cool / (m_dot * cp)

    fea_out = float(fea_boundary_outflow_w) if fea_boundary_outflow_w is not None else 0.0
    fea_in = float(fea_injected_power_w) if fea_injected_power_w is not None else fea_out
    # Whole-machine rejected = FEA boundary outflow + network ambient + coolant
    # (FEA↔housing couple is internal transfer, not machine rejection).
    total_rejected = fea_out + q_amb + q_cool
    total_sources = fea_in + p_end
    residual = total_sources - total_rejected - q_fea_couple
    # When FEA couple is used, that heat leaves/enters the network from the
    # FEA domain already counted in fea_out; treat couple as internal and
    # close on sources vs (fea_out + q_amb + q_cool).
    residual_machine = total_sources - total_rejected
    scale = max(abs(total_sources), abs(total_rejected), 1.0e-12)
    closed = abs(residual_machine) / scale <= 5.0e-2 or abs(residual_machine) <= 1.0e-3

    status: NetworkStatus = "solved"
    # Coolant may remain unresolved while the end/housing network is solved.
    if "g_end_to_housing_w_per_k" in unresolved or "housing_heat_rejection_path" in unresolved:
        status = "partial"
    elif "ambient_k" in unresolved:
        # A supplied g_housing_to_ambient could not be used (no ambient
        # temperature); the returned temperatures exclude that path.
        status = "partial"
    elif unresolved and not (has_ambient_path or coolant_ready or has_fea_couple):
        status = "partial"
    base.update(
        {
            "status": status,
            "unresolved_paths": unresolved,
            "nodes": {
                "end_winding_k": t_end,
                "housing_k": t_housing,
                "ambient_k": t_amb,
                "coolant_inlet_k": t_in,
                "coolant_outlet_k": t_cool_out,
                "fea_housing_k": t_fea,
            },
            "observables": {
                "active_stack_hotspot_k": active_stack_hotspot_k,
                "active_stack_mean_k": active_stack_mean_k,
                "end_winding_hotspot_k": t_end,
                "end_winding_mean_k": t_end,
                "housing_k": t_housing,
                "magnet_k": None,
                "coolant_inlet_k": t_in,
                "coolant_outlet_k": t_cool_out,
                "total_rejected_heat_w": total_rejected,
                "fea_boundary_outflow_w": fea_boundary_outflow_w,
                "fea_injected_power_w": fea_injected_power_w,
            },
            "heat_balance": {
                "end_winding_copper_w": p_end,
                "fea_injected_power_w": fea_in,
                "total_sources_w": total_sources,
                "fea_boundary_outflow_w": fea_out,
                "network_ambient_rejected_w": q_amb,
                "network_coolant_rejected_w": q_cool,
                "network_fea_couple_w": q_fea_couple,
                "end_to_housing_w": q_end_to_housing,
                "total_rejected_w": total_rejected,
                "residual_w": residual_machine,
                "relative_residual": abs(residual_machine) / scale,
                "closed": closed,
                "internal_residual_w": residual,
            },
            "note": (
                "Hybrid network solved with user-supplied conductances. "
                "Absolute-temperature validation still requires cited "
                "interface ranges (S50-03) and the frozen ORNL gate (S50-05)."
                if status == "solved"
                else "Hybrid network partially solved; some paths remain pending."
            ),
            "absolute_temperature_status": "not_validated",
        }
    )
    return base


def build_hybrid_network_from_thermal_result(
    *,
    loss_map: Mapping[str, Any] | None,
    report: Mapping[str, Any] | None,
    network_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Postprocess hook shared by magneto2d / FEMM thermal lanes.

    Reads end-winding watts from the v2 loss map and optional user network
    parameters. Missing params → pending payload (no invented defaults).
    """
    params = dict(network_params or {})
    end_w = end_winding_copper_w_from_loss_map(loss_map)
    if end_w is None:
        return {
            "openem_convention_tag": PROVENANCE_TAG,
            "schema_version": SCHEMA_VERSION,
            "status": "pending",
            "end_winding_copper_injected_w": None,
            "unresolved_paths": ["end_winding_copper_w"],
            "note": (
                "No thermal_loss_map/v2 end-winding copper available; "
                "hybrid network not run."
            ),
            "absolute_temperature_status": "not_validated",
            "sign_unit_convention": SIGN_UNIT_CONVENTION,
            "observable_map": OBSERVABLE_MAP,
        }

    energy = report.get("energy_balance") if isinstance(report, Mapping) else None
    fea_out = None
    fea_in = None
    if isinstance(energy, Mapping):
        if energy.get("boundary_outflow_w") is not None:
            fea_out = float(energy["boundary_outflow_w"])
        if energy.get("volumetric_source_w") is not None:
            fea_in = float(energy["volumetric_source_w"])

    hotspot = None
    mean_t = None
    if isinstance(report, Mapping):
        if report.get("max_temperature_k") is not None:
            hotspot = float(report["max_temperature_k"])
        if report.get("mean_temperature_k") is not None:
            mean_t = float(report["mean_temperature_k"])

    def _opt_float(key: str) -> float | None:
        if key not in params or params[key] is None:
            return None
        return float(params[key])

    return solve_hybrid_end_network(
        end_winding_copper_w=end_w,
        active_stack_hotspot_k=hotspot,
        active_stack_mean_k=mean_t,
        fea_boundary_outflow_w=fea_out,
        fea_injected_power_w=fea_in,
        g_end_to_housing_w_per_k=_opt_float("g_end_to_housing_w_per_k"),
        g_housing_to_ambient_w_per_k=_opt_float("g_housing_to_ambient_w_per_k"),
        ambient_k=_opt_float("ambient_k"),
        coolant_inlet_k=_opt_float("coolant_inlet_k"),
        coolant_mass_flow_kg_per_s=_opt_float("coolant_mass_flow_kg_per_s"),
        coolant_cp_j_per_kg_k=_opt_float("coolant_cp_j_per_kg_k"),
        g_housing_to_coolant_w_per_k=_opt_float("g_housing_to_coolant_w_per_k"),
        fea_housing_k=_opt_float("fea_housing_k"),
        g_housing_to_fea_w_per_k=_opt_float("g_housing_to_fea_w_per_k"),
    )
