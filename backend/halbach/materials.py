"""Permanent-magnet resolution and coercivity audit for Halbach reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.material_catalog import MAGNET_PROPERTIES

from .models import (
    CATALOG_TEMPERATURE_RANGES_C,
    CatalogMagnetInput,
    CustomMagnetInput,
    MagnetInput,
)

CATALOG_REVISION = "openem-magnet-catalog-2026-07-30"
CATALOG_PROVENANCE = "backend.material_catalog.MAGNET_PROPERTIES"
REFERENCE_TEMPERATURE_C = 20.0


def _catalog_float(row: dict[str, object], field: str) -> float:
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"catalog field {field!r} must be numeric")
    return float(value)


# Independent Br and coercivity coefficient rows.  These rows preserve the
# source semantics already documented by the motor temperature adapter without
# importing the thermal application into the public Halbach boundary.
_TEMPERATURE_ROWS: dict[str, dict[str, Any]] = {
    "N35": {"alpha_br_per_k": -0.0012, "alpha_hcj_per_k": -0.0055},
    "N42": {"alpha_br_per_k": -0.0012, "alpha_hcj_per_k": -0.0055},
    "N48": {"alpha_br_per_k": -0.0012, "alpha_hcj_per_k": -0.0055},
    "N52": {"alpha_br_per_k": -0.0012, "alpha_hcj_per_k": -0.0055},
    "N48SH": {"alpha_br_per_k": -0.0011, "alpha_hcj_per_k": -0.0050},
    "Prius_2004_NdFeB": {
        "alpha_br_per_k": -0.0012,
        "alpha_hcj_per_k": -0.0055,
    },
    "Ferrite_Y30": {
        "alpha_br_per_k": -0.0020,
        "alpha_hcj_per_k": 0.0040,
    },
}


@dataclass(frozen=True)
class CoercivityAudit:
    grade: str
    classification: Literal["intrinsic", "normal", "unknown"]
    source_field: str
    original_value: float
    original_unit: str
    normalized_a_per_m: float
    reference_temperature_c: float
    catalog_revision: str
    provenance: str
    eligible_for_margin: bool
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade,
            "classification": self.classification,
            "source_field": self.source_field,
            "original_value": self.original_value,
            "original_unit": self.original_unit,
            "normalized_a_per_m": self.normalized_a_per_m,
            "reference_temperature_c": self.reference_temperature_c,
            "catalog_revision": self.catalog_revision,
            "provenance": self.provenance,
            "eligible_for_margin": self.eligible_for_margin,
            "note": self.note,
        }


def _build_catalog_audit() -> dict[str, CoercivityAudit]:
    audits: dict[str, CoercivityAudit] = {}
    for grade, row in MAGNET_PROPERTIES.items():
        raw = abs(_catalog_float(row, "coercivity_bH_kA_m"))
        audits[grade] = CoercivityAudit(
            grade=grade,
            classification="unknown",
            source_field="coercivity_bH_kA_m",
            original_value=raw,
            original_unit="kA/m",
            normalized_a_per_m=raw * 1000.0,
            reference_temperature_c=REFERENCE_TEMPERATURE_C,
            catalog_revision=CATALOG_REVISION,
            provenance=CATALOG_PROVENANCE,
            eligible_for_margin=False,
            note=(
                "The legacy catalog row does not cite a supplier revision or "
                "identify the value unambiguously as H_cj versus H_cb. It is "
                "retained as metadata and cannot drive a screening margin."
            ),
        )
    return audits


CATALOG_COERCIVITY_AUDIT = _build_catalog_audit()


@dataclass(frozen=True)
class ResolvedMagnetMaterial:
    name: str
    source: Literal["catalog", "custom"]
    remanence_t: float
    relative_permeability: float
    density_kg_per_m3: float | None
    coercivity_a_per_m: float | None
    coercivity_classification: Literal["intrinsic", "normal", "unknown", "missing"]
    coercivity_margin_eligible: bool
    coercivity_ineligible_reason: str | None
    temperature_c: float
    catalog_revision: str | None
    provenance: dict[str, Any]
    br_temperature: dict[str, Any]
    hcj_temperature: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "remanence_t": self.remanence_t,
            "relative_permeability": self.relative_permeability,
            "density_kg_per_m3": self.density_kg_per_m3,
            "coercivity_a_per_m": self.coercivity_a_per_m,
            "coercivity_classification": self.coercivity_classification,
            "coercivity_margin_eligible": self.coercivity_margin_eligible,
            "coercivity_ineligible_reason": self.coercivity_ineligible_reason,
            "temperature_c": self.temperature_c,
            "catalog_revision": self.catalog_revision,
            "provenance": self.provenance,
            "br_temperature": self.br_temperature,
            "hcj_temperature": self.hcj_temperature,
        }


def _temperature_value(
    *,
    input_value: float | None,
    coefficient: float | None,
    reference_temperature_c: float | None,
    temperature_c: float | None,
) -> tuple[float | None, dict[str, Any]]:
    resolved = input_value
    delta_c = None
    scale = None
    applied = False
    if (
        input_value is not None
        and coefficient is not None
        and reference_temperature_c is not None
        and temperature_c is not None
    ):
        delta_c = temperature_c - reference_temperature_c
        scale = 1.0 + coefficient * delta_c
        if scale <= 0.0:
            raise ValueError("magnet temperature coefficient produces a non-positive scale")
        resolved = input_value * scale
        applied = True
    return resolved, {
        "input_value": input_value,
        "coefficient_per_k": coefficient,
        "reference_temperature_c": reference_temperature_c,
        "temperature_c": temperature_c,
        "delta_c": delta_c,
        "scale": scale,
        "resolved_value": resolved,
        "derating_applied": applied,
    }


def _resolve_catalog(magnet: CatalogMagnetInput) -> ResolvedMagnetMaterial:
    row = MAGNET_PROPERTIES[magnet.grade]
    audit = CATALOG_COERCIVITY_AUDIT[magnet.grade]
    coefficients = _TEMPERATURE_ROWS[magnet.grade]
    t_min, t_max = CATALOG_TEMPERATURE_RANGES_C[magnet.grade]
    assert t_min <= magnet.temperature_c <= t_max
    br, br_record = _temperature_value(
        input_value=_catalog_float(row, "remanence_T"),
        coefficient=float(coefficients["alpha_br_per_k"]),
        reference_temperature_c=REFERENCE_TEMPERATURE_C,
        temperature_c=magnet.temperature_c,
    )
    coercivity, hcj_record = _temperature_value(
        input_value=audit.normalized_a_per_m,
        coefficient=float(coefficients["alpha_hcj_per_k"]),
        reference_temperature_c=REFERENCE_TEMPERATURE_C,
        temperature_c=magnet.temperature_c,
    )
    assert br is not None
    return ResolvedMagnetMaterial(
        name=str(row["name"]),
        source="catalog",
        remanence_t=br,
        relative_permeability=_catalog_float(row, "relative_permeability"),
        density_kg_per_m3=_catalog_float(row, "density_kg_m3"),
        coercivity_a_per_m=coercivity,
        coercivity_classification=audit.classification,
        coercivity_margin_eligible=audit.eligible_for_margin,
        coercivity_ineligible_reason=(
            None
            if audit.eligible_for_margin
            else "catalog_coercivity_not_audited_as_intrinsic"
        ),
        temperature_c=magnet.temperature_c,
        catalog_revision=CATALOG_REVISION,
        provenance={"catalog": CATALOG_PROVENANCE, "coercivity_audit": audit.as_dict()},
        br_temperature={**br_record, "quantity": "B_r", "unit": "T"},
        hcj_temperature={**hcj_record, "quantity": "H_cj_candidate", "unit": "A/m"},
    )


def _resolve_custom(magnet: CustomMagnetInput) -> ResolvedMagnetMaterial:
    temperature_c = (
        magnet.temperature_c
        if magnet.temperature_c is not None
        else magnet.reference_temperature_c
        if magnet.reference_temperature_c is not None
        else REFERENCE_TEMPERATURE_C
    )
    br, br_record = _temperature_value(
        input_value=magnet.remanence_t,
        coefficient=magnet.alpha_br_per_k,
        reference_temperature_c=magnet.reference_temperature_c,
        temperature_c=magnet.temperature_c,
    )
    coercivity, hcj_record = _temperature_value(
        input_value=magnet.intrinsic_coercivity_a_per_m,
        coefficient=magnet.alpha_hcj_per_k,
        reference_temperature_c=magnet.reference_temperature_c,
        temperature_c=magnet.temperature_c,
    )
    assert br is not None
    eligible = coercivity is not None
    return ResolvedMagnetMaterial(
        name=magnet.name,
        source="custom",
        remanence_t=br,
        relative_permeability=magnet.relative_permeability,
        density_kg_per_m3=magnet.density_kg_per_m3,
        coercivity_a_per_m=coercivity,
        coercivity_classification="intrinsic" if eligible else "missing",
        coercivity_margin_eligible=eligible,
        coercivity_ineligible_reason=None if eligible else "custom_material_missing_intrinsic_coercivity",
        temperature_c=temperature_c,
        catalog_revision=None,
        provenance={
            "source_note": magnet.source_note,
            "coercivity_audit": {
                "classification": "intrinsic" if eligible else "missing",
                "eligible_for_margin": eligible,
                "basis": (
                    "explicit custom intrinsic_coercivity_a_per_m input"
                    if eligible
                    else "no custom coercivity supplied"
                ),
            },
        },
        br_temperature={**br_record, "quantity": "B_r", "unit": "T"},
        hcj_temperature={**hcj_record, "quantity": "H_cj", "unit": "A/m"},
    )


def resolve_magnet_material(magnet: MagnetInput) -> ResolvedMagnetMaterial:
    if isinstance(magnet, CatalogMagnetInput):
        return _resolve_catalog(magnet)
    return _resolve_custom(magnet)
