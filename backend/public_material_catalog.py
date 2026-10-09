"""Public material metadata used by the local solver and Design workspace.

The catalog distinguishes a human-facing material key from the immutable
numerical model that the UI visualizes. Model hashes cover solver inputs, not
display copy, so a wording change cannot masquerade as a physics change.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

from pydantic import BaseModel, Field

from backend.material_contract import (
    ElectricalSteelCurveError,
    load_electrical_steel_curve,
)

PUBLIC_MATERIAL_MODEL_REVISION = "2026.07.2"
MU_0 = 4.0e-7 * math.pi
PublicMaterialProperty = float | str | list[float]


class PublicMaterialCapabilities(BaseModel):
    material_curve: bool
    saturation_visualization: bool = False
    hysteresis_loop: bool = False
    demagnetization_assessment: bool = False
    temperature_dependence: bool = False
    core_loss: bool = False


class PublicMaterialCurve(BaseModel):
    x_quantity: Literal["field_strength"]
    x_unit: Literal["A/m"]
    x_scale: Literal["log1p", "linear"]
    y_quantity: Literal["flux_density"]
    y_unit: Literal["T"]
    points: list[tuple[float, float]]


class PublicMaterialSource(BaseModel):
    label: str
    url: str


ARNOLD_NDFEB_SOURCE = PublicMaterialSource(
    label="Arnold typical room-temperature NdFeB reference",
    url="https://www.arnoldmagnetics.com/products/neodymium-iron-boron-magnets/",
)


class PublicMaterialModel(BaseModel):
    id: str
    display_name: str
    kind: Literal["electrical_steel", "permanent_magnet", "conductor"]
    model_kind: Literal[
        "nonlinear_bh",
        "linear_recoil",
        "electromagnetic_region",
    ]
    model_revision: str
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    properties: dict[str, PublicMaterialProperty]
    capabilities: PublicMaterialCapabilities
    curve: PublicMaterialCurve | None = None
    limitations: list[str]
    source: PublicMaterialSource | None = None


class PublicMaterialCatalogResponse(BaseModel):
    steels: list[str]
    magnet_grades: list[str]
    conductors: list[str]
    models: dict[str, PublicMaterialModel]


MAGNET_SOLVER_INPUTS: dict[
    str,
    tuple[str, float, float, PublicMaterialSource | None],
] = {
    "N35": ("NdFeB N35", 1.23, 1.05, ARNOLD_NDFEB_SOURCE),
    "N42": ("NdFeB N42", 1.315, 1.05, ARNOLD_NDFEB_SOURCE),
    "N48": ("NdFeB N48", 1.400, 1.05, ARNOLD_NDFEB_SOURCE),
    "N52": ("NdFeB N52", 1.450, 1.05, ARNOLD_NDFEB_SOURCE),
    "N48SH": ("NdFeB N48SH", 1.390, 1.05, ARNOLD_NDFEB_SOURCE),
    # These solver presets have no checked-in source that supports the exact
    # values below. Omit provenance instead of presenting an unrelated NdFeB
    # vendor page as evidence for ferrite or the Prius-specific approximation.
    "Ferrite_Y30": ("Ferrite Y30", 0.40, 1.05, None),
    "Prius_2004_NdFeB": ("Prius 2004 NdFeB preset", 1.24, 1.05, None),
}

CONDUCTOR_KEYS = ("copper", "aluminum")


def _canonical_model_hash(
    model_kind: str,
    properties: dict[str, PublicMaterialProperty],
) -> str:
    payload = json.dumps(
        {"model_kind": model_kind, "properties": properties},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _steel_model() -> PublicMaterialModel:
    curve = load_electrical_steel_curve("M350-50A")
    if len(curve.points) < 2:
        raise ElectricalSteelCurveError(
            "M350-50A requires at least two B-H points for the public model"
        )
    first_nonzero_b, first_nonzero_h = curve.points[1]
    if not math.isfinite(first_nonzero_h) or abs(first_nonzero_h) <= 1e-12:
        raise ElectricalSteelCurveError(
            "M350-50A requires a finite, non-zero second H value"
        )
    initial_mu_r = first_nonzero_b / (MU_0 * first_nonzero_h)
    properties: dict[str, PublicMaterialProperty] = {
        "curve_sha256": curve.sha256,
        "initial_relative_permeability": round(initial_mu_r),
        "curve_min_T": curve.points[0][0],
        "curve_max_T": curve.points[-1][0],
        "curve_max_H_A_per_m": curve.points[-1][1],
        "saturation_knee_range_T": [1.4, 1.6],
        "reference_frequency_Hz": 50.0,
        "out_of_range_behavior": "linear H(B) extrapolation from the final two points",
        "hysteresis_model": "none",
        "loss_model": "generic harmonic Steinmetz estimate",
    }
    return PublicMaterialModel(
        id="M350-50A",
        display_name="M350-50A electrical steel",
        kind="electrical_steel",
        model_kind="nonlinear_bh",
        model_revision=PUBLIC_MATERIAL_MODEL_REVISION,
        model_hash=_canonical_model_hash("nonlinear_bh", properties),
        properties=properties,
        capabilities=PublicMaterialCapabilities(
            material_curve=True,
            saturation_visualization=True,
            core_loss=True,
        ),
        curve=PublicMaterialCurve(
            x_quantity="field_strength",
            x_unit="A/m",
            x_scale="log1p",
            y_quantity="flux_density",
            y_unit="T",
            points=[(h_a_per_m, b_t) for b_t, h_a_per_m in curve.points],
        ),
        limitations=[
            "Static single-valued magnetization law; remanence, coercivity, minor loops, and magnetic history are not modeled.",
            "Core loss is a separate generic harmonic Steinmetz estimate; supplier-specific loss and temperature data are not included.",
            "The source table ends at 2.50 T; the solver extrapolates H(B) from its final two points.",
        ],
        source=PublicMaterialSource(
            label="Modelica Standard Library M350-50A model",
            url=curve.spec.source_model_url,
        ),
    )


def _magnet_model(
    material_id: str,
    display_name: str,
    remanence_t: float,
    relative_permeability: float,
    source: PublicMaterialSource | None,
) -> PublicMaterialModel:
    properties: dict[str, PublicMaterialProperty] = {
        "remanence_T": remanence_t,
        "relative_permeability": relative_permeability,
    }
    implied_coercive_field = remanence_t / (MU_0 * relative_permeability)
    properties["implied_coercive_field_kA_per_m"] = implied_coercive_field / 1_000.0
    points = [
        (
            0.0
            if index == 40
            else -implied_coercive_field + implied_coercive_field * index / 40.0,
            remanence_t * index / 40.0,
        )
        for index in range(41)
    ]
    return PublicMaterialModel(
        id=material_id,
        display_name=display_name,
        kind="permanent_magnet",
        model_kind="linear_recoil",
        model_revision=PUBLIC_MATERIAL_MODEL_REVISION,
        model_hash=_canonical_model_hash("linear_recoil", properties),
        properties=properties,
        capabilities=PublicMaterialCapabilities(material_curve=True),
        curve=PublicMaterialCurve(
            x_quantity="field_strength",
            x_unit="A/m",
            x_scale="linear",
            y_quantity="flux_density",
            y_unit="T",
            points=points,
        ),
        limitations=[
            "Straight recoil-line approximation used by the current local solver.",
            "Demagnetization safety and temperature dependence are not evaluated.",
        ],
        source=source,
    )


def _conductor_model(material_id: str) -> PublicMaterialModel:
    properties: dict[str, PublicMaterialProperty] = {
        "relative_permeability": 1.0,
        "solver_role": "current-carrying region",
    }
    return PublicMaterialModel(
        id=material_id,
        display_name=f"{material_id.title()} conductor",
        kind="conductor",
        model_kind="electromagnetic_region",
        model_revision=PUBLIC_MATERIAL_MODEL_REVISION,
        model_hash=_canonical_model_hash("electromagnetic_region", properties),
        properties=properties,
        capabilities=PublicMaterialCapabilities(material_curve=False),
        limitations=[
            "The electromagnetic solve treats the winding region as approximately nonmagnetic.",
            "Resistive loss and thermal behavior are not evaluated in this material view.",
        ],
    )


def build_public_material_catalog() -> PublicMaterialCatalogResponse:
    """Return public material choices plus their exact visualized model inputs."""

    models: dict[str, PublicMaterialModel] = {}
    try:
        models["M350-50A"] = _steel_model()
    except ElectricalSteelCurveError:
        # Material choices remain usable if packaged curve bytes are missing or
        # corrupt. The UI already marks an absent model as unavailable, while
        # magnets and conductors can still explain their independent inputs.
        pass
    models.update(
        {
            material_id: _magnet_model(
                material_id,
                display_name,
                remanence_t,
                relative_permeability,
                source,
            )
            for material_id, (
                display_name,
                remanence_t,
                relative_permeability,
                source,
            ) in MAGNET_SOLVER_INPUTS.items()
        }
    )
    models.update(
        {material_id: _conductor_model(material_id) for material_id in CONDUCTOR_KEYS}
    )
    return PublicMaterialCatalogResponse(
        steels=["M350-50A"],
        magnet_grades=list(MAGNET_SOLVER_INPUTS),
        conductors=list(CONDUCTOR_KEYS),
        models=models,
    )
