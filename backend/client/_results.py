"""Solve results with accessors for the headline numbers and the waveforms."""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

RESULT_FILE_SCHEMA = "coilem.client_result/v1"

# Result keys holding field pictures for the app's viewers (field lines, flux
# density, slot excitation, iron-loss density). One result's field-line plot
# alone is a few MB of JSON; none of the accessors below reads them.
FIELD_KEYS: tuple[str, ...] = (
    "field_line_plot",
    "field_line_frames",
    "field_movie",
    "field_line_movie",
    "field_playback",
    "slot_excitation_frames",
    "flux_density_map",
    "iron_loss_density",
)


def _array(values: Any) -> np.ndarray:
    return np.asarray(values if values is not None else [], dtype=float)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


@dataclasses.dataclass(frozen=True, eq=False)
class Waveform:
    """One quantity sampled over rotor position.

    ``angle_deg`` is the rotor position in electrical degrees, as the app
    plots it; ``values`` holds the quantity in ``unit``.
    """

    name: str
    unit: str
    angle_deg: np.ndarray
    values: np.ndarray

    def __len__(self) -> int:
        return int(self.values.size)

    @property
    def mean(self) -> float:
        return float(np.mean(self.values))

    @property
    def peak_to_peak(self) -> float:
        return float(np.ptp(self.values))


@dataclasses.dataclass(frozen=True, eq=False)
class PhaseWaveforms:
    """Three phase quantities, and line-to-line ones when the result has them."""

    name: str
    unit: str
    angle_deg: np.ndarray
    a: np.ndarray
    b: np.ndarray
    c: np.ndarray
    ab: np.ndarray | None = None
    bc: np.ndarray | None = None
    ca: np.ndarray | None = None

    def __len__(self) -> int:
        return int(self.a.size)


@dataclasses.dataclass(frozen=True)
class DqFluxLinkage:
    """d/q flux linkage at the solved operating point (``summary.dq_flux_linkage``).

    ``L_d_H`` and ``L_q_H`` are the apparent inductances (λd − λpm)/id and
    λq/iq at this point; each is None where its current is about zero.
    ``status`` and ``inductance_status`` carry the app's output status
    (``experimental`` in this release).
    """

    i_d_A: float
    i_q_A: float
    lambda_d_Wb: float
    lambda_q_Wb: float
    torque_dq_Nm: float
    lambda_pm_Wb: float | None
    L_d_H: float | None
    L_q_H: float | None
    current_angle_deg: float | None
    torque_agreement_pct: float | None
    d_axis_source: str | None
    status: str | None
    inductance_status: str | None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> DqFluxLinkage:
        return cls(
            i_d_A=float(record["i_d_A"]),
            i_q_A=float(record["i_q_A"]),
            lambda_d_Wb=float(record["lambda_d_Wb"]),
            lambda_q_Wb=float(record["lambda_q_Wb"]),
            torque_dq_Nm=float(record["torque_dq_Nm"]),
            lambda_pm_Wb=_number(record.get("lambda_pm_Wb")),
            L_d_H=_number(record.get("apparent_L_d_H")),
            L_q_H=_number(record.get("apparent_L_q_H")),
            current_angle_deg=_number(record.get("current_angle_deg")),
            torque_agreement_pct=_number(record.get("torque_agreement_pct")),
            d_axis_source=record.get("d_axis_source"),
            status=record.get("status"),
            inductance_status=record.get("inductance_status"),
        )


@dataclasses.dataclass(frozen=True)
class Cogging:
    """The zero-current cogging sweep over one cogging period (``summary.cogging``)."""

    peak_to_peak_Nm: float
    peak_Nm: float
    first_harmonic_Nm: float
    mean_Nm: float
    endpoint_mismatch_Nm: float | None
    period_elec_deg: float
    period_mech_deg: float
    fundamental_order: int
    positions_per_period: int
    harmonics: tuple[dict[str, Any], ...]
    status: str | None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Cogging:
        return cls(
            peak_to_peak_Nm=float(record["peak_to_peak_Nm"]),
            peak_Nm=float(record["peak_Nm"]),
            first_harmonic_Nm=float(record["first_harmonic_Nm"]),
            mean_Nm=float(record["mean_Nm"]),
            endpoint_mismatch_Nm=_number(record.get("endpoint_mismatch_Nm")),
            period_elec_deg=float(record["period_elec_deg"]),
            period_mech_deg=float(record["period_mech_deg"]),
            fundamental_order=int(record["fundamental_order"]),
            positions_per_period=int(record["positions_per_period"]),
            harmonics=tuple(dict(item) for item in record.get("harmonics") or ()),
            status=record.get("status"),
        )


