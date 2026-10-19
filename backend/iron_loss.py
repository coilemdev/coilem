"""Stator iron loss from per-position field frames, with cited M350-50A coefficients.

Model (per kilogram, peak flux density B_h of each electrical harmonic h):

  p = sum_h ( kh · f_h · B_h^alpha  +  kc · f_h^2 · B_h^2 )

The coefficients come from public facts only, no fitted loss table:
  * kc is the classical eddy-current term of a lamination,
    pi^2 · d^2 / (6 · rho_el · rho_m).
  * kh and alpha follow from the two EN 10106 maxima at 50 Hz (P1.0 and P1.5),
    once the eddy term is subtracted. The model therefore reproduces the
    grade's guaranteed loss limits exactly at 50 Hz and reads high against
    typical sheet.

Excess loss is not modelled separately. Against a published M400-50A loss
table built the same way, the model was within a mean of ±8 % from 50 Hz to
1 kHz (worst point about 22 %), and about +24 % at 2.5 kHz. Results report the
share of loss that comes from harmonics above 1 kHz or flux densities above
1.5 T, the range the two grade limits do not cover.

Field frames are per-angle Gmsh meshes. The stator triangulation is the same at
every directly meshed angle, so those frames map element by element. Positions
derived by slot-pitch congruence are rotated copies whose stator mesh does not
coincide, so the reference element centroids are located in each distinct
mesh once.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

STATOR_IRON_REGIONS = ("stator_tooth", "stator_yoke")
# The grade limits fix the model at 50 Hz between 1.0 T and 1.5 T; the
# frequency range is where the method was checked against measured sheet.
VALIDATED_MAX_FREQUENCY_HZ = 1000.0
VALIDATED_MAX_FLUX_DENSITY_T = 1.5
_LOCATE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class SteinmetzCoefficients:
    """Specific-loss coefficients in W/kg for f in Hz and peak B in tesla."""

    kh: float
    alpha: float
    kc: float
    density_kg_m3: float

    def specific_loss_w_per_kg(self, frequency_hz: float, flux_density_t: float) -> float:
        return (
            self.kh * frequency_hz * flux_density_t**self.alpha
            + self.kc * frequency_hz**2 * flux_density_t**2
        )


def grade_limit_coefficients(
    *,
    p10_w_per_kg: float,
    p15_w_per_kg: float,
    thickness_m: float,
    resistivity_ohm_m: float,
    density_kg_m3: float,
) -> SteinmetzCoefficients:
    """Coefficients that meet a grade's 50 Hz loss limits at 1.0 T and 1.5 T."""

    kc = math.pi**2 * thickness_m**2 / (6.0 * resistivity_ohm_m * density_kg_m3)
    hysteresis_10 = p10_w_per_kg - kc * 50.0**2
    hysteresis_15 = p15_w_per_kg - kc * 50.0**2 * 1.5**2
    if hysteresis_10 <= 0 or hysteresis_15 <= hysteresis_10:
        raise ValueError("grade limits leave no positive, increasing hysteresis loss")
    kh = hysteresis_10 / 50.0
    alpha = math.log(hysteresis_15 / hysteresis_10) / math.log(1.5)
    return SteinmetzCoefficients(kh=kh, alpha=alpha, kc=kc, density_kg_m3=density_kg_m3)


# M350-50A: EN 10106 maxima P1.0 = 1.50 W/kg and P1.5 = 3.50 W/kg at 50 Hz, 0.50 mm
# nominal thickness and the 7650 kg/m3 conventional density coilEM already uses for
# this grade. Resistivity 42.2e-8 Ohm m is the typical value in SIJ Acroni's
# SIWATT M350-50A technical data sheet (SIWATT M350-50A-1/1-2023-EN).
M350_50A_LOSS = grade_limit_coefficients(
    p10_w_per_kg=1.50,
    p15_w_per_kg=3.50,
    thickness_m=0.50e-3,
    resistivity_ohm_m=42.2e-8,
    density_kg_m3=7650.0,
)


