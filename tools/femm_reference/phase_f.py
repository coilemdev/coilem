"""Preserved Phase F lowering and extraction, with repository-local inputs."""

from __future__ import annotations

import ast
import dataclasses
import datetime
import importlib.util
import math
from pathlib import Path

from tools.femm_reference import runtime as local
from tools.femm_reference.runtime import canonical, read, sha
from tools.femm_reference.runtime import write as write

PUBLIC = local.DATA
SPEC = PUBLIC / "spec_f.json"
PHASE_A_POSTPROCESS = local.PACKAGE / "_vendor/e/backend/femm_postprocess.py"
PHASE_A_NORMALIZER = local.PACKAGE / "_vendor/reference_conventions.py"
FROZEN_HASHES = {
    "phase_a_postprocess": "7de76febe40e8b8ae03392bec20e97ff06335d55863dc0ee7d72e71d0453a60d",
    "phase_a_normalizer": "0898a42d232ca2120b70fa2d23b287e60808e4ab7271187e158811b2ec21f6b4",
}
CANDIDATE_COMMIT = "34de0f4ca1604311f15edf6fb49b5a2a1bf27909"

CASE_ID = "spm_outer_14p12s_drone__baseline"

CASE_IDS = (
    CASE_ID,
    "spm_outer_14p12s_drone__high_current",
    "spm_outer_14p12s_drone__tight_airgap",
    "spm_outer_14p12s_drone__angle30",
    "spm_outer_14p12s_drone_noload__baseline",
    "spm_outer_12p9s_micro__baseline",
    "spm_outer_12p9s_micro_noload__baseline",
    "spm_outer_10p12s_single_layer__baseline",
    "spm_outer_28p24s_multirotor__baseline",
    "spm_outer_30p27s_hub__baseline",
)

CONVENTION = "public-clockwise-v2"

GRID = [7.5 * index for index in range(48)]

PRECISION = 1e-8

MIN_ANGLE = 30

MU0 = 4 * math.pi * 1e-7

DERIVATIVE_POLICY = {
    "name": "registered-Phase-A-numpy-gradient-native-then-public-v1",
    "native_grid_electrical_deg": GRID,
    "operator": "numpy.gradient(flux_Wb, numpy.radians(native_angles_deg)); edge_order=1 (numpy default)",
    "native_voltage": "e_native = +omega_electrical * d(lambda_native)/d(theta_native)",
    "public_voltage": "e_public(theta) = -e_native((-theta) modulo 360), exact sample permutation",
    "public_flux": "lambda_public(theta) = lambda_native((-theta) modulo 360)",
    "endpoint_policy": "Retain original Phase A one-sided endpoint stencils at native 0 and 352.5 degrees; no periodic replacement.",
    "fundamental": "phase A voltage DFT bin 1: RMS=sqrt(2)*abs(sum(e*exp(-j*theta))/48)",
    "prohibited_transforms_applied": [],
    "no_fitting_filtering_interpolation_resampling_or_rescaling": True,
}


def load_runtime():
    local.activate("f")
    from backend.excitation import phase_axis_offset_deg, resolve_phase_current_sample
    from backend.geometry_drawer import compute_geometry
    from backend.geometry_ir import build_geometry_ir, slot_layer_assignments
    from backend.material_contract import load_electrical_steel_curve
    from backend.models import MotorConfig
    from tools.femm_reference import automation, ir_helpers

    ir_helpers.Automation = automation.Automation
    return {
        "lrk": ir_helpers,
        "resolve": resolve_phase_current_sample,
        "axis": phase_axis_offset_deg,
        "compute": compute_geometry,
        "build": build_geometry_ir,
        "assignments": slot_layer_assignments,
        "rotate": ir_helpers._rotate_magnets_in_place,
        "steel": load_electrical_steel_curve,
        "MotorConfig": MotorConfig,
        "mirror": ir_helpers._clockwise_excitation_config,
    }


def inherited_lrk(path):
    receipt = read(path)
    assert receipt["candidate_commit"] == CANDIDATE_COMMIT
    assert receipt["status"] == "INVESTIGATION_COMPLETE_OWNER_REVIEW_REQUIRED"
    return {
        "receipt_sha256": sha(path),
        "status": receipt["status"],
        "corrected_counts": receipt["corrected_counts"],
        "corrected_remaining_refined_checks": receipt["corrected_remaining_refined_checks"],
        "findings": receipt["findings"],
        "interpretation": "Inherited verbatim from prior LRK investigation; two remaining FAIL flags are not waived or reclassified here.",
    }


