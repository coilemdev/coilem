"""Decompose saved off-grid flux error without collecting new FEM evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from backend.benchmark_suite.temperature_metrics import TemperatureReference
from backend.drive_performance import MapModel
from backend.temperature_maps import TemperatureMapBracket, interpolate_temperature_map


def isolate(path: Path) -> dict:
    content = path.read_bytes()
    record = json.loads(content)
    bracket = TemperatureMapBracket.model_validate(record["bracket"])
    rows = []
    for raw in record["references"]:
        reference = TemperatureReference.model_validate(raw)
        direct = reference.direct_map
        if direct is None or direct.scope_key != reference.computation_scope_key:
            raise ValueError("Isolation requires a complete direct map with matching identity")
        predicted = MapModel.from_map(interpolate_temperature_map(bracket, reference.temperature_C).map)
        temperature_exact = MapModel.from_map(direct)
        grid = {(p.current_peak_A, p.gamma_deg) for p in direct.points}
        for point in reference.points:
            if (point.current_peak_A, point.gamma_deg) in grid:
                continue
            args = (np.array(point.current_peak_A), np.array(point.gamma_deg))
            a = float(predicted.sample_points(*args)["lambda_d"])
            b = float(temperature_exact.sample_points(*args)["lambda_d"])
            c = point.lambda_d_Wb
            rows.append(dict(temperature_C=reference.temperature_C, current_peak_A=point.current_peak_A,
                gamma_deg=point.gamma_deg, bracket_sample_Wb=a, direct_temperature_map_sample_Wb=b,
                direct_off_grid_Wb=c, temperature_path_delta_Wb=a-b,
                current_angle_grid_delta_Wb=b-c, total_delta_Wb=a-c))
    return dict(case_id=record["case_id"], source_bundle_sha256=hashlib.sha256(content).hexdigest(),
        method="A: sampled bracket map; B: sampled direct-temperature map; C: direct off-grid solve. A-C = (A-B) + (B-C).",
        claim="Diagnostic decomposition on the saved preview grid; no new solves or changed acceptance bands.",
        original_acceptance=record["acceptance"]["status"], rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    print(json.dumps(isolate(args.bundle), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