@dataclass(frozen=True)
class FieldFrame:
    """One rotor position's mesh and element flux density."""

    nodes_mm: np.ndarray  # (nodes, 2)
    triangles: np.ndarray  # (elements, 3)
    regions: Sequence[str]
    bx_t: np.ndarray  # (elements,)
    by_t: np.ndarray  # (elements,)

    @classmethod
    def from_payload(cls, payload: dict) -> FieldFrame:
        return cls(
            nodes_mm=np.asarray(payload["nodes_mm"], dtype=float),
            triangles=np.asarray(payload["triangles"], dtype=int),
            regions=list(payload["regions"]),
            bx_t=np.asarray(payload["element_bx_t"], dtype=float),
            by_t=np.asarray(payload["element_by_t"], dtype=float),
        )


@dataclass(frozen=True)
class StatorFluxHistory:
    """Flux density of each reference stator element at each rotor position."""

    bx_t: np.ndarray  # (positions, elements)
    by_t: np.ndarray  # (positions, elements)
    area_m2: np.ndarray  # (elements,)
    distinct_meshes: int


@dataclass(frozen=True)
class IronLossEstimate:
    hysteresis_w: float
    eddy_w: float
    stator_iron_mass_kg: float
    share_above_validated_frequency: float
    share_above_validated_flux_density: float

    @property
    def total_w(self) -> float:
        return self.hysteresis_w + self.eddy_w


def stator_flux_history(frames: Sequence[FieldFrame]) -> StatorFluxHistory:
    """Collect stator element fields over positions on the first frame's elements."""

    if len(frames) < 2:
        raise ValueError("iron loss needs at least two rotor positions")
    reference = frames[0]
    ref_index = _stator_elements(reference)
    if ref_index.size == 0:
        raise ValueError("the reference frame has no stator iron elements")
    ref_corners = reference.nodes_mm[reference.triangles[ref_index]]
    ref_keys = _triangle_keys(ref_corners)
    centroids = ref_corners.mean(axis=1)

    bx = np.empty((len(frames), ref_index.size))
    by = np.empty((len(frames), ref_index.size))
    mappings: dict[bytes, np.ndarray] = {}
    for position, frame in enumerate(frames):
        index = _stator_elements(frame)
        corners = frame.nodes_mm[frame.triangles[index]]
        signature = np.round(corners, 3).tobytes()
        mapping = mappings.get(signature)
        if mapping is None:
            mapping = _map_reference_elements(ref_keys, centroids, index, corners)
            mappings[signature] = mapping
        bx[position] = frame.bx_t[mapping]
        by[position] = frame.by_t[mapping]

    area_m2 = 0.5 * np.abs(
        (ref_corners[:, 1, 0] - ref_corners[:, 0, 0]) * (ref_corners[:, 2, 1] - ref_corners[:, 0, 1])
        - (ref_corners[:, 2, 0] - ref_corners[:, 0, 0]) * (ref_corners[:, 1, 1] - ref_corners[:, 0, 1])
    ) * 1e-6
    return StatorFluxHistory(bx_t=bx, by_t=by, area_m2=area_m2, distinct_meshes=len(mappings))


