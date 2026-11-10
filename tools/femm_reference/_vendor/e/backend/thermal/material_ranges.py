"""S49-01 literature-range thermal material library.

Loads the pre-registered artifact under
``qa/s49_01_thermal_material_ranges/`` and resolves hot / nominal / cold
corners for thermal FEA.

Hard rule (Mac, 2026-07-08): every low/nominal/high must cite a source or
remain ``null`` with ``extraction_status: PENDING_SOURCE``. This module
never invents numbers — it only validates and resolves what the artifact
already contains.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIBRARY_PATH = (
    REPO_ROOT
    / "qa"
    / "s49_01_thermal_material_ranges"
    / "s49_01_thermal_material_ranges.json"
)

PROVENANCE_TAG = "s49_literature_range_v1"
SCHEMA_VERSION = "s49_01_v1"
ARTIFACT_KIND = "s49_01_thermal_material_literature_ranges"

CornerName = Literal["hot", "nominal", "cold"]
ExtractionStatus = Literal["PENDING_SOURCE", "EXTRACTED"]
ThermalRole = Literal["conductivity", "conductance", "resistance"]

REQUIRED_SLOT_IDS: tuple[str, ...] = (
    "impregnated_winding_k_in_plane",
    "impregnated_winding_k_through",
    "lamination_stack_k_in_plane",
    "lamination_stack_k_through",
    "slot_liner_interface",
    "stator_housing_contact_conductance",
)

# Structural defaults for corner polarity (not physical values).
# conductivity / conductance: hotter machine ⇒ lower parameter value.
# resistance: hotter machine ⇒ higher parameter value.
DEFAULT_THERMAL_ROLES: dict[str, ThermalRole] = {
    "impregnated_winding_k_in_plane": "conductivity",
    "impregnated_winding_k_through": "conductivity",
    "lamination_stack_k_in_plane": "conductivity",
    "lamination_stack_k_through": "conductivity",
    "slot_liner_interface": "resistance",
    "stator_housing_contact_conductance": "conductance",
    "air_k": "conductivity",
    "magnet_k": "conductivity",
    "shaft_k": "conductivity",
}

# 2D cross-section region → conductivity slot (in-plane). Through-stack and
# interface slots are reserved for S49-01 interface layers / 3D later.
# Air-like / magnet / shaft regions MUST map here — never silently fall back
# to steel-like k under the literature tag (#92 review finding).
REGION_CONDUCTIVITY_SLOT: dict[str, str] = {
    "SlotWinding": "impregnated_winding_k_in_plane",
    "StatorTooth": "lamination_stack_k_in_plane",
    "StatorYoke": "lamination_stack_k_in_plane",
    "RotorCore": "lamination_stack_k_in_plane",
    "Airgap": "air_k",
    "Air": "air_k",
    "OuterAir": "air_k",
    "InnerAir": "air_k",
    "MagnetPocketAir": "air_k",
    "FluxBarrier": "air_k",
    "ExteriorAir": "air_k",
    "Magnet": "magnet_k",
    "RotorMagnet": "magnet_k",
    "PM": "magnet_k",
    "Shaft": "shaft_k",
}


class MaterialRangeError(ValueError):
    """Invalid literature-range library or corner resolution failure."""


def default_library_path() -> Path:
    return DEFAULT_LIBRARY_PATH


def literature_conductivity_slots_ready(
    library: Mapping[str, Any] | None = None,
) -> bool:
    """True when every region-mapped conductivity slot is EXTRACTED.

    Interface slots (slot liner, housing contact) may remain PENDING without
    blocking 2D literature materials — they are not in
    :data:`REGION_CONDUCTIVITY_SLOT`.
    """
    lib = library if library is not None else load_material_range_library()
    needed = set(REGION_CONDUCTIVITY_SLOT.values())
    for slot in lib.get("parameter_slots") or []:
        if not isinstance(slot, dict):
            continue
        slot_id = str(slot.get("id") or "")
        if slot_id not in needed:
            continue
        if slot.get("extraction_status") != "EXTRACTED":
            return False
        needed.discard(slot_id)
    return not needed


def load_material_range_library(
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Load and validate the S49-01 literature-range artifact."""
    lib_path = Path(path) if path is not None else DEFAULT_LIBRARY_PATH
    if not lib_path.is_file():
        raise MaterialRangeError(f"material range library not found: {lib_path}")
    try:
        data = json.loads(lib_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MaterialRangeError(f"invalid JSON in {lib_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise MaterialRangeError("material range library root must be an object")
    validate_material_range_library(data)
    return data


def validate_material_range_library(data: Mapping[str, Any]) -> None:
    """Enforce schema + hard rule (no invented unsourced numbers)."""
    if data.get("artifact_kind") != ARTIFACT_KIND:
        raise MaterialRangeError(
            f"artifact_kind must be {ARTIFACT_KIND!r}, got {data.get('artifact_kind')!r}"
        )
    if data.get("schema_version") != SCHEMA_VERSION:
        raise MaterialRangeError(
            f"schema_version must be {SCHEMA_VERSION!r}, got {data.get('schema_version')!r}"
        )
    if data.get("openem_convention_tag") != PROVENANCE_TAG:
        raise MaterialRangeError(
            f"openem_convention_tag must be {PROVENANCE_TAG!r}, "
            f"got {data.get('openem_convention_tag')!r}"
        )
    if data.get("status") not in {"PRE_REGISTERED", "PARTIAL", "COMPLETE"}:
        raise MaterialRangeError(
            f"status must be PRE_REGISTERED|PARTIAL|COMPLETE, got {data.get('status')!r}"
        )

    corners = data.get("corner_definitions")
    if not isinstance(corners, dict):
        raise MaterialRangeError("corner_definitions object required")
    for key in ("hot", "nominal", "cold", "monotonicity_assumption"):
        if not corners.get(key):
            raise MaterialRangeError(f"corner_definitions.{key} required")

    slots = data.get("parameter_slots")
    if not isinstance(slots, list) or not slots:
        raise MaterialRangeError("parameter_slots must be a non-empty list")

    seen: set[str] = set()
    for slot in slots:
        if not isinstance(slot, dict):
            raise MaterialRangeError("each parameter_slots entry must be an object")
        _validate_slot(slot)
        slot_id = str(slot["id"])
        if slot_id in seen:
            raise MaterialRangeError(f"duplicate parameter slot id={slot_id!r}")
        seen.add(slot_id)

    missing = [sid for sid in REQUIRED_SLOT_IDS if sid not in seen]
    if missing:
        raise MaterialRangeError(f"missing required parameter slots: {missing}")

    if "amendments" in data and not isinstance(data["amendments"], list):
        raise MaterialRangeError("amendments must be a list")


def _validate_slot(slot: Mapping[str, Any]) -> None:
    slot_id = slot.get("id")
    if not isinstance(slot_id, str) or not slot_id:
        raise MaterialRangeError("parameter slot id required")

    if slot.get("provenance") != PROVENANCE_TAG:
        raise MaterialRangeError(
            f"slot {slot_id!r} provenance must be {PROVENANCE_TAG!r}"
        )

    status = slot.get("extraction_status")
    if status not in {"PENDING_SOURCE", "EXTRACTED"}:
        raise MaterialRangeError(
            f"slot {slot_id!r} extraction_status must be "
            f"PENDING_SOURCE|EXTRACTED, got {status!r}"
        )

    for key in ("nominal", "low", "high"):
        if key not in slot:
            raise MaterialRangeError(f"slot {slot_id!r} missing field {key!r}")

    nominal, low, high = slot["nominal"], slot["low"], slot["high"]

    if status == "PENDING_SOURCE":
        if nominal is not None or low is not None or high is not None:
            raise MaterialRangeError(
                f"slot {slot_id!r} is PENDING_SOURCE but has non-null "
                f"low/nominal/high — hard rule: no invented numbers"
            )
        return

    # EXTRACTED
    if nominal is None or low is None or high is None:
        raise MaterialRangeError(
            f"slot {slot_id!r} is EXTRACTED but low/nominal/high incomplete"
        )
    try:
        n_f, l_f, h_f = float(nominal), float(low), float(high)
    except (TypeError, ValueError) as exc:
        raise MaterialRangeError(
            f"slot {slot_id!r} low/nominal/high must be numeric"
        ) from exc

    if not (l_f <= n_f <= h_f):
        raise MaterialRangeError(
            f"slot {slot_id!r} band ordering violated: "
            f"low={l_f} nominal={n_f} high={h_f} (need low ≤ nominal ≤ high)"
        )

    source = slot.get("source")
    if not isinstance(source, dict) or not source:
        raise MaterialRangeError(
            f"slot {slot_id!r} EXTRACTED requires non-empty source object "
            f"(cite table/figure/equation)"
        )
    for key in ("citation", "locator"):
        if not source.get(key):
            raise MaterialRangeError(
                f"slot {slot_id!r} source.{key} required when EXTRACTED"
            )

    validity = slot.get("validity_range")
    if not isinstance(validity, dict) or not validity:
        raise MaterialRangeError(
            f"slot {slot_id!r} EXTRACTED requires validity_range object"
        )

    if not slot.get("units"):
        raise MaterialRangeError(f"slot {slot_id!r} EXTRACTED requires units")

    role = slot.get("thermal_role") or DEFAULT_THERMAL_ROLES.get(slot_id)
    if role not in {"conductivity", "conductance", "resistance"}:
        raise MaterialRangeError(
            f"slot {slot_id!r} thermal_role must be "
            f"conductivity|conductance|resistance, got {role!r}"
        )


def slot_by_id(library: Mapping[str, Any], slot_id: str) -> dict[str, Any]:
    for slot in library.get("parameter_slots") or []:
        if isinstance(slot, dict) and slot.get("id") == slot_id:
            return dict(slot)
    raise MaterialRangeError(f"unknown parameter slot id={slot_id!r}")


def thermal_role_for_slot(slot: Mapping[str, Any]) -> ThermalRole:
    slot_id = str(slot.get("id", ""))
    role = slot.get("thermal_role") or DEFAULT_THERMAL_ROLES.get(slot_id)
    if role not in {"conductivity", "conductance", "resistance"}:
        raise MaterialRangeError(
            f"slot {slot_id!r} missing thermal_role and no default mapping"
        )
    return role  # type: ignore[return-value]


def pending_slot_ids(library: Mapping[str, Any]) -> list[str]:
    return [
        str(slot["id"])
        for slot in library.get("parameter_slots") or []
        if isinstance(slot, dict) and slot.get("extraction_status") == "PENDING_SOURCE"
    ]


def extracted_slot_ids(library: Mapping[str, Any]) -> list[str]:
    return [
        str(slot["id"])
        for slot in library.get("parameter_slots") or []
        if isinstance(slot, dict) and slot.get("extraction_status") == "EXTRACTED"
    ]


def resolve_slot_corner(
    slot: Mapping[str, Any],
    corner: CornerName,
) -> float | None:
    """Return the numeric value for one slot at a corner, or None if pending."""
    if slot.get("extraction_status") == "PENDING_SOURCE":
        return None
    if corner == "nominal":
        return float(slot["nominal"])

    role = thermal_role_for_slot(slot)
    low, high = float(slot["low"]), float(slot["high"])
    # hot = worse heat rejection / higher thermal resistance
    if corner == "hot":
        return high if role == "resistance" else low
    # cold
    return low if role == "resistance" else high


def resolve_corner_parameters(
    library: Mapping[str, Any],
    corner: CornerName,
    *,
    require_extracted: bool = False,
) -> dict[str, float | None]:
    """Map every slot id → corner value (None when PENDING_SOURCE)."""
    if corner not in {"hot", "nominal", "cold"}:
        raise MaterialRangeError(f"unknown corner {corner!r}")
    out: dict[str, float | None] = {}
    for slot in library.get("parameter_slots") or []:
        if not isinstance(slot, dict):
            continue
        slot_id = str(slot["id"])
        value = resolve_slot_corner(slot, corner)
        if require_extracted and value is None:
            raise MaterialRangeError(
                f"corner={corner!r} requires EXTRACTED slot {slot_id!r}; "
                f"still PENDING_SOURCE"
            )
        out[slot_id] = value
    return out


def band_triplet(
    cold: float,
    nominal: float,
    hot: float,
) -> dict[str, float]:
    """Build ``{nominal, band_low, band_high}`` for a temperature (or similar).

    ``band_low`` is the cold-corner result; ``band_high`` is the hot-corner
    result. Ordering is asserted (cold ≤ nominal ≤ hot under the monotonicity
    assumption for temperature). Use for **hotspot** only — per-region means
    can invert under mixed resistance/conductance corners; use
    :func:`band_envelope` there.
    """
    if not (cold <= nominal <= hot):
        raise MaterialRangeError(
            f"temperature band ordering violated: "
            f"cold={cold} nominal={nominal} hot={hot}"
        )
    return {
        "nominal": float(nominal),
        "band_low": float(cold),
        "band_high": float(hot),
    }


def band_envelope(
    cold: float,
    nominal: float,
    hot: float,
) -> dict[str, float]:
    """Build ``{nominal, band_low, band_high}`` without monotonicity assert.

    ``band_low`` / ``band_high`` are min/max across the three corner values.
    Intended for per-region mean/max temperatures, where mixed
    resistance/conductance corners can legitimately invert ordering even when
    the global hotspot remains monotonic.
    """
    vals = (float(cold), float(nominal), float(hot))
    return {
        "nominal": float(nominal),
        "band_low": min(vals),
        "band_high": max(vals),
    }


# Regions that may use fallback_k under a literature solve without claiming
# a literature-cited conductivity. Air / magnet / shaft are mapped above —
# only residual kinds (e.g. Housing before a housing-k slot lands) remain.
# Any use is stamped into literature_meta.fallback_regions.
LITERATURE_FALLBACK_REGION_KINDS: frozenset[str] = frozenset(
    {
        "Housing",
    }
)


# Laminated EM grades that share the cited M19-centric in-plane stack band.
_LAMINATED_ROTOR_GRADES: frozenset[str] = frozenset(
    {"M19", "M27", "M36", "NO20", "NO27"}
)
# Solid rotor steel: use the cited AISI 1018 shaft conductivity slot.
_SOLID_ROTOR_STEEL_GRADES: frozenset[str] = frozenset({"1018_steel"})


def _conductivity_slot_for_region(
    region_kind: str,
    *,
    rotor_steel: str | None = None,
    stator_steel: str | None = None,
) -> str | None:
    """Resolve literature slot from region kind + MotorConfig steel grades.

    ``RotorCore`` with ``rotor_steel=1018_steel`` maps to ``shaft_k`` (solid
    steel), not the lamination stack band. Unsupported configured grades
    raise rather than silently using a generic lamination range.
    """
    kind_s = str(region_kind)
    if kind_s == "RotorCore" and rotor_steel is not None:
        grade = str(rotor_steel)
        if grade in _SOLID_ROTOR_STEEL_GRADES:
            return "shaft_k"
        if grade in _LAMINATED_ROTOR_GRADES:
            return "lamination_stack_k_in_plane"
        raise MaterialRangeError(
            f"unsupported rotor_steel={grade!r} for RotorCore literature "
            f"conductivity; cite a slot or mark PENDING_SOURCE"
        )
    if kind_s in {"StatorTooth", "StatorYoke"} and stator_steel is not None:
        grade = str(stator_steel)
        if grade not in _LAMINATED_ROTOR_GRADES:
            raise MaterialRangeError(
                f"unsupported stator_steel={grade!r} for {kind_s} literature "
                f"conductivity; cite a slot or mark PENDING_SOURCE"
            )
    return REGION_CONDUCTIVITY_SLOT.get(kind_s)


def materials_from_literature_corner(
    region_kinds: list[str],
    library: Mapping[str, Any],
    corner: CornerName = "nominal",
    *,
    fallback_k_w_per_m_k: float | None = None,
    require_mapped_slots_extracted: bool = True,
    rotor_steel: str | None = None,
    stator_steel: str | None = None,
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    """Build per-triangle isotropic ``k_w_per_m_k`` materials for a corner.

    Mapped regions use the corresponding EXTRACTED conductivity slot.
    When ``rotor_steel`` / ``stator_steel`` are provided (from MotorConfig),
    ``RotorCore`` / stator steel regions resolve via the configured grade
    rather than region kind alone.

    Unmapped regions in :data:`LITERATURE_FALLBACK_REGION_KINDS` may use
    ``fallback_k_w_per_m_k``; other unmapped kinds raise. Fallback usage is
    recorded in the returned meta so payloads cannot silently claim
    literature provenance for steel-like air/magnet k.

    Returns ``(materials, meta)`` where ``meta`` includes
    ``fallback_regions`` / ``fallback_k_w_per_m_k`` when any triangle used
    the fallback.
    """
    if not region_kinds:
        raise MaterialRangeError("region_kinds empty")
    params = resolve_corner_parameters(library, corner)
    materials: list[dict[str, float]] = []
    pending_needed: set[str] = set()
    fallback_regions: dict[str, int] = {}
    mapped_slot_ids: set[str] = set()
    grade_overrides: dict[str, str] = {}

    for kind in region_kinds:
        kind_s = str(kind)
        slot_id = _conductivity_slot_for_region(
            kind_s, rotor_steel=rotor_steel, stator_steel=stator_steel
        )
        if kind_s == "RotorCore" and rotor_steel is not None and slot_id is not None:
            grade_overrides[kind_s] = f"{rotor_steel}->{slot_id}"
        if slot_id is None:
            if kind_s not in LITERATURE_FALLBACK_REGION_KINDS:
                raise MaterialRangeError(
                    f"no literature conductivity mapping for region {kind_s!r}; "
                    f"add a REGION_CONDUCTIVITY_SLOT entry or allowlist it in "
                    f"LITERATURE_FALLBACK_REGION_KINDS"
                )
            if fallback_k_w_per_m_k is None:
                raise MaterialRangeError(
                    f"region {kind_s!r} requires fallback_k_w_per_m_k "
                    f"(not a literature-mapped conductivity slot)"
                )
            materials.append({"k_w_per_m_k": float(fallback_k_w_per_m_k)})
            fallback_regions[kind_s] = fallback_regions.get(kind_s, 0) + 1
            continue
        mapped_slot_ids.add(slot_id)
        value = params.get(slot_id)
        if value is None:
            pending_needed.add(slot_id)
            if require_mapped_slots_extracted:
                continue
            if fallback_k_w_per_m_k is None:
                raise MaterialRangeError(
                    f"slot {slot_id!r} PENDING_SOURCE and no fallback"
                )
            materials.append({"k_w_per_m_k": float(fallback_k_w_per_m_k)})
            fallback_regions[kind_s] = fallback_regions.get(kind_s, 0) + 1
            continue
        materials.append({"k_w_per_m_k": float(value)})

    if require_mapped_slots_extracted and pending_needed:
        raise MaterialRangeError(
            "literature materials requested but slots still PENDING_SOURCE: "
            f"{sorted(pending_needed)}. Cite sources in "
            f"qa/s49_01_thermal_material_ranges/ before enabling "
            f"use_literature_materials (corner={corner!r})."
        )
    meta: dict[str, Any] = {
        "mapped_slot_ids": sorted(mapped_slot_ids),
    }
    if grade_overrides:
        meta["grade_slot_overrides"] = dict(sorted(grade_overrides.items()))
        if rotor_steel is not None:
            meta["rotor_steel"] = str(rotor_steel)
        if stator_steel is not None:
            meta["stator_steel"] = str(stator_steel)
    if fallback_regions:
        meta["fallback_regions"] = dict(sorted(fallback_regions.items()))
        meta["fallback_k_w_per_m_k"] = float(fallback_k_w_per_m_k)  # type: ignore[arg-type]
        meta["fallback_note"] = (
            "Unmapped allowlisted regions used fallback_k_w_per_m_k; "
            "these values are NOT literature-cited conductivities."
        )
    return materials, meta


def literature_k_by_region_kind(
    region_kinds: Iterable[str],
    library: Mapping[str, Any] | None = None,
    corner: CornerName = "nominal",
    *,
    fallback_k_w_per_m_k: float | None = 40.0,
    require_mapped_slots_extracted: bool = True,
) -> tuple[dict[str, float], dict[str, Any]]:
    """One isotropic k per unique region kind (FEMM named-material path).

    Resolves :data:`REGION_CONDUCTIVITY_SLOT` at ``corner`` via
    :func:`materials_from_literature_corner`. Used by the FEMM heat-flow
    motor drawers so dual-lane parity compares the same materials physics
    as the native literature path (S49-01c).
    """
    kinds = [str(k) for k in region_kinds]
    if not kinds:
        raise MaterialRangeError("region_kinds empty")
    # Preserve first-seen order while deduping.
    unique: list[str] = list(dict.fromkeys(kinds))
    lib = library if library is not None else load_material_range_library()
    materials, meta = materials_from_literature_corner(
        unique,
        lib,
        corner,
        fallback_k_w_per_m_k=fallback_k_w_per_m_k,
        require_mapped_slots_extracted=require_mapped_slots_extracted,
    )
    if len(materials) != len(unique):
        raise MaterialRangeError(
            f"literature_k_by_region_kind length mismatch: "
            f"{len(materials)} materials for {len(unique)} kinds"
        )
    k_by_kind = {
        kind: float(mat["k_w_per_m_k"])
        for kind, mat in zip(unique, materials)
    }
    out_meta = {
        "corner": corner,
        "library_status": lib.get("status"),
        "openem_convention_tag": PROVENANCE_TAG,
        **meta,
        "k_by_kind": dict(k_by_kind),
    }
    return k_by_kind, out_meta
