"""Hybrid thermal FEA package (S48/S49).

All public entry points are gated by ``OPENEM_THERMAL_ENABLED``. When the flag
is off, callers should treat thermal as unavailable — no routes, no solver
mode, no UI stage.
"""

from __future__ import annotations

from backend.feature_flags import thermal_enabled
from backend.thermal.hybrid_network import PROVENANCE_TAG as HYBRID_NETWORK_TAG
from backend.thermal.interfaces import interface_capability_payload
from backend.thermal.magnet_temperature import derate_magnet_properties
from backend.thermal.material_ranges import (
    load_material_range_library,
    resolve_corner_parameters,
)

__all__ = [
    "thermal_enabled",
    "thermal_capability_payload",
    "derate_magnet_properties",
    "load_material_range_library",
    "resolve_corner_parameters",
    "interface_capability_payload",
]


def thermal_capability_payload() -> dict[str, object]:
    """Capability blob for /health and similar discovery endpoints."""
    enabled = thermal_enabled()
    if not enabled:
        return {
            "enabled": False,
            "mode": None,
            "parity_lane": None,
            "solve_endpoint": None,
            "length_units": None,
            "loss_map_schema": None,
            "temperature_scope": None,
            "absolute_temperature_status": None,
            "pending_physics": [],
            "interfaces": None,
            "hybrid_network": None,
            "feature_flag": "OPENEM_THERMAL_ENABLED",
        }

    interfaces = interface_capability_payload()
    pending = [
        "end_region_network_parameters",
        "coolant_correlation",
    ]
    if not interfaces["both_interfaces_active"]:
        pending.extend(
            [
                "slot_liner_interface",
                "stator_housing_contact",
            ]
        )
    return {
        "enabled": True,
        "mode": "steady_state_conduction",
        "parity_lane": "phase_d",
        "solve_endpoint": "/thermal/solve",
        "length_units": "m",
        "loss_map_schema": "thermal_loss_map/v2",
        "temperature_scope": "active_stack_2d",
        "absolute_temperature_status": interfaces["absolute_temperature_status"],
        "pending_physics": pending,
        "interfaces": interfaces,
        "hybrid_network": {
            "openem_convention_tag": HYBRID_NETWORK_TAG,
            "available": True,
            "default_status": "pending",
            "note": (
                "POST /thermal/solve returns hybrid_network. End-winding "
                "copper from thermal_loss_map/v2 is injected once when "
                "present; conductances/coolant correlation stay pending "
                "until user-supplied or cited."
            ),
        },
        "feature_flag": "OPENEM_THERMAL_ENABLED",
    }