def source_identity(*, field_run):
    return local.identity("f")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def input_contract(runtime, case_id=CASE_ID):
    spec = read(SPEC)
    assert spec["protocol_version"] == "1.8.0" and spec["convention"] == CONVENTION
    assert case_id in CASE_IDS
    case = next(case for case in spec["cases"] if case["id"] == case_id)
    assert case["phase"] == "F" and len(case["jobs"]) == 1
    job = case["jobs"][0]
    fixture = PUBLIC / job["fixture"]
    assert sha(fixture) == job["fixture_sha256"], "Fixture bytes differ from registered request"
    raw = read(fixture)
    assert canonical(raw) == job["input_sha256"], "Canonical request differs from registered request"
    config = runtime["MotorConfig"].model_validate(raw)
    assert config.rotor_layout == "outer" and config.topology == "SPM"
    sp = config.solve_params
    assert sp.excitation_mode == "sinusoidal" and sp.current_amplitude_convention == "peak"
    assert sp.rotor_sweep_range_deg == 360 and sp.rotor_step_deg == 7.5 and sp.rated_speed_rpm == 3000
    if case_id == CASE_ID:
        assert config.winding.turns_per_coil == 12 and config.winding.layers == 2
    assert sp.magnet_temperature_C is None
    assert config.materials.magnet_grade == "N42"
    assert config.materials.stator_steel == config.materials.rotor_steel == "M350-50A"
    steel = runtime["steel"]("M350-50A")
    assert steel.sha256 == spec["material_contract"]["curve_sha256"]
    magnet = spec["material_contract"]["magnets"]["N42"]
    assert magnet == {"Br_T": 1.315, "mu_r": 1.05}
    return config, spec, job, steel


def driver_vector(runtime, config, theta, drive):
    if drive == "production":
        vector = tuple(runtime["resolve"](runtime["mirror"](config), -theta).phase_current_a)
        angle = 90 - theta - config.solve_params.current_angle_deg - runtime["axis"](config)
    elif drive == "brief":
        vector = tuple(runtime["resolve"](config, theta, clockwise_positive=True).phase_current_a)
        angle = theta - 90 + config.solve_params.current_angle_deg - runtime["axis"](config)
    else:
        raise ValueError("Explicit production or brief drive is required")
    expected = tuple(config.solve_params.current_amplitude_A * math.sin(math.radians(angle - 120 * k)) for k in range(3))
    assert all(abs(actual - expected) <= 1e-12 for actual, expected in zip(vector, expected, strict=True)), (
        "Drive resolver differs from its declared source formula"
    )
    return vector


def rotated_ir(runtime, config, theta):
    pairs = config.rotor.pole_count // 2
    native_mechanical = -float(theta) / pairs
    geom = runtime["compute"](config)
    runtime["rotate"](geom, math.radians(native_mechanical))
    ir = runtime["build"](config, geom=geom, rotor_angle_deg=native_mechanical)
    assert ir.rotor_layout == "outer" and ir.metadata["radial_layout"] == "outer_rotor"
    issues = ir.validation_report().issues
    assert not issues, (theta, issues)
    return ir, native_mechanical


def winding_specs(runtime, config, ir):
    result = {}
    for region in ir.regions:
        if region.kind != "SlotWinding":
            continue
        prefix, phase, direction, slot, *layers = region.source_group.split(":")
        assert prefix == "winding" and phase in "ABC" and direction in {"in", "out"}
        index = int(slot.removeprefix("slot"))
        layer = int(layers[0].removeprefix("layer")) if layers else 1
        side = next(side for side in runtime["assignments"](config, index) if side.layer == layer)
        assert (phase, direction) == (side.phase, side.direction)
        turns = config.winding.turns_per_coil * side.turn_fraction
        assert math.isclose(turns, round(turns), abs_tol=1e-12), "FEMM circuit turns must be integral"
        result[region.region_id] = {
            "slot_index": index,
            "layer": layer,
            "phase": phase,
            "direction": direction,
            "turn_fraction": side.turn_fraction,
            "unsigned_turns": int(round(turns)),
            "signed_turns": int(round(turns)) * (1 if direction == "in" else -1),
            "area_mm2": region.area_mm2,
        }
    expected_count = sum(len(runtime["assignments"](config, index)) for index in range(config.stator.slot_count))
    assert len(result) == expected_count
    return result


