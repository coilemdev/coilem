"""Data-only reference bundles, already normalized to public clockwise coordinates."""

from tools.benchmark_suite import CONVENTION, PROTOCOL_VERSION
from tools.benchmark_suite.contract import canonical, checked_json, read, sha


def load_suite(path):
    spec = read(path)
    if spec["schema"] != "coilem.benchmark_spec/v1" or spec["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("Unsupported suite protocol")
    if spec["convention"] != CONVENTION:
        raise ValueError("Suite coordinate convention mismatch")
    return spec


def load_bundle(directory, spec):
    manifest = read(directory / "manifest.json")
    if (
        manifest["schema"] != "coilem.frozen_reference_bundle/v1"
        or manifest["protocol_version"] != spec["protocol_version"]
        or manifest["convention"] != CONVENTION
        or manifest.get("normalized") is not True
        or manifest["material_contract"] != spec["material_contract"]
    ):
        raise ValueError("Reference material, protocol or coordinate contract mismatch; register a new bundle")
    records = {}
    for case in spec["cases"]:
        entry = manifest["records"].get(case["id"])
        if entry is None:
            continue
        record = checked_json(directory, entry["file"], entry["sha256"])
        if (
            entry["input_sha256"] != case["jobs"][0]["input_sha256"]
            or record["input_sha256"] != entry["input_sha256"]
            or record["case_id"] != case["id"]
            or record["phase"] != case["phase"]
            or record["convention"] != CONVENTION
            or record.get("normalized") is not True
            or record["reference_commit"] != manifest["reference_commit"]
            or (case["phase"] == "D" and record["protocol_sha256"] != case["protocol_sha256"])
        ):
            raise ValueError(f"Reference input or identity mismatch: {case['id']}; register a new bundle")
        records[case["id"]] = record["result"]
    return manifest, records, canonical({"manifest": sha(directory / "manifest.json"), "records": manifest["records"]})


def verify_materials(expected):
    from backend.material_contract import load_electrical_steel_curve
    from backend.public_material_catalog import MAGNET_SOLVER_INPUTS

    if load_electrical_steel_curve(expected["steel_grade"]).sha256 != expected["curve_sha256"]:
        raise ValueError("Steel curve changed; register a new reference bundle")
    for grade, props in expected["magnets"].items():
        if MAGNET_SOLVER_INPUTS[grade][1:3] != (props["Br_T"], props["mu_r"]):
            raise ValueError(f"Magnet contract changed: {grade}; register a new reference bundle")
