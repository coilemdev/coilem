"""Strict electrical-steel curve loading and provenance records.

The checked-in curve bytes are part of the solver input contract. Consumers
must fail closed when those bytes or their ordered numeric contents change so a
comparison cannot silently become a comparison of different materials.
"""

from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


class ElectricalSteelCurveError(RuntimeError):
    """Raised when an electrical-steel curve violates its frozen contract."""


@dataclass(frozen=True)
class ElectricalSteelSpec:
    material_key: str
    relative_path: str
    sha256: str
    point_count: int
    b_min_T: float
    b_max_T: float
    source_model_url: str
    source_formula_url: str
    source_license: str
    notice_path: str


@dataclass(frozen=True)
class ElectricalSteelCurve:
    spec: ElectricalSteelSpec
    path: Path
    sha256: str
    points: tuple[tuple[float, float], ...]

    def preflight_record(
        self,
        *,
        consumer: str,
        roles: Iterable[str] = (),
    ) -> dict[str, object]:
        """Return the normalized record embedded in solve provenance."""

        b_values = tuple(point[0] for point in self.points)
        h_values = tuple(point[1] for point in self.points)
        return {
            "schema_version": "openem.electrical_steel_curve/v1",
            "consumer": consumer,
            "material_key": self.spec.material_key,
            "roles": sorted(set(roles)),
            "curve_path": self.spec.relative_path,
            "curve_sha256": self.sha256,
            "point_count": len(self.points),
            "b_range_T": [min(b_values), max(b_values)],
            "h_range_A_per_m": [min(h_values), max(h_values)],
            "columns": {
                "flux_density": "B_T",
                "field_strength": "H_A_per_m",
            },
            "source": {
                "model_url": self.spec.source_model_url,
                "formula_url": self.spec.source_formula_url,
                "license": self.spec.source_license,
                "notice_path": self.spec.notice_path,
            },
        }


REPO_ROOT = Path(__file__).resolve().parents[1]

M350_50A_SPEC = ElectricalSteelSpec(
    material_key="M350-50A",
    relative_path="materials/electrical-steel/M350-50A.csv",
    sha256="d6096df7cc7103e8b9fc77407b1750e8ddf9f5d0cd1fdf8ad748d9febf896c3d",
    point_count=252,
    b_min_T=0.0,
    b_max_T=2.5,
    source_model_url=(
        "https://github.com/modelica/ModelicaStandardLibrary/blob/master/"
        "Modelica/Magnetic/FluxTubes/Material/SoftMagnetic/ElectricSheet/"
        "M350_50A.mo"
    ),
    source_formula_url=(
        "https://github.com/modelica/ModelicaStandardLibrary/blob/master/"
        "Modelica/Magnetic/FluxTubes/Material/SoftMagnetic/mu_rApprox.mo"
    ),
    source_license="BSD-3-Clause",
    notice_path="THIRD_PARTY_NOTICES.md",
)

ELECTRICAL_STEEL_SPECS: Mapping[str, ElectricalSteelSpec] = {
    M350_50A_SPEC.material_key: M350_50A_SPEC,
}


