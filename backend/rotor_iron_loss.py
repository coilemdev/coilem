"""Internal rotor-material sampling contract for #306; not wired into public results.

Angles are the actual, unwrapped, counterclockwise-positive geometry poses,
not the clockwise public electrical angles. Version 1 requires a full mechanical
turn. Material points and vector fields are both transformed into rotor axes.
The existing two-term harmonic approximation is reused without changing stator
results. It does not account for DC-bias/minor-loop or rotating-flux corrections.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Literal, Sequence

import numpy as np

from backend.iron_loss import FieldFrame, StatorFluxHistory, SteinmetzCoefficients, _locate, harmonic_iron_loss

METHOD = "rotor_material_harmonic/v1"


@dataclass(frozen=True)
class RotorSamplingPlan:
    """Uniform half-open full-turn grid; the closure solve is a separate check."""

    speed_rpm: float
    positions: int
    direction: int = -1
    start_mechanical_deg: float = 0.0

    def __post_init__(self):
        if not math.isfinite(self.speed_rpm) or self.speed_rpm <= 0:
            raise ValueError("rotor sampling needs a positive finite speed")
        if isinstance(self.positions, bool) or not isinstance(self.positions, int) or self.positions < 8:
            raise ValueError("rotor sampling needs at least eight positions")
        if isinstance(self.direction, bool) or self.direction not in (-1, 1):
            raise ValueError("direction must be -1 or +1 in native CCW geometry coordinates")
        if not math.isfinite(self.start_mechanical_deg):
            raise ValueError("the initial mechanical pose must be finite")

    @property
    def mechanical_angles_deg(self) -> tuple[float, ...]:
        return tuple(self.start_mechanical_deg + self.direction * 360.0 * k / self.positions for k in range(self.positions))

    @property
    def period_s(self) -> float:
        return 60.0 / self.speed_rpm

    @property
    def base_frequency_hz(self) -> float:
        return 1.0 / self.period_s

    def metadata(self) -> dict:
        return {
            "schema": "coilem.rotor_sampling/v1", **asdict(self),
            "angle_convention": "native_ccw_mechanical_unwrapped",
            "reference_frame": "rotor_material", "span_mechanical_deg": 360.0,
            "period_s": self.period_s, "base_frequency_Hz": self.base_frequency_hz,
            "endpoint_included": False, "half_wave_reconstruction": False,
        }


@dataclass(frozen=True)
class RotorFieldSample:
    """One pose's rotor-core triangles and B, already expressed in rotor axes."""

    mechanical_angle_deg: float
    corners_mm: np.ndarray
    bx_t: np.ndarray
    by_t: np.ndarray
    source_element_index: np.ndarray


@dataclass(frozen=True)
class RotorFluxHistory:
    plan: RotorSamplingPlan
    bx_t: np.ndarray
    by_t: np.ndarray
    area_m2: np.ndarray
    reference_element_index: np.ndarray
    distinct_meshes: int

    def __post_init__(self):
        shape = (self.plan.positions, len(self.area_m2))
        if not len(self.area_m2) or self.bx_t.shape != shape or self.by_t.shape != shape:
            raise ValueError("rotor history must contain every planned pose and reference element")
        if self.area_m2.ndim != 1 or len(self.reference_element_index) != shape[1]:
            raise ValueError("rotor history integration weights do not match its elements")
        if not all(np.isfinite(a).all() for a in (self.bx_t, self.by_t, self.area_m2)) or np.any(self.area_m2 <= 0):
            raise ValueError("rotor history needs finite fields and positive element areas")


@dataclass(frozen=True)
class RotorLossMaterial:
    steel_id: str
    coefficient_source: str
    coefficients: SteinmetzCoefficients
    stacking_factor: float = 1.0

    def __post_init__(self):
        c = self.coefficients
        if not self.steel_id.strip() or not self.coefficient_source.strip():
            raise ValueError("rotor loss needs a steel identity and coefficient source")
        if not all(math.isfinite(v) for v in (c.kh, c.kc, c.alpha, c.density_kg_m3, self.stacking_factor)):
            raise ValueError("rotor material parameters must be finite")
        if c.kh < 0 or c.kc < 0 or c.alpha <= 0 or c.density_kg_m3 <= 0 or not 0 < self.stacking_factor <= 1:
            raise ValueError("invalid rotor loss coefficients, density or stacking factor")


@dataclass(frozen=True)
class RotorIronLossEstimate:
    hysteresis_W: float
    lamination_eddy_W: float
    rotor_iron_mass_kg: float
    method: str = METHOD

    @property
    def total_W(self) -> float:
        return self.hysteresis_W + self.lamination_eddy_W


