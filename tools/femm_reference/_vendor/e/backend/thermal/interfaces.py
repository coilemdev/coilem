"""S50-03 thermal interface status helpers.

Slot-liner resistance and stator–housing contact conductance remain separate
model parameters. Physical defaults stay ``PENDING_SOURCE`` until cited
table/figure/equation locators land — this module never invents numbers.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from backend.thermal.material_ranges import (
    load_material_range_library,
    slot_by_id,
)

InterfaceId = Literal["slot_liner_interface", "stator_housing_contact_conductance"]
InterfaceStatus = Literal["pending", "user_supplied", "modeled"]

INTERFACE_SLOT_IDS: tuple[InterfaceId, ...] = (
    "slot_liner_interface",
    "stator_housing_contact_conductance",
)


def interface_slot_status(
    slot_id: InterfaceId,
    *,
    library: Mapping[str, Any] | None = None,
    user_value: float | None = None,
    modeled: bool = False,
) -> dict[str, Any]:
    """Status blob for one interface parameter.

    Priority:
    - ``modeled`` True and a finite user/extracted value → ``modeled``
    - finite ``user_value`` without modeled flag → ``user_supplied``
    - else follow the literature library extraction status (``pending``)
    """
    lib = library if library is not None else load_material_range_library()
    slot = slot_by_id(lib, slot_id)
    extraction = str(slot.get("extraction_status") or "PENDING_SOURCE")
    cited_value = None
    if extraction == "EXTRACTED":
        nom = slot.get("nominal")
        if isinstance(nom, (int, float)):
            cited_value = float(nom)

    value = user_value if user_value is not None else cited_value
    resolved_value: float | None = None
    if isinstance(value, (int, float)):
        candidate = float(value)
        if candidate == candidate and candidate > 0.0:
            resolved_value = candidate

    has_value = resolved_value is not None

    if modeled and has_value:
        status: InterfaceStatus = "modeled"
    elif user_value is not None and has_value:
        status = "user_supplied"
    else:
        status = "pending"

    return {
        "id": slot_id,
        "status": status,
        "extraction_status": extraction,
        "value": resolved_value if status != "pending" else None,
        "units": slot.get("units"),
        "thermal_role": slot.get("thermal_role"),
        "pending_note": slot.get("pending_note"),
        "source": slot.get("source"),
        "representation": "zero_thickness_contact" if status == "modeled" else None,
    }


def interface_capability_payload(
    *,
    library: Mapping[str, Any] | None = None,
    slot_liner_user_value: float | None = None,
    housing_contact_user_value: float | None = None,
    slot_liner_modeled: bool = False,
    housing_contact_modeled: bool = False,
) -> dict[str, Any]:
    """Capability / result fragment for API + UI warnings.

    The "temperatures biased low" warning clears only when *both* interfaces
    are ``modeled``. Pending literature slots keep absolute-temperature blocked.
    """
    lib = library if library is not None else load_material_range_library()
    liner = interface_slot_status(
        "slot_liner_interface",
        library=lib,
        user_value=slot_liner_user_value,
        modeled=slot_liner_modeled,
    )
    housing = interface_slot_status(
        "stator_housing_contact_conductance",
        library=lib,
        user_value=housing_contact_user_value,
        modeled=housing_contact_modeled,
    )
    both_active = liner["status"] == "modeled" and housing["status"] == "modeled"
    return {
        "openem_convention_tag": "s50_03_thermal_interfaces_v1",
        "representation": "zero_thickness_contact",
        "interfaces": {
            "slot_liner_interface": liner,
            "stator_housing_contact_conductance": housing,
        },
        "both_interfaces_active": both_active,
        # Honest capability stamp: the API accepts modeled=true for
        # bookkeeping, but no ThermalContactSet is built from these values
        # yet — the 2D FEA solve is unchanged. Consumers must not treat
        # "modeled" as "injected into the field solution" until this flips.
        "applied_to_fea": False,
        "temperatures_biased_low_warning": not both_active,
        "absolute_temperature_status": (
            "interfaces_modeled_not_validated" if both_active else "not_validated"
        ),
        "note": (
            "Both slot-liner and stator–housing contacts are marked modeled "
            "for capability bookkeeping, but zero-thickness contact injection "
            "into the 2D FEA is not wired yet (applied_to_fea=false). "
            "Absolute-temperature validation still requires the hybrid "
            "end/coolant network (S50-04) and the frozen ORNL gate."
            if both_active
            else "Slot-liner and/or housing-contact interfaces are not both "
            "modeled — temperatures remain biased low. Physical defaults stay "
            "PENDING_SOURCE until cited locators land; do not invent numbers."
        ),
    }