def mesh_settings(ir, airgap_mesh_scale=1.0):
    gap = float(ir.metadata["airgap_rotor_side_radius_mm"]) - float(ir.metadata["airgap_stator_side_radius_mm"])
    assert gap > 0
    assert airgap_mesh_scale in (1.0, 0.5)
    gap_mesh = gap / 4 * airgap_mesh_scale
    return {
        "airgap_mesh_size_mm": gap_mesh,
        "max_arc_segment_deg": min(1.0, math.degrees(gap_mesh / ir.metadata["airgap_rotor_side_radius_mm"])),
        "precision": PRECISION,
        "min_angle_deg": MIN_ANGLE,
        "smartmesh": 0,
        "magnet_and_pocket_mesh_size_mm": 0.15,
        "other_mesh_size_mm": 0.25,
        "airgap_mesh_scale": airgap_mesh_scale,
    }


def lower_model(femm, runtime, config, ir, currents, steel, airgap_mesh_scale=1.0):
    """Lower exact IR curves; keep selection of moving air separate from WST matter."""
    lrk = runtime["lrk"]
    settings = mesh_settings(ir, airgap_mesh_scale)
    sides = winding_specs(runtime, config, ir)
    femm.newdocument(0)
    femm.mi_probdef(0, "millimeters", "planar", PRECISION, config.stator.stack_length_mm, MIN_ANGLE)
    femm.mi_smartmesh(0)
    femm.mi_addboundprop("AzZero", 0, 0, 0, 0, 0, 0, 0, 0, 0)
    femm.mi_addmaterial("Air", 1, 1, 0, 0, 0)
    femm.mi_addmaterial("Copper", 1, 1, 0, 0, 0)
    names = {"air": "Air", "conductor:copper": "Copper"}
    for role in ("stator", "rotor"):
        name = "Steel_" + role
        femm.mi_addmaterial(name, 1, 1, 0, 0, 0)
        for b, h in steel.points:
            femm.mi_addbhpoint(name, b, h)
        names[f"steel:{role}:M350-50A"] = name
    hc = 1.315 / (MU0 * 1.05)
    femm.mi_addmaterial("PermanentMagnet", 1.05, 1.05, hc, 0, 0)
    names["magnet:N42"] = "PermanentMagnet"
    paths = max(1, config.winding.parallel_paths)
    for phase, current in zip("ABC", currents, strict=True):
        femm.mi_addcircprop(phase, current / paths, 1)
    edges, nodes = {}, {}
    for region in ir.regions:
        for loop in region.loops:
            for segment in loop.segments:
                a, b = lrk.xy(segment.start), lrk.xy(segment.end)
                ra, rb = tuple(round(v, 9) for v in a), tuple(round(v, 9) for v in b)
                center = tuple(round(v, 9) for v in lrk.xy(segment.center)) if segment.center else None
                # Midpoint distinguishes complementary arcs with the same endpoints.
                middle = tuple(round(v, 9) for v in lrk.edge_midpoint(segment)) if segment.kind == "arc" else None
                key = segment.kind, tuple(sorted((ra, rb))), center, middle
                if key not in edges or segment.boundary_tag:
                    edges[key] = segment
                nodes.setdefault(ra, a)
                nodes.setdefault(rb, b)
    for point in nodes.values():
        femm.mi_addnode(*point)
    for segment in edges.values():
        a, b = lrk.xy(segment.start), lrk.xy(segment.end)
        if segment.kind == "line":
            femm.mi_drawline(*a, *b)
        elif segment.sweep_deg > 0:
            femm.mi_drawarc(*a, *b, segment.sweep_deg, settings["max_arc_segment_deg"])
        else:
            femm.mi_drawarc(*b, *a, -segment.sweep_deg, settings["max_arc_segment_deg"])
        if segment.boundary_tag == "dirichlet_az_zero":
            midpoint = lrk.edge_midpoint(segment)
            if segment.kind == "arc":
                femm.mi_selectarcsegment(*midpoint)
                femm.mi_setarcsegmentprop(settings["max_arc_segment_deg"], "AzZero", 0, 0)
            else:
                femm.mi_selectsegment(*midpoint)
                femm.mi_setsegmentprop("AzZero", 0, 1, 0, 0)
            femm.mi_clearselected()
    labels = {}
    for region in ir.regions:
        point = lrk.label(region)
        labels[region.region_id] = point
        side = sides.get(region.region_id)
        circuit, turns = (side["phase"], side["signed_turns"]) if side else ("<None>", 0)
        direction = math.degrees(math.atan2(region.magnetization_xy[1], region.magnetization_xy[0])) if region.magnetization_xy else 0
        group = 2 if region.motion_group == "rotor" else 1 if region.kind in ("StatorYoke", "StatorTooth", "SlotWinding") else 0
        mesh = settings["airgap_mesh_size_mm"] if region.kind == "Airgap" else 0.15 if region.kind in ("Magnet", "MagnetPocketAir") else 0.25
        femm.mi_addblocklabel(*point)
        femm.mi_selectlabel(*point)
        femm.mi_setblockprop(names[region.material_key], 0, mesh, circuit, direction, group, turns)
        femm.mi_clearselected()
    femm.mi_addblocklabel(0, 0)
    femm.mi_selectlabel(0, 0)
    femm.mi_setblockprop("<No Mesh>", 1, 0, "<None>", 0, 0, 0)
    femm.mi_clearselected()
    return {**settings, "labels": labels, "winding_specs": sides, "unique_edges": len(edges), "nodes": len(nodes), "magnet_Hc_A_per_m": hc}