def harmonic_iron_loss(
    history: StatorFluxHistory,
    *,
    electrical_frequency_hz: float,
    stack_length_m: float,
    machine_scale: float,
    coefficients: SteinmetzCoefficients = M350_50A_LOSS,
) -> IronLossEstimate:
    """Harmonic Steinmetz loss over one electrical period sampled uniformly.

    ``machine_scale`` converts the meshed sector to the whole machine
    (pole count / meshed pole pitches). The Nyquist bin is left out: a
    uniformly sampled waveform cannot resolve its amplitude.
    """

    positions = history.bx_t.shape[0]
    if positions < 2:
        raise ValueError("iron loss needs at least two rotor positions")
    if electrical_frequency_hz <= 0 or stack_length_m <= 0 or machine_scale <= 0:
        raise ValueError("frequency, stack length and machine scale must be positive")
    spectrum_x = np.fft.rfft(history.bx_t, axis=0)
    spectrum_y = np.fft.rfft(history.by_t, axis=0)
    orders = np.arange(spectrum_x.shape[0])
    resolved = (orders >= 1) & (2 * orders < positions)
    amplitude = (2.0 / positions) * np.sqrt(np.abs(spectrum_x[resolved]) ** 2 + np.abs(spectrum_y[resolved]) ** 2)
    frequency = electrical_frequency_hz * orders[resolved][:, None]

    mass_kg = history.area_m2 * stack_length_m * coefficients.density_kg_m3 * machine_scale
    hysteresis = coefficients.kh * frequency * amplitude**coefficients.alpha * mass_kg
    eddy = coefficients.kc * frequency**2 * amplitude**2 * mass_kg
    loss = hysteresis + eddy
    total = float(loss.sum())
    above_frequency = float(loss[frequency[:, 0] > VALIDATED_MAX_FREQUENCY_HZ].sum())
    above_flux_density = float(loss[amplitude > VALIDATED_MAX_FLUX_DENSITY_T].sum())
    return IronLossEstimate(
        hysteresis_w=float(hysteresis.sum()),
        eddy_w=float(eddy.sum()),
        stator_iron_mass_kg=float(mass_kg.sum()),
        share_above_validated_frequency=above_frequency / total if total > 0 else 0.0,
        share_above_validated_flux_density=above_flux_density / total if total > 0 else 0.0,
    )


def _stator_elements(frame: FieldFrame) -> np.ndarray:
    return np.nonzero(np.isin(np.asarray(frame.regions), STATOR_IRON_REGIONS))[0]


def _triangle_keys(corners: np.ndarray) -> list[bytes]:
    rounded = np.round(corners, 4)
    order = np.lexsort((rounded[:, :, 1], rounded[:, :, 0]), axis=1)
    rounded = np.take_along_axis(rounded, order[:, :, None], axis=1)
    return [triangle.tobytes() for triangle in rounded]


def _map_reference_elements(
    ref_keys: list[bytes],
    centroids: np.ndarray,
    index: np.ndarray,
    corners: np.ndarray,
) -> np.ndarray:
    by_key = dict(zip(_triangle_keys(corners), index))
    direct = [by_key.get(key, -1) for key in ref_keys]
    if all(element >= 0 for element in direct):
        return np.asarray(direct, dtype=int)
    local = _locate(centroids, corners)
    if np.any(local < 0):
        missing = int(np.sum(local < 0))
        raise ValueError(f"{missing} stator elements fall outside a rotated position's stator mesh")
    return index[local]


def _locate(points: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Index of the triangle containing each point, using a uniform bucket grid."""

    low, high = corners.min(axis=1), corners.max(axis=1)
    origin = low.min(axis=0)
    cell = max(float(np.median(high - low)) * 2.0, 1e-6)
    first = np.floor((low - origin) / cell).astype(int)
    last = np.floor((high - origin) / cell).astype(int)
    buckets: dict[tuple[int, int], list[int]] = {}
    for triangle, (x0, y0), (x1, y1) in zip(range(len(corners)), first, last):
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                buckets.setdefault((gx, gy), []).append(triangle)

    a, b, c = corners[:, 0], corners[:, 1], corners[:, 2]
    det = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
    found = np.full(len(points), -1, dtype=int)
    cells = np.floor((points - origin) / cell).astype(int)
    for point_index, (point, (gx, gy)) in enumerate(zip(points, cells)):
        candidates = buckets.get((gx, gy))
        if not candidates:
            continue
        cand = np.asarray(candidates)
        dx, dy = point[0] - a[cand, 0], point[1] - a[cand, 1]
        u = ((c[cand, 1] - a[cand, 1]) * dx - (c[cand, 0] - a[cand, 0]) * dy) / det[cand]
        v = ((b[cand, 0] - a[cand, 0]) * dy - (b[cand, 1] - a[cand, 1]) * dx) / det[cand]
        inside = np.nonzero((u >= -_LOCATE_TOLERANCE) & (v >= -_LOCATE_TOLERANCE) & (u + v <= 1 + _LOCATE_TOLERANCE))[0]
        if inside.size:
            found[point_index] = cand[inside[0]]
    return found
