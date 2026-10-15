"""Geometry-bound current validation, historical replay, and immutable references."""
import copy
import math
from pathlib import Path

import pytest

from backend.excitation import phase_axis_offset_deg
from backend.models import MotorConfig
from tools.benchmark_suite.bldc_metrics import golden_sector, validate_lane_result
from tools.benchmark_suite.cli import inputs
from tools.benchmark_suite.contract import DEFAULT_BUNDLE, ROOT, SPEC, read, sha
from tools.benchmark_suite.references import load_bundle, load_suite

OLD = ROOT / "benchmarks/abcd-v1.1/benchmark_spec.json"
NEW = ROOT / "benchmarks/abcd-v1.3/benchmark_spec.json"
BUNDLE = ROOT / "benchmarks/reference-baselines/ipm-high-output-v3"
AXES = {"spm_14p12s_high_pole":15.0, "spm_4p12s_small":0.0, "spm_8p12s_reference":30.0}


def test_default_uses_reconciled_contract_and_complete_v3_reference():
    assert SPEC == NEW and DEFAULT_BUNDLE == BUNDLE
    manifest, records, _ = load_bundle(BUNDLE,load_suite(SPEC))
    assert len(records)==29 and manifest['validation_status']=='REVIEW_REQUIRED'


def test_angle_revision_changes_only_validation_and_keeps_historical_bytes():
    old, new = load_suite(OLD), load_suite(NEW)
    configs, protocols, golden = inputs(new, new["cases"])
    _, historical_protocols, _ = inputs(old, old["cases"])
    assert new["material_contract"] == old["material_contract"]
    assert new["golden_sha256"] == old["golden_sha256"] == "0914644d93f05fa5738534c518e2ecffeca2d129d8a38fbe8b8df2f65c695b86"
    assert new["validation_change"]["post_hoc_registration"] is True
    for before, after in zip(old["cases"],new["cases"],strict=True):
        assert before["id"] == after["id"] and before["jobs"] == after["jobs"]
        if before["phase"] != "D":
            assert before == after
            continue
        cid = after["id"]
        protocol = protocols[cid]
        assert protocol["matrix"] == historical_protocols[cid]["matrix"]
        assert protocol["excitation"] == historical_protocols[cid]["excitation"]
        assert protocol["gates"] == historical_protocols[cid]["gates"]
        assert protocol["gates"]["native_standard_to_fine_ripple_delta_percentage_points_max"] == 5.0
        assert protocol["current_angle_convention"]["phase_a_axis_offset_electrical_deg"] == AXES[cid]
        # Independent literal fixture expectations guard a shared producer/helper bug.
        assert phase_axis_offset_deg(MotorConfig.model_validate(configs[cid,"native-standard"])) == AXES[cid]


@pytest.mark.parametrize("cid", AXES)
def test_new_frame_validates_actual_femm_currents_without_rewriting_historical_failures(cid):
    old, new = load_suite(OLD), load_suite(NEW)
    _, previous, golden = inputs(old, old["cases"])
    _, current, _ = inputs(new, new["cases"])
    before = {p:sha(p) for p in BUNDLE.glob("*.json")}
    _, records, _ = load_bundle(BUNDLE,new)
    validate_lane_result("femm-standard",records[cid],current[cid],golden=golden)
    if AXES[cid]:
        with pytest.raises(ValueError,match="current phase sequence"):
            validate_lane_result("femm-standard",records[cid],previous[cid],golden=golden)
    else:
        validate_lane_result("femm-standard",records[cid],previous[cid],golden=golden)
    assert before == {p:sha(p) for p in BUNDLE.glob("*.json")}
    wrong = copy.deepcopy(records[cid])
    wrong["phase_current_waveform"]["phase_a_A"][0] += 1
    with pytest.raises(ValueError,match="current phase sequence"):
        validate_lane_result("femm-standard",wrong,current[cid],golden=golden)


@pytest.mark.parametrize("axis", [0.0,15.0,30.0])
def test_sector_boundaries_use_registered_axis_and_advance_without_waveform_fitting(axis):
    protocol={"excitation":{"commutation_advance_deg":7.5},"current_angle_convention":{
        "version":"winding-phase-a-v1","physical_angle_convention":"public-clockwise-v2",
        "phase_a_axis_offset_electrical_deg":axis}}
    boundary=60-axis-7.5
    assert golden_sector(boundary-1e-9,protocol)==0
    assert golden_sector(boundary,protocol)==1
    assert golden_sector(boundary+1e-9,protocol)==1
    assert golden_sector(360-axis-7.5,protocol)==0


@pytest.mark.parametrize("invalid", [True,math.nan,math.inf,-1,360,"30",None])
def test_invalid_axis_is_rejected(invalid):
    p={"excitation":{"commutation_advance_deg":0},"current_angle_convention":{
        "version":"winding-phase-a-v1","physical_angle_convention":"public-clockwise-v2",
        "phase_a_axis_offset_electrical_deg":invalid}}
    with pytest.raises(ValueError,match="axis offset"):
        golden_sector(0,p)


def test_legacy_protocol_retains_fixed_axis_and_unknown_frames_fail_closed():
    assert golden_sector(45,{"excitation":{"commutation_advance_deg":0}})==0
    with pytest.raises(ValueError,match="Unsupported"):
        golden_sector(45,{"excitation":{"commutation_advance_deg":0},"current_angle_convention":{"version":"unknown"}})


@pytest.mark.parametrize("mutation", ["missing_bridge","manifest_hash","measured_commit","protocol_hash","limits"])
def test_reference_reuse_is_explicit_and_hash_bound(mutation):
    spec=load_suite(NEW)
    if mutation=="missing_bridge":spec.pop("reference_compatibility")
    elif mutation=="manifest_hash":spec["reference_compatibility"]["manifest_sha256"]="0"*64
    elif mutation=="measured_commit":spec["reference_compatibility"]["reference_commit"]="wrong"
    elif mutation=="protocol_hash":spec["reference_compatibility"]["six_step_protocol_sha256"]["spm_8p12s_reference"]="0"*64
    else:
        spec["material_contract"]=copy.deepcopy(spec["material_contract"])
        spec["material_contract"]["steel_grade"]="other"
    with pytest.raises(ValueError,match="protocol mismatch|identity mismatch|contract mismatch"):
        load_bundle(BUNDLE,spec)


@pytest.mark.parametrize("kind", ["grid","limit","current"])
def test_report_migration_rejects_numerical_or_physical_setting_changes(monkeypatch,kind):
    from tools import report_benchmark_against_reference as late
    from tools.benchmark_suite import contract

    measured=load_suite(OLD)
    configs,protocols,golden=inputs(measured,measured['cases'])
    original_read=contract.read
    def changed(path):
        value=original_read(path)
        if Path(path).name=='spm_8p12s_reference.json':
            if kind=='grid':value['matrix']['cross_lane_product']['sample_count']+=1
            elif kind=='limit':value['gates']['native_standard_to_fine_ripple_delta_percentage_points_max']=6
            else:value['excitation']['product_current_A']=51
        return value
    monkeypatch.setattr(contract,'read',changed)
    with pytest.raises(ValueError,match='grids, excitation settings or numerical limits'):
        late.reconcile_angles(NEW,measured,[],configs,protocols,golden,BUNDLE)
