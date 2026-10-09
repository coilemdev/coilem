"""Project-local nonlinear steel data, independent of the bundled catalog."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import struct

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MU_0 = 4 * math.pi * 1e-7
MAX_CURVE_POINTS = 4096
CUSTOM_STEEL_PATTERN = r"^custom:[0-9a-f]{64}$"


def validate_bh_points(points: list[tuple[float, float]]) -> None:
    if not 3 <= len(points) <= MAX_CURVE_POINTS:
        raise ValueError(f"B-H curve must contain 3–{MAX_CURVE_POINTS} points.")
    if points[0] != (0.0, 0.0):
        raise ValueError("B-H curve must start at B=0 T, H=0 A/m.")
    previous_b, previous_h = points[0]
    for index, (b, h) in enumerate(points):
        if not math.isfinite(b) or not math.isfinite(h):
            raise ValueError(f"Point {index + 1}: B and H must be finite numbers.")
        if not 0 <= b <= 5 or not 0 <= h <= 1e7:
            raise ValueError(f"Point {index + 1}: expected B between 0 and 5 T and H between 0 and 10,000,000 A/m.")
        if index:
            if b <= previous_b or h <= previous_h:
                raise ValueError(f"Point {index + 1}: B and H must both strictly increase; remove duplicates or reversed points.")
            mu_r = b / (MU_0 * h)
            if not 1 <= mu_r <= 1e6:
                raise ValueError(f"Point {index + 1}: relative permeability must be between 1 and 1,000,000; check the units.")
        previous_b, previous_h = b, h


def curve_digest(points: list[tuple[float, float]]) -> str:
    # JSON.stringify converts -0 to 0. Hash both as positive zero so a curve's
    # identity survives browser requests and project save/reopen.
    return hashlib.sha256(b"".join(
        struct.pack(">dd", 0.0 if b == 0 else b, 0.0 if h == 0 else h)
        for b, h in points
    )).hexdigest()


class CustomSteel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    id: str = Field(pattern=CUSTOM_STEEL_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=500)
    lamination_thickness_mm: float | None = Field(default=None, gt=0, le=10)
    bh_curve: list[tuple[float, float]] = Field(min_length=3, max_length=MAX_CURVE_POINTS)
    curve_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("bh_curve", mode="before")
    @classmethod
    def numeric_points(cls, value):
        if not isinstance(value, (list, tuple)) or any(
            not isinstance(point, (list, tuple)) or len(point) != 2
            or any(isinstance(number, bool) or not isinstance(number, (int, float)) for number in point)
            for point in value
        ):
            raise ValueError("B-H points must contain numeric B and H values.")
        return [(0.0 if b == 0 else b, 0.0 if h == 0 else h) for b, h in value]

    @model_validator(mode="after")
    def check_identity(self):
        validate_bh_points(self.bh_curve)
        if self.curve_sha256 != curve_digest(self.bh_curve):
            raise ValueError("Custom steel curve checksum mismatch; reimport the original CSV.")
        if self.id != self.content_id():
            raise ValueError("Custom steel identity mismatch; reimport after changing its name, source, thickness, or curve.")
        return self

    def content_id(self) -> str:
        identity = [self.name, self.source, self.lamination_thickness_mm, self.curve_sha256]
        return "custom:" + hashlib.sha256(json.dumps(identity, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()

    def preflight_record(self, roles: list[str]) -> dict:
        return {
            "schema_version": "openem.electrical_steel_curve/v1",
            "consumer": "magneto2d",
            "material_key": self.id,
            "material_name": self.name,
            "roles": sorted(roles),
            "curve_sha256": self.curve_sha256,
            "point_count": len(self.bh_curve),
            "b_range_T": [0, self.bh_curve[-1][0]],
            "h_range_A_per_m": [0, self.bh_curve[-1][1]],
            "source": {"description": self.source, "kind": "user_supplied"},
            "lamination_thickness_mm": self.lamination_thickness_mm,
            "core_loss_model": "unavailable",
        }


class SteelImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=500)
    lamination_thickness_mm: float | None = Field(default=None, gt=0, le=10)
    csv_text: str = Field(min_length=1, max_length=524288)


def import_steel(request: SteelImportRequest) -> CustomSteel:
    text = request.csv_text.lstrip("\ufeff")
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    try:
        rows = list(csv.reader(io.StringIO("\n".join(lines)), strict=True))
    except csv.Error as exc:
        raise ValueError(f"Invalid CSV: {exc}") from exc
    if not rows or [value.strip() for value in rows[0]] not in (["B_T", "H_A_per_m"], ["H_A_per_m", "B_T"]):
        raise ValueError("CSV header must be B_T,H_A_per_m or H_A_per_m,B_T (tesla and amperes per metre).")
    reverse = rows[0][0].strip() == "H_A_per_m"
    points: list[tuple[float, float]] = []
    for index, row in enumerate(rows[1:], start=2):
        if len(row) != 2:
            raise ValueError(f"CSV row {index}: expected exactly two numeric columns.")
        try:
            point = (float(row[0]), float(row[1]))
        except ValueError as exc:
            raise ValueError(f"CSV row {index}: expected numeric B and H values.") from exc
        points.append((point[1], point[0]) if reverse else point)
    validate_bh_points(points)
    provisional = CustomSteel.model_construct(
        id="",
        name=request.name,
        source=request.source,
        lamination_thickness_mm=request.lamination_thickness_mm,
        bh_curve=points,
        curve_sha256=curve_digest(points),
    )
    return CustomSteel.model_validate({**provisional.model_dump(), "id": provisional.content_id()})


def is_custom_steel_id(value: str) -> bool:
    return re.fullmatch(CUSTOM_STEEL_PATTERN, value) is not None