def emf_from_public_flux(flux, rpm, pairs):
    import numpy as np

    assert len(flux) == 48 and all(len(row) == 3 for row in flux)
    order = [(-index) % 48 for index in range(48)]
    native_flux = np.array([flux[index] for index in order], dtype=float)
    omega_e = rpm * 2 * math.pi / 60 * pairs
    native_emf = omega_e * np.gradient(native_flux, np.radians(np.array(GRID)), axis=0)
    public_emf = [-native_emf[index, :] for index in order]
    return [[float(value) for value in row] for row in public_emf], native_flux.tolist(), native_emf.tolist()


def phase_harmonic(values):
    assert len(values) == 48 and all(math.isfinite(value) for value in values)
    real = sum(v * math.cos(math.radians(theta)) for theta, v in zip(GRID, values, strict=True)) / 48
    imag = -sum(v * math.sin(math.radians(theta)) for theta, v in zip(GRID, values, strict=True)) / 48
    return {"rms_V": math.sqrt(2) * math.hypot(real, imag), "phase_deg": math.degrees(math.atan2(imag, real))}


def verify_original_derivative():
    """Execute only the pinned pure derivative method on analytic synthetic flux."""
    import numpy as np

    assert sha(PHASE_A_POSTPROCESS) == FROZEN_HASHES["phase_a_postprocess"]
    tree = ast.parse(PHASE_A_POSTPROCESS.read_text(encoding="utf-8"))
    node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_compute_back_emf_scaled")
    namespace = {"np": np}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<pinned-pure-phase-a-derivative>", "exec"), namespace)
    radians = np.radians(np.array(GRID))
    public_flux = [
        [float(np.cos(theta + shift) + 0.07 * np.sin(5 * theta + shift)) for shift in (0, -2 * math.pi / 3, 2 * math.pi / 3)] for theta in radians
    ]
    ours, native_flux, native_emf = emf_from_public_flux(public_flux, 3000, 7)
    expected = namespace["_compute_back_emf_scaled"](
        None, *np.array(native_flux).T.tolist(), GRID, 3000 * 2 * math.pi / 60 * 7, basis_label="electrical", log_result=False
    )
    assert np.array_equal(np.array(native_emf), np.array(expected).T), "Derivative differs from original Phase A"
    assert sha(PHASE_A_NORMALIZER) == FROZEN_HASHES["phase_a_normalizer"]
    spec = importlib.util.spec_from_file_location("_pinned_phase_a_normalizer", PHASE_A_NORMALIZER)
    normalizer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(normalizer)
    raw = {"back_emf_waveform": {"electrical_angle_deg": GRID, **{f"phase_{phase}_V": list(expected[index]) for index, phase in enumerate("abc")}}}
    normalized = normalizer.normalize_femm_reference({"result": {}, "raw_reference_result": raw})["back_emf_waveform"]
    for index, phase in enumerate("abc"):
        assert normalized[f"phase_{phase}_V"] == [row[index] for row in ours]
    return {
        "status": "PASS",
        "synthetic_only": True,
        "sample_count": 48,
        "derivative_bitwise_identical_to_pinned_original": True,
        "public_normalization_exactly_identical_to_pinned_original": True,
        "normalizer_version": normalizer.VERSION,
    }


