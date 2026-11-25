"""Reproducible remaining-path audit, separate from the frozen 23-case suite."""

import argparse
import hashlib
import json
from pathlib import Path

from backend.benchmark_suite import thermal_path_reference as reference
from backend.resources import data_file, package_resource
from backend.thermal_network import axial_winding_resistance, slab_mean_resistance, square_bundle_resistance

REGISTRATION = "benchmarks/thermal-v0.6/path-audit-fixtures.json"
SOURCES = ("thermal_network.py", "thermal_rating.py", "models/thermal.py",
           "benchmark_suite/thermal_path_audit.py", "benchmark_suite/thermal_path_reference.py")


def run_suite():
    raw = data_file(REGISTRATION).read_bytes()
    spec = json.loads(raw)
    rows = []

    def check(name, actual, expected, relative, scope="analytical", unit="K", **extra):
        error = abs(actual - expected)
        band = relative * max(abs(expected), 1e-12)
        rows.append(dict(case=name, scope=scope, unit=unit, prediction=actual, reference=expected,
            absolute_error=error, tolerance=band, status="PASS" if error <= band else "FAIL", **extra))

    a = spec["axial"]
    for q in a["net_transfer_W"]:
        r = axial_winding_resistance(a["active_length_m"], a["end_length_m"], a["copper_area_m2"], a["k_W_mK"])
        expected = reference.coil_mean_difference(a["active_length_m"], a["end_length_m"], a["copper_area_m2"], a["k_W_mK"], q)
        check(f"axial_transfer_{q}W", q*r, expected, spec["analytic_relative_tolerance"],
              previous_prediction=q*a["active_length_m"]/(12*a["k_W_mK"]*a["copper_area_m2"]))
    s = spec["slot"]
    # Equal wall temperatures: integrate the parabolic slot profile and add
    # the linear liner drop across the combined area of both faces.
    expected = s["heat_W"] * (s["width_m"] / (6*s["k_W_mK"]*s["wall_area_m2"])
                             + s["liner_m"] / (s["liner_k_W_mK"]*s["wall_area_m2"]))
    actual = s["heat_W"] * (slab_mean_resistance(s["width_m"], s["k_W_mK"], s["wall_area_m2"]/2, two_sided=True)
                           + s["liner_m"]/(s["liner_k_W_mK"]*s["wall_area_m2"]))
    check("symmetric_slot_and_liner", actual, expected, spec["analytic_relative_tolerance"])
    m = spec["magnet"]
    for q in m["heat_W"]:
        expected = q*m["thickness_m"]/(3*m["k_W_mK"]*m["face_area_m2"])
        actual = q*slab_mean_resistance(m["thickness_m"], m["k_W_mK"], m["face_area_m2"], two_sided=False)
        check(f"magnet_mean_{q}W", actual, expected, spec["analytic_relative_tolerance"], previous_prediction=1.5*expected)
    s = spec["square"]
    d, length, k = s["side_m"], s["total_length_m"], s["k_W_mK"]
    area = 4*d*length
    for biot in s["biot"]:
        h = 2*k*biot/d
        actual = square_bundle_resistance(d, area, k, h)*k*length
        (coarse, qc), (fine, qf) = [reference.square_finite_volume(biot, n) for n in spec["finite_volume_grids"]]
        check(f"square_Robin_Bi_{biot}", actual, fine, spec["finite_volume_relative_tolerance"], "finite_volume_crosscheck", "1",
              previous_prediction=(d/(6*k*area)+1/(h*area))*k*length,
              mesh_difference=abs(fine-coarse), reference_rejected_heat=qf)
        check(f"square_mesh_Bi_{biot}", coarse, fine, spec["finite_volume_mesh_relative_tolerance"], "reference_convergence", "1")
        check(f"square_balance_Bi_{biot}", qf, 1, 1e-8, "reference_balance", "W")
    low, high = s["small_biot"], s["large_biot"]
    check("square_convection_limit", square_bundle_resistance(d, area, k, 2*k*low/d)*k*length,
          1/(8*low), s["limit_relative_tolerance"], unit="1")
    check("square_isothermal_limit", square_bundle_resistance(d, area, k, 2*k*high/d)*k*length,
          reference.square_dirichlet_mean_coefficient(), s["limit_relative_tolerance"], unit="1")
    # At prescribed measured heat and ambient, a global resistance multiplier
    # scales the rise; fixed-current R(T) is intentionally NOT used for this fit.
    base = square_bundle_resistance(d, area, k, 2*k/d)
    c = spec["calibration"]
    for multiplier in c["multipliers"]:
        rise = c["heat_W"] * base
        measured_rise = multiplier * rise
        fitted = rise * measured_rise / rise**2
        check(f"fixed_heat_calibration_{multiplier}", fitted, multiplier, spec["analytic_relative_tolerance"], "synthetic_calibration", "1")
    return dict(protocol=spec["protocol"], claim=spec["claim"], output_status="experimental",
        output_status_reason="Idealized path checks only; actual cooling, packing and rotor losses remain unqualified.",
        status="FAIL" if any(r["status"]=="FAIL" for r in rows) else "PASS", registration=spec,
        registration_sha256=hashlib.sha256(raw).hexdigest(),
        source_sha256={p:hashlib.sha256(package_resource(*p.split('/')).read_bytes()).hexdigest() for p in SOURCES}, cases=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Evidence already exists; choose a new output file")
    bundle = run_suite()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(bundle, indent=2, allow_nan=False)+'\n')
    print(json.dumps(dict(status=bundle['status'], cases=len(bundle['cases']),
                         failures=[r['case'] for r in bundle['cases'] if r['status']=='FAIL'])))
    return int(bundle['status']=='FAIL')


if __name__ == '__main__':
    raise SystemExit(main())