def _to_rotor(values: np.ndarray, angle_deg: float) -> np.ndarray:
    angle = math.radians(angle_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    # Row vectors multiplied by R(theta) implement R(-theta) on column vectors.
    return values @ np.array([[cosine, -sine], [sine, cosine]])


def sample_rotor_field(
    frame: FieldFrame, *, mechanical_angle_deg: float,
    coordinate_frame: Literal["global", "rotor_material"] = "global",
) -> RotorFieldSample:
    """Adapt an explicitly declared mesh/vector frame into rotor-material axes.

    Remeshed global exports rotate both geometry and B. Moving-air-gap FEMM
    exports already follow the rotor in its drawn axes, so both are retained.
    The actual signed mechanical pose is required in either representation.
    """

    if not math.isfinite(mechanical_angle_deg):
        raise ValueError("a signed native mechanical pose is required")
    if coordinate_frame not in ("global", "rotor_material"):
        raise ValueError("the mesh and B coordinate frame must be global or rotor_material")
    nodes, triangles = np.asarray(frame.nodes_mm), np.asarray(frame.triangles)
    if nodes.ndim != 2 or nodes.shape[1] != 2 or not np.isfinite(nodes).all():
        raise ValueError("invalid field nodes")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or not np.issubdtype(triangles.dtype, np.integer):
        raise ValueError("invalid field triangles")
    if np.any(triangles < 0) or np.any(triangles >= len(nodes)):
        raise ValueError("field triangle node index is out of bounds")
    count = len(triangles)
    if len(frame.regions) != count or np.shape(frame.bx_t) != (count,) or np.shape(frame.by_t) != (count,):
        raise ValueError("field regions and vectors must match the triangle list")
    # Shaft and generic 'steel' tags are deliberately not accepted as laminations.
    indices = np.array([i for i, tag in enumerate(frame.regions) if tag in ("rotor_core", "RotorCore")], dtype=int)
    if not len(indices):
        raise ValueError("the frame has no explicitly tagged rotor-core elements")
    field = np.column_stack([np.asarray(frame.bx_t)[indices], np.asarray(frame.by_t)[indices]])
    if not np.isfinite(field).all():
        raise ValueError("rotor field values must be finite")
    corners = nodes[triangles[indices]]
    vectors = field
    if coordinate_frame == "global":
        corners = _to_rotor(corners, mechanical_angle_deg)
        vectors = _to_rotor(vectors, mechanical_angle_deg)
    return RotorFieldSample(mechanical_angle_deg, corners, vectors[:, 0], vectors[:, 1], indices)


def _triangle_keys(corners: np.ndarray) -> list[bytes]:
    rounded = np.round(corners, 8)
    # Canonicalise signed zero after rotation and vertex order after remeshing.
    rounded[rounded == 0] = 0.0
    order = np.lexsort((rounded[:, :, 1], rounded[:, :, 0]), axis=1)
    return [t.tobytes() for t in np.take_along_axis(rounded, order[:, :, None], axis=1)]


def rotor_flux_history(plan: RotorSamplingPlan, samples: Sequence[RotorFieldSample]) -> RotorFluxHistory:
    """Track first-pose material centroids across reordered or remeshed rotors.

    Areas belong to the reference mesh. Missing material points fail closed;
    there is no nearest-neighbour extrapolation into pockets, magnets or air.
    """

    if len(samples) != plan.positions:
        raise ValueError("rotor samples do not cover the complete sampling plan")
    reference = samples[0]
    corners = reference.corners_mm
    keys = _triangle_keys(corners)
    points = corners.mean(axis=1)
    u, v = corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]
    areas = 0.5e-6 * np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
    bx, by = np.empty((plan.positions, len(corners))), np.empty((plan.positions, len(corners)))
    mappings: dict[bytes, np.ndarray] = {}
    for k, (sample, expected_angle) in enumerate(zip(samples, plan.mechanical_angles_deg)):
        if abs(sample.mechanical_angle_deg - expected_angle) > 1e-8:
            raise ValueError("rotor sample poses differ from the ordered, unwrapped plan")
        if sample.corners_mm.shape != (len(sample.bx_t), 3, 2) or np.shape(sample.by_t) != np.shape(sample.bx_t):
            raise ValueError("malformed rotor sample")
        if not all(np.isfinite(a).all() for a in (sample.corners_mm, sample.bx_t, sample.by_t)):
            raise ValueError("rotor samples must be finite")
        sample_keys = _triangle_keys(sample.corners_mm)
        signature = hashlib.sha256(b"".join(sample_keys)).digest()
        mapping = mappings.get(signature)
        if mapping is None:
            by_key = {key: i for i, key in enumerate(sample_keys)}
            mapping = np.array([by_key.get(key, -1) for key in keys])
            missing = mapping < 0
            if np.any(missing):
                mapping[missing] = _locate(points[missing], sample.corners_mm)
            if np.any(mapping < 0):
                raise ValueError(f"{int((mapping < 0).sum())} rotor material points fall outside rotor steel")
            mappings[signature] = mapping
        bx[k], by[k] = sample.bx_t[mapping], sample.by_t[mapping]
    return RotorFluxHistory(plan, bx, by, areas, reference.source_element_index.copy(), len(mappings))


def harmonic_rotor_iron_loss(
    history: RotorFluxHistory, *, material: RotorLossMaterial, stack_length_m: float,
) -> RotorIronLossEstimate:
    """Apply the unchanged harmonic kernel with the mechanical-history frequency.

    The StatorFluxHistory adapter is internal compatibility with the existing
    generic numerical kernel. No stator symmetry or electrical pole-pair factor
    is applied, and the full-turn contract uses a full-machine mesh.
    """

    if not math.isfinite(stack_length_m) or stack_length_m <= 0:
        raise ValueError("rotor loss needs a positive finite stack length")
    estimate = harmonic_iron_loss(
        StatorFluxHistory(history.bx_t, history.by_t, history.area_m2 * material.stacking_factor, history.distinct_meshes),
        electrical_frequency_hz=history.plan.base_frequency_hz,
        stack_length_m=stack_length_m, machine_scale=1.0, coefficients=material.coefficients,
    )
    return RotorIronLossEstimate(estimate.hysteresis_w, estimate.eddy_w, estimate.stator_iron_mass_kg)
