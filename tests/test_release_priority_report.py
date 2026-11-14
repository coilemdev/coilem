"""Readable report units and partial results retain their numeric meaning."""
import io
from copy import deepcopy

from pypdf import PdfReader

from backend.models import MotorConfig
from backend.public_report import _setting_entry, build_public_run_csv, build_public_run_pdf
from backend.winding_resistance import winding_resistance
from tests.test_public_report_exports import CONFIG, _result_with_motor_field


def report_arguments():
    config = deepcopy(CONFIG)
    config["solve_params"].update(solve_quality="quick", rotor_rotation_model="remesh_per_step", torque_method="weighted_stress")
    result = _result_with_motor_field()
    result["summary"]["dq_flux_linkage"] = {
        "i_d_A": -7.248, "i_q_A": 19.936, "lambda_d_Wb": 0.02, "lambda_q_Wb": 0.01,
        "lambda_pm_Wb": 0.03, "apparent_L_d_H": 0.001, "apparent_L_q_H": 0.002,
        "torque_dq_Nm": 4.25, "current_angle_deg": 20, "positions": 4,
    }
    result["summary"]["winding_resistance"] = winding_resistance(MotorConfig.model_validate(config)).model_dump(mode="json")
    result["warnings"] = ["Partial electrical sweep: averages describe the sampled window."]
    return {
        "project": config, "request": {"resolved_config": config}, "result": result, "material": {},
        "manifest": {"project_name": "Release 0.5.8 report verification",
                     "provenance": {"platform": {"system": "Darwin", "machine": "arm64", "python": "3.12"}}},
    }


def test_pdf_labels_peak_currents_and_plain_settings_without_changing_csv_values():
    args = report_arguments()
    original = deepcopy(args)
    pdf = build_public_run_pdf(**args)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "-7.248 A peak" in text
    assert "19.936 A peak" in text
    assert "Accuracy plan\nPreview" in text
    assert "Remesh each position" in " ".join(text.split())
    assert "Weighted stress" in text
    assert '{"machine"' not in text
    assert "machine: arm64" in text
    assert "Partial electrical sweep" in text
    assert text.count("Phase resistance, 20 C") == 1
    csv = build_public_run_csv(**args).decode()
    assert "-7.248" in csv and "19.936" in csv
    assert args == original


def test_report_display_names_are_scoped_to_the_setting():
    assert _setting_entry("solve_quality", "fine") == ("Solve quality", "High accuracy")
    assert _setting_entry("mesh_density", "fine") == ("Mesh density", "fine")
    assert _setting_entry("unknown_setting", "custom") == ("Unknown setting", "custom")
    assert _setting_entry("unknown_setting", "standard") == ("Unknown setting", "standard")


def test_input_interpretation_is_reported_as_information():
    args = report_arguments()
    args["result"]["input_notes"] = ["Actual outer bridge: 3.36 mm; the requested clearance is a minimum."]
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(build_public_run_pdf(**args))).pages)
    assert "Interpreted rotor inputs" in text
    assert "Actual outer bridge: 3.36 mm" in text
