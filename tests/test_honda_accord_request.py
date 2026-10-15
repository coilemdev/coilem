"""The frozen 2005 Honda Accord request (#92) is the builder's output and a valid public design."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FOLDER = REPO_ROOT / "docs/hardware-validation/honda-accord-2005"


def test_committed_request_is_the_builder_output():
    from tools import honda_accord_request

    committed = json.loads((FOLDER / "request.json").read_text(encoding="utf-8"))
    assert committed == honda_accord_request.request


def test_request_is_a_valid_public_design_with_the_published_magnet_volume():
    from backend.geometry import validate_geometry
    from backend.geometry_ir import build_geometry_ir, validate_geometry_ir
    from backend.public_policy import parse_public_motor_config, public_config_support_error

    config = parse_public_motor_config(json.loads((FOLDER / "request.json").read_text(encoding="utf-8")))
    assert public_config_support_error(config) is None
    assert validate_geometry(config) == []
    report = validate_geometry_ir(build_geometry_ir(config))
    assert report.issues == ()
    # Two 18.45 x 4.46 mm magnets per pole (Table 2.3), drawn as one 36.9 mm bar per pole.
    published = 16 * 2 * 18.45 * 4.46
    assert abs(report.region_area_by_kind_mm2["Magnet"] - published) < 0.01 * published


def test_targets_match_the_report_tables():
    back = json.loads((FOLDER / "target-back-emf.json").read_text(encoding="utf-8"))["rows"]
    locked = json.loads((FOLDER / "target-locked-rotor.json").read_text(encoding="utf-8"))["rows"]
    assert [r["motor_shaft_rpm"] for r in back][:3] == [200, 400, 600] and len(back) == 18
    assert back[9] == {"motor_shaft_rpm": 2000, "va_ln_rms_V": 57.39, "vb_ln_rms_V": 56.93, "vc_ln_rms_V": 56.97, "average_ln_rms_V": 57.10}
    assert [(r["current_A"], r["peak_torque_Nm"]) for r in locked][::4] == [(25, 18.3), (125, 79.4), (225, 135)]