class Result:
    """The result of one solve.

    The accessors cover the numbers most scripts need; ``data`` holds the
    whole result as the app returns it (JSON-compatible), and ``request`` the
    request that produced it. Quantities that the run did not compute are
    None, for example ``cogging`` when cogging was not requested.
    """

    __slots__ = ("data", "request")

    # The keys of metrics(), in order: one row of a sweep table.
    METRIC_NAMES: tuple[str, ...] = (
        "average_torque_Nm",
        "torque_ripple_pct",
        "back_emf_fundamental_V",
        "lambda_pm_Wb",
        "i_d_A",
        "i_q_A",
        "lambda_d_Wb",
        "lambda_q_Wb",
        "L_d_H",
        "L_q_H",
        "cogging_peak_to_peak_Nm",
        "solve_time_s",
    )

    def __init__(self, data: Mapping[str, Any], request: Mapping[str, Any] | None = None) -> None:
        if not isinstance(data, Mapping) or not isinstance(data.get("summary"), Mapping):
            raise ValueError("Not a coilEM solve result: it has no summary")
        self.data: dict[str, Any] = dict(data)
        self.request: dict[str, Any] | None = dict(request) if request is not None else None

    # -- Headline numbers ---------------------------------------------------------

    @property
    def summary(self) -> dict[str, Any]:
        return self.data["summary"]

    @property
    def metadata(self) -> dict[str, Any]:
        return self.data.get("solve_metadata") or {}

    def _summary_number(self, key: str) -> float | None:
        return _number(self.summary.get(key))

    @property
    def average_torque_Nm(self) -> float | None:
        """Mean torque of the loaded sweep, in N·m."""

        return self._summary_number("avg_torque_Nm")

    @property
    def torque_ripple_pct(self) -> float | None:
        """Torque ripple of the loaded sweep in %, as the app reports it."""

        return self._summary_number("torque_ripple_pct")

    @property
    def back_emf_fundamental_V(self) -> float | None:
        """Fundamental of the phase back-EMF at the operating point's speed (RMS where the solver reports it)."""

        return self._summary_number("back_emf_fundamental_V")

    @property
    def back_emf_thd_pct(self) -> float | None:
        return self._summary_number("back_emf_thd_pct")

    @property
    def lambda_pm_Wb(self) -> float | None:
        """No-load magnet flux linkage amplitude, in Wb."""

        return self._summary_number("lambda_pm_Wb")

    @property
    def Kt_Nm_per_A(self) -> float | None:  # noqa: N802 - the app's symbol
        return self._summary_number("Kt_Nm_per_A")

    @property
    def Ke_Vs_per_rad_mech(self) -> float | None:  # noqa: N802 - the app's symbol
        return self._summary_number("Ke_Vs_per_rad_mech")

    @property
    def peak_flux_density_teeth_T(self) -> float | None:
        return self._summary_number("peak_flux_density_teeth_T")

    @property
    def peak_flux_density_yoke_T(self) -> float | None:
        return self._summary_number("peak_flux_density_yoke_T")

    @property
    def solve_time_s(self) -> float | None:
        return self._summary_number("solve_time_s")

    @property
    def mesh_elements(self) -> int | None:
        value = self.metadata.get("mesh_element_count")
        return int(value) if isinstance(value, int) else None

    @property
    def dq(self) -> DqFluxLinkage | None:
        """d/q flux linkage and apparent inductances, when the run had current."""

        record = self.summary.get("dq_flux_linkage")
        return DqFluxLinkage.from_record(record) if isinstance(record, Mapping) else None

    @property
    def cogging(self) -> Cogging | None:
        """The cogging record, when cogging was requested."""

        record = self.summary.get("cogging")
        return Cogging.from_record(record) if isinstance(record, Mapping) else None

    # -- Waveforms ----------------------------------------------------------------

    def _torque(self, key: str, name: str) -> Waveform | None:
        record = self.data.get(key)
        if not isinstance(record, Mapping) or not record.get("torque_Nm"):
            return None
        return Waveform(name, "N·m", _array(record.get("electrical_angle_deg")), _array(record["torque_Nm"]))

    @property
    def torque(self) -> Waveform | None:
        """Loaded torque over rotor position, or None when torque was not requested."""

        return self._torque("torque_waveform", "torque")

    @property
    def cogging_torque(self) -> Waveform | None:
        """Zero-current cogging torque over one cogging period, when requested."""

        return self._torque("cogging_torque_waveform", "cogging torque")

    @property
    def back_emf(self) -> PhaseWaveforms | None:
        """No-load back-EMF in V at the operating point's speed, when back-EMF was requested."""

        record = self.data.get("back_emf_waveform")
        if not isinstance(record, Mapping) or not record.get("phase_a_V"):
            return None
        optional = {name: record.get(f"line_{name}_V") for name in ("ab", "bc", "ca")}
        return PhaseWaveforms(
            "back-EMF",
            "V",
            _array(record.get("electrical_angle_deg")),
            _array(record["phase_a_V"]),
            _array(record.get("phase_b_V")),
            _array(record.get("phase_c_V")),
            **{name: _array(values) if values else None for name, values in optional.items()},
        )

    @property
    def phase_current(self) -> PhaseWaveforms | None:
        """The phase currents the loaded sweep applied, in A."""

        record = self.data.get("phase_current_waveform")
        if not isinstance(record, Mapping) or not record.get("phase_a_A"):
            return None
        return PhaseWaveforms(
            "phase current",
            "A",
            _array(record.get("electrical_angle_deg")),
            _array(record["phase_a_A"]),
            _array(record.get("phase_b_A")),
            _array(record.get("phase_c_A")),
        )

    # -- Tables and files ---------------------------------------------------------

    def metrics(self) -> dict[str, float | None]:
        """The headline numbers as a flat dict (keys :attr:`METRIC_NAMES`), one row of a sweep table."""

        dq = self.dq
        cogging = self.cogging
        values: dict[str, float | None] = {
            "average_torque_Nm": self.average_torque_Nm,
            "torque_ripple_pct": self.torque_ripple_pct,
            "back_emf_fundamental_V": self.back_emf_fundamental_V,
            "lambda_pm_Wb": self.lambda_pm_Wb,
            "i_d_A": dq.i_d_A if dq else None,
            "i_q_A": dq.i_q_A if dq else None,
            "lambda_d_Wb": dq.lambda_d_Wb if dq else None,
            "lambda_q_Wb": dq.lambda_q_Wb if dq else None,
            "L_d_H": dq.L_d_H if dq else None,
            "L_q_H": dq.L_q_H if dq else None,
            "cogging_peak_to_peak_Nm": cogging.peak_to_peak_Nm if cogging else None,
            "solve_time_s": self.solve_time_s,
        }
        return {name: values[name] for name in self.METRIC_NAMES}

    def without_fields(self) -> Result:
        """A copy without the field pictures (:data:`FIELD_KEYS`); every accessor still works."""

        return Result({key: value for key, value in self.data.items() if key not in FIELD_KEYS}, self.request)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": RESULT_FILE_SCHEMA, "request": copy.deepcopy(self.request), "result": copy.deepcopy(self.data)}

    def save(self, path: str | Path, *, fields: bool = False) -> Path:
        """Write the request and the result to one JSON file.

        The field pictures are left out unless ``fields`` is True; with them
        a file is several MB.
        """

        path = Path(path)
        payload = (self if fields else self.without_fields()).to_dict()
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> Result:
        """Read a file written by :meth:`save`, or a bare result JSON."""

        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(payload, Mapping) and payload.get("schema") == RESULT_FILE_SCHEMA:
            return cls(payload["result"], payload.get("request"))
        return cls(payload)

    def __repr__(self) -> str:
        parts = []
        if self.average_torque_Nm is not None:
            parts.append(f"torque {self.average_torque_Nm:.4g} N·m")
        if self.torque_ripple_pct is not None:
            parts.append(f"ripple {self.torque_ripple_pct:.3g} %")
        if self.back_emf_fundamental_V is not None:
            parts.append(f"back-EMF {self.back_emf_fundamental_V:.4g} V")
        if self.cogging is not None:
            parts.append(f"cogging {self.cogging.peak_to_peak_Nm:.3g} N·m p-p")
        return f"Result({', '.join(parts) or 'no headline numbers'})"