class FakeFEMM:
    """Record preprocessing calls only; reject any accidental solve in preflight."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name not in {
            "newdocument",
            "mi_probdef",
            "mi_smartmesh",
            "mi_addboundprop",
            "mi_addmaterial",
            "mi_addbhpoint",
            "mi_addcircprop",
            "mi_addnode",
            "mi_drawline",
            "mi_drawarc",
            "mi_selectarcsegment",
            "mi_setarcsegmentprop",
            "mi_selectsegment",
            "mi_setsegmentprop",
            "mi_clearselected",
            "mi_addblocklabel",
            "mi_selectlabel",
            "mi_setblockprop",
        }:
            raise AssertionError("Preflight attempted non-preprocessing FEMM command: " + name)
        return lambda *args: self.calls.append((name, args))


def preflight(runtime, config, steel, drive, airgap_mesh_scale=1.0):
    checks = []
    for theta in GRID:
        ir, native = rotated_ir(runtime, config, theta)
        currents = driver_vector(runtime, config, theta, drive)
        assert abs(sum(currents)) < 1e-10
        sides = winding_specs(runtime, config, ir)
        settings = mesh_settings(ir, airgap_mesh_scale)
        tags = [segment for region in ir.regions for loop in region.loops for segment in loop.segments if segment.boundary_tag == "dirichlet_az_zero"]
        expected_radii = {config.stator.ID_mm / 2, config.rotor.OD_mm / 2}
        assert {round(segment.radius_mm, 9) for segment in tags} == expected_radii
        assert all(region.motion_group == "rotor" for region in ir.regions if region.kind in {"RotorCore", "Magnet", "MagnetPocketAir"})
        assert sum(side["signed_turns"] for side in sides.values() if side["phase"] == "A") == 0
        assert sum(side["signed_turns"] for side in sides.values() if side["phase"] == "B") == 0
        assert sum(side["signed_turns"] for side in sides.values() if side["phase"] == "C") == 0
        checks.append(
            {
                "electrical_angle_deg": theta,
                "native_mechanical_angle_deg": native,
                "ir_sha256_canonical": canonical(dataclasses.asdict(ir)),
                "region_count": len(ir.regions),
                "winding_region_count": len(sides),
                "current_A": list(currents),
                **settings,
            }
        )
    fake = FakeFEMM()
    ir, _ = rotated_ir(runtime, config, 0)
    lowered = lower_model(fake, runtime, config, ir, driver_vector(runtime, config, 0, drive), steel, airgap_mesh_scale)
    blocks = [args for name, args in fake.calls if name == "mi_setblockprop"]
    winding = [args for args in blocks if args[3] in {"A", "B", "C"}]
    assert len(winding) == len(lowered["winding_specs"])
    assert sorted(args[6] for args in winding) == sorted(side["signed_turns"] for side in lowered["winding_specs"].values())
    assert blocks[-1][0] == "<No Mesh>"
    circuits = [args for name, args in fake.calls if name == "mi_addcircprop"]
    assert len(circuits) == 3 and all(args[2] == 1 for args in circuits)
    assert sum(name == "mi_addbhpoint" for name, _ in fake.calls) == 2 * len(steel.points)
    magnet = next(args for name, args in fake.calls if name == "mi_addmaterial" and args[0] == "PermanentMagnet")
    assert magnet[1:4] == (1.05, 1.05, 1.315 / (MU0 * 1.05))
    problem = next(args for name, args in fake.calls if name == "mi_probdef")
    assert problem == (0, "millimeters", "planar", PRECISION, config.stator.stack_length_mm, MIN_ANGLE)
    return {
        "status": "PASS",
        "field_solves_started": False,
        "all_48_rotated_ir_checks": checks,
        "fake_femm_lowering": {
            "status": "PASS",
            "calls": len(fake.calls),
            "winding_blocks": len(winding),
            "unsigned_turns_per_region": sorted({abs(args[6]) for args in winding}),
            "unique_edges": lowered["unique_edges"],
        },
        "original_derivative_and_normalizer_check": verify_original_derivative(),
    }


def actual_session_identity(automation, expected):
    import win32api
    import win32process

    session = dict(automation.sessions[-1])
    handle = win32api.OpenProcess(0x0400 | 0x0010, False, session["pid"])
    try:
        executable = Path(win32process.GetModuleFileNameEx(handle, 0))
    finally:
        handle.Close()
    actual = {name: sha(executable.parent / name) for name in expected}
    assert actual == expected, "COM launched a different FEMM installation"
    return {**session, "actual_COM_binary_sha256": actual}


def extract(femm, config, ir, settings, currents):
    labels = settings["labels"]
    femm.mo_clearblock()
    for region in ir.regions:
        if region.kind in {"RotorCore", "Magnet"}:
            femm.mo_selectblock(*labels[region.region_id])
    rotor_ccw = float(femm.mo_blockintegral(22))
    femm.mo_clearblock()
    femm.mo_groupselectblock(1)
    stator_ccw = float(femm.mo_blockintegral(22))
    femm.mo_clearblock()
    paths = max(1, config.winding.parallel_paths)
    audit = []
    for region in ir.regions:
        side = settings["winding_specs"].get(region.region_id)
        expected = side["signed_turns"] * currents["ABC".index(side["phase"])] / paths if side else 0.0
        femm.mo_selectblock(*labels[region.region_id])
        actual = float(femm.mo_blockintegral(7))
        area = float(femm.mo_blockintegral(5))
        femm.mo_clearblock()
        tolerance = max(1e-7, abs(expected) * 1e-7)
        assert abs(actual - expected) <= tolerance, (region.region_id, expected, actual)
        assert area > 0 and math.isfinite(area)
        audit.append(
            {
                "region_id": region.region_id,
                "kind": region.kind,
                "expected_amp_turns_A": expected,
                "actual_amp_turns_A": actual,
                "tolerance_A": tolerance,
                "solved_area_mm2": area * 1e6,
                "ir_area_mm2": region.area_mm2,
            }
        )
    properties = [[float(value) for value in femm.mo_getcircuitproperties(phase)] for phase in "ABC"]
    for index, values in enumerate(properties):
        assert len(values) == 3 and all(math.isfinite(value) for value in values)
        assert abs(values[0] * paths - currents[index]) <= max(1e-9, abs(currents[index]) * 1e-9)
    assert all(math.isfinite(value) for value in (rotor_ccw, stator_ccw))
    return {
        "raw_rotor_ccw_Nm": rotor_ccw,
        "raw_stator_ccw_Nm": stator_ccw,
        "rotor_cw_Nm": -rotor_ccw,
        "stator_reaction_rotor_cw_Nm": stator_ccw,
        "circuit_properties_ABC": properties,
        "terminal_flux_linkage_Wb": [values[2] / paths for values in properties],
        "terminal_current_A": [values[0] * paths for values in properties],
        "current_integral_audit": audit,
        "mesh_element_count": int(femm.mo_numelements()),
    }


def assemble_result(config, points, case_id=CASE_ID):
    loaded = [point for point in points if point["stage"] == "loaded"]
    noload = [point for point in points if point["stage"] == "noload"]
    assert [point["electrical_angle_deg"] for point in loaded] == GRID
    assert [point["electrical_angle_deg"] for point in noload] == GRID
    flux = [point["terminal_flux_linkage_Wb"] for point in noload]
    emf, native_flux, native_emf = emf_from_public_flux(flux, config.solve_params.rated_speed_rpm, config.rotor.pole_count // 2)
    phases = [[row[index] for row in emf] for index in range(3)]
    harmonics = [phase_harmonic(values) for values in phases]
    torques = [point["rotor_cw_Nm"] for point in loaded]
    mean = sum(torques) / 48
    sp = config.solve_params
    omega_m = sp.rated_speed_rpm * 2 * math.pi / 60
    implied = 3 * harmonics[0]["rms_V"] * sp.current_amplitude_A / math.sqrt(2) * math.cos(math.radians(sp.current_angle_deg)) / omega_m
    ratio = mean / implied if abs(implied) > 1e-15 else None
    phase_differences = [(harmonics[index]["phase_deg"] - harmonics[0]["phase_deg"]) % 360 for index in (1, 2)]
    phase_error = [min(abs(angle - 120), abs(angle - 240)) for angle in phase_differences]
    balance = (
        [abs(harmonics[index]["rms_V"] / harmonics[0]["rms_V"] - 1) * 100 for index in (1, 2)] if harmonics[0]["rms_V"] > 1e-15 else [None, None]
    )
    counts = [point["mesh_element_count"] for point in points]
    loaded_case = sp.current_amplitude_A > 0
    energy_status = ("PASS" if ratio is not None and abs(ratio - 1) <= 0.05 else "FAIL") if loaded_case else "NOT_APPLICABLE_NOLOAD_CASE"
    if case_id.endswith("__high_current"):
        energy_status = "REPORTED_HIGH_CURRENT_SATURATION_EXPECTED"
    self_checks = {
        "sign": {"status": ("PASS" if mean > 0 else "FAIL") if loaded_case else "NOT_APPLICABLE_NOLOAD_CASE", "mean_loaded_rotor_cw_Nm": mean},
        "energy_balance": {"status": energy_status, "signed_ratio": ratio, "implied_torque_Nm": implied, "tolerance_fraction": 0.05},
        "phase_fundamental_balance": {
            "status": "PASS" if all(v is not None and v <= 1 for v in balance) else "FAIL",
            "B_C_relative_to_A_delta_pct": balance,
            "tolerance_pct": 1,
        },
        "phase_spacing": {
            "status": "REPORTED",
            "B_C_relative_to_A_deg": phase_differences,
            "distance_to_120_or_240_deg": phase_error,
            "note": "No numeric phase-angle gate is added; report spacing against the request's 120-degree expectation.",
        },
        "other_nine_cases_and_two_mesh_controls": {"status": "NOT_RUN_OWNER_PILOT_CHECKPOINT_REQUIRED"},
        "current_angle_ratio_and_separate_noload_case_ratio": {"status": "PENDING_CROSS_CASE_REVIEW"},
        "noload_mean_rotor_cw_Nm": sum(p["rotor_cw_Nm"] for p in noload) / 48,
    }
    result = {
        "summary": {"avg_torque_Nm": mean, "back_emf_fundamental_V": harmonics[0]["rms_V"]},
        "torque_waveform": {"electrical_angle_deg": GRID, "torque_Nm": torques},
        "back_emf_waveform": {"electrical_angle_deg": GRID, **{f"phase_{phase}_V": phases[index] for index, phase in enumerate("abc")}},
        "no_load_flux_linkage_waveform": {
            "electrical_angle_deg": GRID,
            **{f"phase_{phase}_Wb": [row[index] for row in flux] for index, phase in enumerate("abc")},
        },
        "solve_metadata": {
            "femm_version": "4.2 (actual COM binaries checked against frozen seal)",
            "torque_method": "weighted_stress",
            "torque_body": "rotor",
            "torque_selection": "RotorCore and Magnet only; MagnetPocketAir excluded from WST mask",
            "torque_sign": "rotor clockwise = -FEMM rotor CCW; stator reaction diagnostic only",
            "precision": PRECISION,
            "min_angle_deg": MIN_ANGLE,
            "airgap_mesh_size_mm": points[0]["settings"]["airgap_mesh_size_mm"],
            "mesh_element_count": max(counts),
            "mesh_element_count_range": [min(counts), max(counts)],
            "mesh_element_counts_per_position": counts,
            "back_emf_derivative_policy": DERIVATIVE_POLICY,
            "phase_fundamentals": dict(zip("ABC", harmonics, strict=True)),
        },
    }
    from backend.benchmark_suite.metrics import validate_abc

    validate_abc(result, config.model_dump(mode="json"), native=False)
    evidence = {
        "native_electrical_angle_deg": GRID,
        "native_flux_linkage_ABC_Wb": native_flux,
        "native_back_emf_ABC_V": native_emf,
        "policy": DERIVATIVE_POLICY,
    }
    return result, self_checks, evidence
