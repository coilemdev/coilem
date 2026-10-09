"""Public single-run report and replay package contracts."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from backend.public_report import (
    build_public_run_csv,
    build_public_run_pdf,
    write_replayable_run_package,
)
from backend.solve_workspace import SolveWorkspace, SolveWorkspaceError

pypdf = pytest.importorskip("pypdf")

CONFIG = json.loads(Path("tests/fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"))


def _result() -> dict:
    angles = [0.0, 30.0, 60.0, 90.0]
    return {
        "summary": {
            "avg_torque_Nm": 4.25,
            "torque_ripple_pct": 2.5,
            "back_emf_fundamental_V": 18.75,
            "back_emf_thd_pct": 3.2,
            "Kt_Nm_per_A": 0.425,
            "peak_flux_density_teeth_T": 1.62,
            "peak_flux_density_yoke_T": 1.34,
            "solve_time_s": 12.5,
        },
        "torque_waveform": {
            "electrical_angle_deg": angles,
            "torque_Nm": [4.1, 4.3, 4.2, 4.4],
        },
        "back_emf_waveform": {
            "electrical_angle_deg": angles,
            "phase_a_V": [0.0, 9.0, 18.0, 9.0],
            "phase_b_V": [-15.6, -18.0, -9.0, 0.0],
            "phase_c_V": [15.6, 9.0, -9.0, -9.0],
        },
        "solve_metadata": {
            "solver_name": "magneto2d-rust-0.3.2",
            "mesh_element_count": 12345,
            "rotor_positions": 4,
            "mesh_density": "normal",
        },
        "warnings": ["Peak tooth flux density is near the review threshold."],
    }


@pytest.mark.parametrize(
    "untrusted_text",
    ["=1+1", "+1+1", "-1+1", "@SUM(1,1)", "\t=1+1", "\r=1+1", "\n=1+1", "  =1+1"],
)
def test_csv_exports_untrusted_text_as_literals_without_changing_numeric_data(
    untrusted_text: str,
) -> None:
    arguments = {
        "project": {},
        "request": {"resolved_config": {"materials": {"source": untrusted_text}}},
        "result": {
            "summary": {"avg_torque_Nm": -4.25},
            "back_emf_waveform": {"phase_a_V": [-15.6, 0.0, 15.6]},
            "warnings": [untrusted_text],
        },
        "material": {"records": [{"material_name": untrusted_text}]},
        "manifest": {"project_name": untrusted_text},
    }
    original = deepcopy(arguments)

    rows = list(csv.reader(io.StringIO(build_public_run_csv(**arguments).decode("utf-8"))))

    assert ["identity", "project_name", "", "'" + untrusted_text, ""] in rows
    assert ["material", "material_name", "", "'" + untrusted_text, "0"] in rows
    assert ["setting", "materials.source", "", "'" + untrusted_text, ""] in rows
    # Warnings are intentionally stripped by the report's existing normalization.
    assert ["warning", "message", "", "'" + untrusted_text.strip(), "0"] in rows
    assert ["summary", "avg_torque_Nm", "N m", "-4.25", ""] in rows
    assert ["back_emf_waveform", "phase_a_V", "V", "-15.6", "0"] in rows
    assert ["back_emf_waveform", "phase_a_V", "V", "0", "1"] in rows
    assert arguments == original


@pytest.mark.parametrize("linked_directory", [False, True])
def test_replay_package_rejects_symlinks_without_reading_outside_files(
    tmp_path: Path,
    linked_directory: bool,
) -> None:
    run_directory = tmp_path / "run"
    run_directory.mkdir()
    (run_directory / "project.openem").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("private audit sentinel", encoding="utf-8")
    link = run_directory / "linked-evidence"
    try:
        link.symlink_to(outside if linked_directory else sentinel, target_is_directory=linked_directory)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable on this platform: {exc}")
    target = tmp_path / "run-package.zip"

    with pytest.raises((ValueError, OSError)):
        write_replayable_run_package(
            run_directory,
            target,
            completed_at="2026-10-09T00:00:00Z",
        )

    assert sentinel.read_text(encoding="utf-8") == "private audit sentinel"
    assert link.is_symlink()
    if target.is_file() and zipfile.is_zipfile(target):
        with zipfile.ZipFile(target) as archive:
            assert not any("linked-evidence" in name for name in archive.namelist())


def test_replay_package_rejects_linked_output_without_overwriting_user_file(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run"
    run_directory.mkdir()
    (run_directory / "project.openem").write_text("{}", encoding="utf-8")
    sentinel = tmp_path / "existing-user-file.txt"
    sentinel.write_text("preserve existing user data", encoding="utf-8")
    target = run_directory / "run-package.zip"
    try:
        target.symlink_to(sentinel)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable on this platform: {exc}")

    with pytest.raises((ValueError, OSError)):
        write_replayable_run_package(
            run_directory,
            target,
            completed_at="2026-10-09T00:00:00Z",
        )

    assert sentinel.read_text(encoding="utf-8") == "preserve existing user data"
    assert target.is_symlink()


@pytest.mark.parametrize("used", ["weighted_stress", "contour", None])
def test_pdf_reports_actual_torque_method_separately_from_request(used):
    config = deepcopy(CONFIG)
    config["solve_params"]["torque_method"] = "weighted_stress"
    result = _result()
    result["solve_metadata"]["torque_method"] = used
    pdf = build_public_run_pdf(
        project=config, request={"resolved_config": config}, result=result, material={}, manifest={},
    )
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert f"Torque method used\n{used or 'Not recorded'}" in text
    assert "Torque method requested\nweighted_stress" in text


def _complete_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("COILEM_BUILD_COMMIT", "a" * 40)
    workspace = SolveWorkspace(tmp_path / "data")
    writer = workspace.begin_run(
        project_name="M350 launch motor.coilem",
        config=CONFIG,
        submitted_request={"config": CONFIG, "project_name": "M350 launch motor"},
    )
    location = writer.complete(_result_with_motor_field())
    return workspace, location


def _result_with_motor_field() -> dict:
    result = _result()
    result["field_line_plot"] = {
        "nodes_mm": [[-2, -1], [2, -1], [2, 1], [-2, 1], [0, 0]],
        "triangles": [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
        "regions": ["stator_yoke", "slot_winding", "magnet", "rotor_core"],
        "element_b_mag_t": [0.0, 1.0, 2.0, 3.0],
        "contour_levels": [{"level": 0.1, "segments_mm": [[-1, 0, 1, 0]]}],
    }
    result["field_line_frames"] = [{"angle_deg": 45.0}]
    return result


def test_pdf_embeds_stored_motor_and_field_with_correct_orientation_and_range():
    arguments = {
        "project": CONFIG, "request": {"resolved_config": CONFIG},
        "result": _result_with_motor_field(), "material": {}, "manifest": {},
    }
    pdf = build_public_run_pdf(**arguments)
    assert build_public_run_pdf(**arguments) == pdf
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    figure_page = reader.pages[1]
    text = figure_page.extract_text()
    assert "2D motor cross-section" in text
    assert "Solved flux-density heatmap" in text
    assert "45 deg electrical / 22.5 deg mechanical" in text
    assert "Flux density |B| (T)" in text
    assert "0.000" in text and "3.000" in text
    images = [image.image.convert("RGB") for image in figure_page.images]
    assert len(images) == 2
    geometry = next(image for image in images if image.getpixel((600, 800)) == (138, 155, 173))
    field = next(image for image in images if image.getpixel((600, 800)) == (20, 42, 97))
    assert geometry.getpixel((600, 400)) == (229, 62, 62)  # Magnet above center.
    assert field.getpixel((200, 650)) == (220, 61, 61)  # Highest |B| at left.
    assert field.getpixel((600, 600)) == (241, 194, 50)  # Stored field line.
    assert field.getpixel((20, 20)) == (255, 255, 255)  # Preserve equal aspect.


@pytest.mark.parametrize("bad_values", [[0.0], [0.0, 1.0, float("nan"), 3.0], [0.0, -1.0, 2.0, 3.0]])
def test_invalid_field_values_keep_geometry_but_explain_unavailable_heatmap(bad_values):
    result = _result_with_motor_field()
    result["field_line_plot"]["element_b_mag_t"] = bad_values
    reader = pypdf.PdfReader(io.BytesIO(build_public_run_pdf(
        project=CONFIG, request={"resolved_config": CONFIG},
        result=result, material={}, manifest={},
    )))
    page = reader.pages[1]
    assert len(page.images) == 1
    assert "Heatmap unavailable" in page.extract_text()


def test_invalid_saved_mesh_does_not_draw_a_partial_motor():
    result = _result_with_motor_field()
    result["field_line_plot"]["triangles"][0] = [-1, 1, 4]
    reader = pypdf.PdfReader(io.BytesIO(build_public_run_pdf(
        project=CONFIG, request={"resolved_config": CONFIG},
        result=result, material={}, manifest={},
    )))
    page = reader.pages[1]
    assert len(page.images) == 0
    assert "Motor figure unavailable" in page.extract_text()
    assert "Heatmap unavailable" in page.extract_text()


def test_stored_pdf_csv_and_package_are_bound_to_one_immutable_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, location = _complete_run(tmp_path, monkeypatch)
    loaded = workspace.load_run(location.project_slug, location.run_id)
    manifest = loaded["manifest"]
    project = loaded["project"]
    request = loaded["request"]
    result = loaded["result"]
    material = json.loads((location.path / "material.json").read_text(encoding="utf-8"))

    pdf_path = workspace.resolve_export(
        location.project_slug,
        location.run_id,
        "pdf",
    )
    csv_path = workspace.resolve_export(
        location.project_slug,
        location.run_id,
        "csv",
    )
    package_path = workspace.resolve_export(
        location.project_slug,
        location.run_id,
        "package",
    )
    pdf_bytes = pdf_path.read_bytes()
    csv_bytes = csv_path.read_bytes()

    # ReportLab is run in invariant mode and reads no current/live state.
    arguments = {
        "project": project,
        "request": request,
        "result": result,
        "material": material,
        "manifest": manifest,
    }
    assert build_public_run_pdf(**arguments) == pdf_bytes
    assert build_public_run_csv(**arguments) == csv_bytes

    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)
    for expected in (
        "M350 launch motor.coilem",
        location.run_id,
        manifest["completed_at"],
        "M350-50A",
        "d6096df7cc7103e8b9fc77407b1750e8ddf9f5d0cd1fdf8ad748d9febf896c3d",
        "magneto2d-rust-0.3.2",
        "12345",
        "4.25 N m",
        "Peak tooth flux density is near the review threshold.",
        "temperature prediction is not included",
        "Exact resolved settings",
    ):
        assert expected in text

    rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
    assert ["report_schema", "coilem.single_run_report.v1"] in rows
    assert [
        "identity",
        "run_id",
        "",
        location.run_id,
        "",
    ] in rows
    assert [
        "identity",
        "completed_at",
        "",
        manifest["completed_at"],
        "",
    ] in rows
    assert ["summary", "avg_torque_Nm", "N m", "4.25", ""] in rows
    assert ["setting", "materials.stator_steel", "", "M350-50A", ""] in rows
    assert [
        "solve_metadata",
        "solver_name",
        "",
        "magneto2d-rust-0.3.2",
        "",
    ] in rows

    with zipfile.ZipFile(package_path) as archive:
        assert {
            "manifest.json",
            "project.coilem",
            "request.json",
            "result.json",
            "material.json",
            "report/report.pdf",
            "report/report.csv",
            "report/summary.json",
        } <= set(archive.namelist())
        packaged_manifest = json.loads(archive.read("manifest.json"))
        expected_packaged_manifest = deepcopy(manifest)
        expected_packaged_manifest["exports"]["package_sha256"] = None
        assert packaged_manifest == expected_packaged_manifest
        assert json.loads(archive.read("project.coilem")) == project
        assert archive.read("report/report.pdf") == pdf_bytes
        assert archive.read("report/report.csv") == csv_bytes

    assert manifest["exports"]["package_sha256"]


def test_six_step_exports_preserve_drive_identity_waveforms_and_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COILEM_BUILD_COMMIT", "b" * 40)
    config = deepcopy(CONFIG)
    config["solve_params"].update(
        {
            "excitation_mode": "ideal_six_step_120",
            "current_amplitude_A": 42.0,
            "current_amplitude_convention": "plateau",
            "commutation_advance_deg": 7.5,
            "phase_connection": "wye",
        }
    )
    result = _result()
    result["phase_current_waveform"] = {
        "electrical_angle_deg": [0.0, 30.0, 60.0, 90.0],
        "phase_a_A": [42.0, 42.0, 0.0, 0.0],
        "phase_b_A": [-42.0, -42.0, -42.0, -42.0],
        "phase_c_A": [0.0, 0.0, 42.0, 42.0],
    }
    result["back_emf_waveform"].update(
        {
            "line_ab_V": [15.6, 27.0, 27.0, 9.0],
            "line_bc_V": [-31.2, -27.0, 0.0, 9.0],
            "line_ca_V": [15.6, 0.0, -27.0, -18.0],
        }
    )
    result["solve_metadata"].update(
        {
            "excitation_mode": "ideal_six_step_120",
            "current_amplitude_A": 42.0,
            "current_amplitude_convention": "plateau",
            "commutation_advance_deg": 7.5,
            "phase_connection": "wye",
            "excitation_convention_version": "openem.bldc_six_step/v1",
            "loaded_cycle_complete": False,
        }
    )
    workspace = SolveWorkspace(tmp_path / "data")
    writer = workspace.begin_run(
        project_name="six-step.coilem",
        config=config,
        submitted_request={"config": config, "project_name": "six-step"},
    )
    location = writer.complete(result)
    loaded = workspace.load_run(location.project_slug, location.run_id)

    excitation = loaded["manifest"]["provenance"]["excitation"]
    assert excitation == {
        "mode": "ideal_six_step_120",
        "current_amplitude_A": 42.0,
        "current_amplitude_convention": "plateau",
        "commutation_advance_deg": 7.5,
        "phase_connection": "wye",
    }
    pdf_text = "\n".join(
        page.extract_text() or ""
        for page in pypdf.PdfReader(location.path / "report" / "report.pdf").pages
    )
    assert "Ideal six-step (120 deg)" in pdf_text
    assert "Conducting phase current" in pdf_text
    assert "42 A plateau" in pdf_text or "42.0 A plateau" in pdf_text
    assert "7.5 deg" in pdf_text
    assert "PWM, switching ripple" in pdf_text

    csv_text = (location.path / "report" / "report.csv").read_text(encoding="utf-8")
    assert "phase_current_waveform,phase_a_A,A,42,0" in csv_text
    assert "back_emf_waveform,line_ab_V,V,15.6,0" in csv_text
    assert "setting,solve_params.commutation_advance_deg,,7.5," in csv_text
    assert "Ideal six-step is an ideal current excitation only" in csv_text

    with zipfile.ZipFile(location.path / "report" / "run-package.zip") as archive:
        packaged_result = json.loads(archive.read("result.json"))
        assert packaged_result["phase_current_waveform"] == result["phase_current_waveform"]
        packaged_request = json.loads(archive.read("request.json"))
        assert packaged_request["resolved_config"]["solve_params"]["excitation_mode"] == "ideal_six_step_120"


def test_tampered_replay_package_fails_integrity_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, location = _complete_run(tmp_path, monkeypatch)
    package_path = location.path / "report" / "run-package.zip"
    package_path.write_bytes(package_path.read_bytes() + b"tampered")

    loaded = workspace.load_run(location.project_slug, location.run_id)

    assert loaded["integrity"]["valid"] is False
    assert loaded["integrity"]["export_mismatches"] == ["package"]
    with pytest.raises(SolveWorkspaceError, match="integrity check"):
        workspace.resolve_export(
            location.project_slug,
            location.run_id,
            "package",
        )


def test_missing_or_older_run_export_fails_with_migration_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, location = _complete_run(tmp_path, monkeypatch)
    (location.path / "report" / "report.pdf").unlink()

    with pytest.raises(SolveWorkspaceError, match="integrity check"):
        workspace.resolve_export(location.project_slug, location.run_id, "pdf")

    workspace, location = _complete_run(tmp_path / "older", monkeypatch)
    manifest_path = location.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "coilem.solve_run.v1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SolveWorkspaceError, match="older manifest"):
        workspace.resolve_export(location.project_slug, location.run_id, "csv")