def _parse_curve_bytes(
    raw: bytes,
    *,
    path: Path,
) -> tuple[tuple[float, float], ...]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ElectricalSteelCurveError(
            f"Electrical-steel curve is not UTF-8: {path}"
        ) from exc

    data_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    rows = list(csv.reader(data_lines))
    if not rows or rows[0] != ["B_T", "H_A_per_m"]:
        raise ElectricalSteelCurveError(
            f"Electrical-steel curve {path} must use the exact B_T,H_A_per_m header"
        )

    points: list[tuple[float, float]] = []
    for row_number, row in enumerate(rows[1:], start=2):
        if len(row) != 2:
            raise ElectricalSteelCurveError(
                f"Electrical-steel curve {path} row {row_number} must contain two columns"
            )
        try:
            b_tesla = float(row[0])
            h_a_per_m = float(row[1])
        except ValueError as exc:
            raise ElectricalSteelCurveError(
                f"Electrical-steel curve {path} row {row_number} is not numeric"
            ) from exc
        if not math.isfinite(b_tesla) or not math.isfinite(h_a_per_m):
            raise ElectricalSteelCurveError(
                f"Electrical-steel curve {path} row {row_number} is not finite"
            )
        if b_tesla < 0.0 or h_a_per_m < 0.0:
            raise ElectricalSteelCurveError(
                f"Electrical-steel curve {path} row {row_number} must be non-negative"
            )
        if points and b_tesla <= points[-1][0]:
            raise ElectricalSteelCurveError(
                f"Electrical-steel curve {path} B values must be strictly increasing"
            )
        if points and h_a_per_m < points[-1][1]:
            raise ElectricalSteelCurveError(
                f"Electrical-steel curve {path} H values must be non-decreasing"
            )
        points.append((b_tesla, h_a_per_m))

    if not points or points[0] != (0.0, 0.0):
        raise ElectricalSteelCurveError(
            f"Electrical-steel curve {path} must begin at B=0 T, H=0 A/m"
        )
    return tuple(points)


def load_electrical_steel_curve(
    material_key: str,
    *,
    curve_path: Path | None = None,
    verify_frozen_identity: bool = True,
) -> ElectricalSteelCurve:
    """Load and validate a supported electrical-steel curve.

    ``verify_frozen_identity=False`` exists only for parser-level tests and
    tooling that validates proposed replacement data. Solver adapters must use
    the default fail-closed behavior.
    """

    spec = ELECTRICAL_STEEL_SPECS.get(material_key)
    if spec is None:
        supported = ", ".join(sorted(ELECTRICAL_STEEL_SPECS))
        raise ElectricalSteelCurveError(
            f"Unsupported electrical-steel curve {material_key!r}; supported: {supported}"
        )

    path = curve_path if curve_path is not None else REPO_ROOT / spec.relative_path
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ElectricalSteelCurveError(
            f"Required electrical-steel curve is missing: {path}"
        ) from exc
    except OSError as exc:
        raise ElectricalSteelCurveError(
            f"Could not read electrical-steel curve {path}: {exc}"
        ) from exc

    digest = hashlib.sha256(raw).hexdigest()
    if verify_frozen_identity and digest != spec.sha256:
        raise ElectricalSteelCurveError(
            f"Electrical-steel curve SHA-256 mismatch for {material_key}: "
            f"expected {spec.sha256}, got {digest}"
        )

    points = _parse_curve_bytes(raw, path=path)
    if len(points) != spec.point_count:
        raise ElectricalSteelCurveError(
            f"Electrical-steel curve {path} has {len(points)} points; "
            f"expected {spec.point_count}"
        )
    if points[0][0] != spec.b_min_T or points[-1][0] != spec.b_max_T:
        raise ElectricalSteelCurveError(
            f"Electrical-steel curve {path} spans {points[0][0]}..{points[-1][0]} T; "
            f"expected {spec.b_min_T}..{spec.b_max_T} T"
        )

    return ElectricalSteelCurve(
        spec=spec,
        path=path,
        sha256=digest,
        points=points,
    )


def electrical_steel_preflight_records(
    role_material_keys: Mapping[str, str],
    *,
    consumer: str,
) -> list[dict[str, object]]:
    """Validate shared curves and return one record per configured material.

    Historical private-only grades are left to their legacy adapters. Any
    configured grade that has a shared contract is always checked here before
    solver execution.
    """

    roles_by_material: dict[str, list[str]] = {}
    for role, material_key in role_material_keys.items():
        if material_key in ELECTRICAL_STEEL_SPECS:
            roles_by_material.setdefault(material_key, []).append(role)

    return [
        load_electrical_steel_curve(material_key).preflight_record(
            consumer=consumer,
            roles=roles,
        )
        for material_key, roles in sorted(roles_by_material.items())
    ]
