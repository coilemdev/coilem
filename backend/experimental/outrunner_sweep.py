"""Explicit cases and periodic waveform analysis for the local LRK experiment."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

POLE_PAIRS = 7
PERIOD_DEG = 360 / POLE_PAIRS
SLIDING_SOURCE_SHA256 = "62dc72be4e4de0161dc1538bd35f921480a5169647238f8b4057ec88762105ee"


@dataclass(frozen=True)
class SweepCase:
    id: str
    angle_ccw_deg: float
    currents_A: tuple[float, float, float]
    family: str
    reference_model: str = "sliding"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", self.id):
            raise ValueError("Case ID must be a safe unique filename")
        if not math.isfinite(self.angle_ccw_deg):
            raise ValueError("Finite mechanical angle required")
        if len(self.currents_A) != 3 or not all(math.isfinite(x) for x in self.currents_A) or abs(sum(self.currents_A)) > 1e-10:
            raise ValueError("Three finite balanced phase currents required")
        if self.reference_model not in ("full", "sliding"):
            raise ValueError("Unknown reference model")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SweepCase:
        return cls(**{**raw, "currents_A": tuple(raw["currents_A"])})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def initial_cases(samples: int = 48) -> list[SweepCase]:
    if samples < 24 or samples % 24:
        raise ValueError("Use a multiple of 24 unique samples, at least 24")
    cases = []
    for index, angle in enumerate((-1/7, 0, 1/7, 5, 20, 40)):
        for model in ("full", "sliding"):
            cases.append(SweepCase(f"orientation_{index}_{model}", angle, (0, 4, -4), "orientation", model))
    for index, current in enumerate((-6, -2, 0, 2, 6)):
        cases.append(SweepCase(f"current_{index}", 0, (0, current, -current), "current", "full"))
    for family, currents in (("loaded", (0, 4, -4)), ("noload", (0, 0, 0))):
        for i in range(samples+1):
            cases.append(SweepCase(f"{family}_{i:04d}", PERIOD_DEG*i/samples, currents, family))
    cases.append(SweepCase("mechanical_closure", 360, (0, 0, 0), "mechanical_closure", "full"))
    return cases


def periodic_derivative(values: np.ndarray, period_rad: float, method: str = "spectral") -> np.ndarray:
    """Derivative on a uniform periodic grid excluding the repeated endpoint.

    Spectral uses every resolved Fourier mode (no smoothing or phase fitting).
    The even-grid Nyquist derivative is zero at the original sample positions.
    """
    data = np.asarray(values, dtype=float)
    if data.ndim not in (1, 2) or len(data) < 8 or not np.isfinite(data).all() or not math.isfinite(period_rad) or period_rad <= 0:
        raise ValueError("Expected finite periodic data and positive period")
    step = period_rad/len(data)
    if method == "central4":
        return (np.roll(data, 2, axis=0)-8*np.roll(data, 1, axis=0)+8*np.roll(data, -1, axis=0)-np.roll(data, -2, axis=0))/(12*step)
    if method != "spectral":
        raise ValueError("Unknown derivative method")
    frequency = 2*math.pi*np.fft.fftfreq(len(data), d=step)
    if len(data) % 2 == 0:
        frequency[len(data)//2] = 0
    multiplier = 1j*frequency if data.ndim == 1 else 1j*frequency[:, None]
    return np.fft.ifft(multiplier*np.fft.fft(data, axis=0), axis=0).real


def bemf(values: np.ndarray, rpm: float = 1000, method: str = "spectral") -> np.ndarray:
    """Induced EMF e=-d(lambda)/dt along the ordered rotation coordinate.

    Values are phase flux linkages over one electrical period, with no repeated
    endpoint. The derivative is with respect to MECHANICAL radians. Original
    comparison samples advance CCW; running-mode samples advance clockwise.
    """
    if not math.isfinite(rpm) or rpm <= 0:
        raise ValueError("Positive normalization speed required")
    return -rpm*2*math.pi/60*periodic_derivative(values, 2*math.pi/POLE_PAIRS, method)


def fundamental(values: np.ndarray) -> dict[str, Any]:
    data = np.asarray(values)
    coefficient = 2*np.fft.rfft(data, axis=0)[1]/len(data)
    return {"peak": np.abs(coefficient).tolist(), "cosine_phase_deg": np.degrees(np.angle(coefficient)).tolist()}
