"""Public single-run report and replay package contracts."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from backend.models import MotorConfig
from backend.public_report import (
    _angle_axis_end,
    _design_setting_groups,
    _electrical_angle_ticks,
    _flatten,
    _plain,
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
        "Resolved settings for this design",
        "Every stored setting, including those left out here, is in the setting rows of",
        manifest["bindings"]["resolved_request_sha256"],
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
    # The CSV keeps every resolved setting, also those the PDF leaves out.
    assert [row[1:4] for row in rows if row[0] == "setting"] == [
        [field, "", _plain(value)] for field, value in _flatten(request["resolved_config"])
    ]
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

    # The package is not stored with the run (it repeated every artifact); it
    # is built for the download, outside the run budget, and always the same.
    assert manifest["exports"]["package_sha256"] is None
    assert manifest["exports"]["package_mode"] == "on_demand"
    assert not (location.path / "report" / "run-package.zip").exists()
    assert workspace.is_export_scratch(package_path)
    assert not workspace.is_export_scratch(location.path)
    rebuilt = workspace.resolve_export(location.project_slug, location.run_id, "package")
    assert rebuilt != package_path
    assert rebuilt.read_bytes() == package_path.read_bytes()


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

    package_path = workspace.resolve_export(location.project_slug, location.run_id, "package")
    with zipfile.ZipFile(package_path) as archive:
        packaged_result = json.loads(archive.read("result.json"))
        assert packaged_result["phase_current_waveform"] == result["phase_current_waveform"]
        packaged_request = json.loads(archive.read("request.json"))
        assert packaged_request["resolved_config"]["solve_params"]["excitation_mode"] == "ideal_six_step_120"


def test_tampered_run_builds_no_replay_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, location = _complete_run(tmp_path, monkeypatch)
    pdf_path = location.path / "report" / "report.pdf"
    pdf_path.write_bytes(pdf_path.read_bytes() + b"tampered")

    loaded = workspace.load_run(location.project_slug, location.run_id)

    assert loaded["integrity"]["valid"] is False
    assert loaded["integrity"]["export_mismatches"] == ["pdf"]
    with pytest.raises(SolveWorkspaceError, match="integrity check"):
        workspace.resolve_export(
            location.project_slug,
            location.run_id,
            "package",
        )
    assert not list(workspace.export_scratch_root.glob("*.zip"))


def test_stored_replay_package_of_an_older_run_is_still_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runs saved before packages were built on download keep their stored zip."""

    workspace, location = _complete_run(tmp_path, monkeypatch)
    manifest_path = location.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["exports"]["package_mode"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package_path = location.path / "report" / "run-package.zip"
    write_replayable_run_package(location.path, package_path, completed_at=manifest["completed_at"])
    manifest["exports"]["package_sha256"] = hashlib.sha256(package_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = workspace.load_run(location.project_slug, location.run_id)
    assert loaded["integrity"]["valid"] is True
    assert workspace.resolve_export(location.project_slug, location.run_id, "package") == package_path.resolve()

    package_path.write_bytes(package_path.read_bytes() + b"tampered")
    loaded = workspace.load_run(location.project_slug, location.run_id)
    assert loaded["integrity"]["valid"] is False
    assert loaded["integrity"]["export_mismatches"] == ["package"]
    with pytest.raises(SolveWorkspaceError, match="integrity check"):
        workspace.resolve_export(location.project_slug, location.run_id, "package")


def test_package_download_is_built_for_the_request_and_removed_after(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from backend.public_main import app

    workspace, location = _complete_run(tmp_path, monkeypatch)
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "data"))
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.get(f"/runs/{location.project_slug}/{location.run_id}/package.zip")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "result.json" in archive.namelist()
    assert not list(workspace.export_scratch_root.glob("*.zip"))
    assert not (location.path / "report" / "run-package.zip").exists()


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


# The PDF lists the settings that define the design (#52); the CSV and
# request.json keep every resolved value.
EXAMPLES = Path("frontend/src/public/examples")
_POCKET_SETTINGS = {
    "flat_buried": {"Flat buried magnet shape", "Bridge thickness", "Side bridge thickness"},
    "v_shape": {"V angle", "V depth", "Inner web thickness", "Outer bridge thickness"},
}


def _resolved(raw: dict) -> dict:
    """A resolved_config as the solve route stores it."""

    return MotorConfig.model_validate(raw).model_dump(mode="json")


def _setting_labels(config: dict) -> dict[str, dict[str, str]]:
    return {title: dict(entries) for title, entries in _design_setting_groups(config)}


def _settings_page_text(config: dict) -> str:
    """The text of the PDF page holding the settings section, which must fit on it."""

    pdf = build_public_run_pdf(
        project={"topology": config["topology"]},
        request={"resolved_config": config},
        result=_result(),
        material={},
        manifest={"bindings": {"resolved_request_sha256": "f" * 64}},
    )
    pages = [page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages]
    first = next(index for index, text in enumerate(pages) if "Resolved settings for this design" in text)
    last = next(index for index, text in enumerate(pages) if "Every stored setting" in text)
    assert first == last, "the settings section fits on one page"
    return pages[first]


def _bundled_configs() -> dict[str, dict]:
    configs = {"spm_4p12s_simple": _resolved(CONFIG)}
    for path in sorted(EXAMPLES.glob("*.openem")):
        configs[path.stem] = _resolved(json.loads(path.read_text(encoding="utf-8")))
    return configs


@pytest.mark.parametrize("name", sorted(_bundled_configs()))
def test_pdf_settings_list_only_the_settings_of_the_designs_topology(name: str) -> None:
    config = _bundled_configs()[name]
    groups = _setting_labels(config)
    labels = {label for entries in groups.values() for label in entries}
    values = [value for entries in groups.values() for value in entries.values()]
    rotor_type = config["rotor"]["ipm_topology"] if config["topology"] == "IPM" else None

    assert list(groups) == ["Stator", "Rotor", "Winding", "Materials", "Operating point", "Solve plan"] + (
        ["Analyses"] if config["solve_options"] else []
    )
    assert all(value.strip() and value not in {"[]", "{}"} for value in values), "no empty values"
    assert not any(label.startswith("HoleM50") for label in labels), "HoleM50 fields only for a HoleM50 rotor"
    assert not labels & {"Flux barrier count", "Barrier widths", "Magneto2d workers", "Stream noload field lines"}
    for pocket_type, pocket_labels in _POCKET_SETTINGS.items():
        if pocket_type == rotor_type:
            assert pocket_labels <= set(groups["Rotor"])
        else:
            assert not pocket_labels & set(groups["Rotor"]), f"{pocket_type} fields on a {rotor_type or 'SPM'} rotor"
    if config["topology"] == "SPM":
        assert "IPM rotor type" not in groups["Rotor"] and "Pocket clearance" not in groups["Rotor"]
    assert ("Tooth shoe height" in groups["Stator"]) == bool(config["stator"]["tooth_shoe_enabled"])
    assert ("Coil span" in groups["Winding"]) == (config["winding"]["coil_span"] is not None)
    assert groups["Operating point"]["Phase current"] == (
        f"{_plain(config['solve_params']['current_amplitude_A'])} A "
        f"{config['solve_params']['current_amplitude_convention']}"
    )

    page = _settings_page_text(config)
    assert "f" * 64 in page
    assert "holem50" not in page.lower()


def test_pdf_settings_follow_rotor_type_plan_and_tooth_shoe() -> None:
    raw = deepcopy(CONFIG)
    raw["topology"] = "IPM"
    raw["rotor"]["ipm_topology"] = "pyleecan_holem50"
    raw["stator"]["tooth_shoe_enabled"] = False
    raw["solve_params"].update(solve_quality="custom", rotor_step_deg=2.5, rotor_sweep_range_deg=120, magneto2d_workers=4)
    config = _resolved(raw)
    groups = _setting_labels(config)

    holem50 = {f"HoleM50 W{index}" for index in range(5)} | {f"HoleM50 H{index}" for index in range(5)}
    assert holem50 <= set(groups["Rotor"])
    assert groups["Rotor"]["HoleM50 W0"] == f"{_plain(config['rotor']['holem50_w0_mm'])} mm"
    assert groups["Rotor"]["IPM rotor type"] == "pyleecan_holem50"
    assert not set().union(*_POCKET_SETTINGS.values()) & set(groups["Rotor"])
    assert "Tooth shoe height" not in groups["Stator"] and groups["Stator"]["Tooth shoe enabled"] == "false"
    assert groups["Solve plan"]["Rotor step"] == "2.5 deg"
    assert groups["Solve plan"]["Rotor sweep range"] == "120 deg"
    assert "Magneto2d workers" not in groups["Solve plan"]
    assert "HoleM50 W0" in _settings_page_text(config)

    # Every preset sets its own step; Preview uses the stored sweep range, capped
    # at 60 deg (SolveParams.effective_native_loaded_sweep_range_deg).
    for plan in ("quick", "standard", "fine"):
        raw = deepcopy(CONFIG)
        raw["solve_params"].update(solve_quality=plan, rotor_sweep_range_deg=45)
        plan_settings = _setting_labels(_resolved(raw))["Solve plan"]
        assert "Rotor step" not in plan_settings, plan
        if plan == "quick":
            assert plan_settings["Rotor sweep range"] == "45 deg", "a Preview run solved this 45 deg window"
        else:
            assert "Rotor sweep range" not in plan_settings, plan
    assert "settings the solve plan does not use" in _settings_page_text(_resolved(CONFIG))


def test_pdf_settings_follow_the_excitation() -> None:
    sinusoidal = _setting_labels(_resolved(CONFIG))["Operating point"]
    assert "Current angle" in sinusoidal
    assert not {"Commutation advance", "Phase connection"} & set(sinusoidal)

    raw = deepcopy(CONFIG)
    raw["solve_params"].update(excitation_mode="ideal_six_step_120", current_amplitude_convention="plateau")
    six_step = _setting_labels(_resolved(raw))["Operating point"]
    assert {"Commutation advance", "Phase connection"} <= set(six_step)
    assert "Current angle" not in six_step
    assert six_step["Phase current"].endswith(" A plateau")


def test_pdf_settings_keep_fields_this_report_does_not_know_yet() -> None:
    config = _resolved(CONFIG)
    config["rotor"]["sleeve_thickness_mm"] = 0.5
    config["solve_params"]["mesh_smoothing_passes"] = 3
    config["solve_params"]["nested"] = {"left": "to the CSV"}
    groups = _setting_labels(config)

    assert groups["Rotor"]["Sleeve thickness"] == "0.5 mm"
    assert groups["Solve plan"]["Mesh smoothing passes"] == "3"
    assert "Nested" not in groups["Solve plan"]


def test_pdf_first_page_holds_the_whole_provenance_table() -> None:
    """Owner QA of #61: the provenance table split across pages 1 and 2."""

    config = _resolved(CONFIG)
    manifest = {
        "run_id": "20261013t000000000000z-qa",
        "project_name": "A project name long enough to take a full line in the header table",
        "provenance": {
            "solver_name": "magneto2d-rust-0.3.3",
            "application_version": "0.3.0",
            "application_commit": "a" * 40,
            # An installed package records three more provenance rows.
            "build": {
                "installation": "package",
                "magneto2d_version": "0.3.3",
                "magneto2d_target": "aarch64-apple-darwin",
                "magneto2d_sha256": "b" * 64,
                "ui_bundle_sha256": "c" * 64,
            },
            "platform": {"machine": "arm64", "python": "3.12.13", "system": "Darwin"},
            "qualification": {
                "status": "experimental",
                "reason": "V-shape IPM rotors: two of the six benchmark fixtures fail their torque gates, so results are experimental.",
                "basis": "coilEM benchmark report v1.1",
            },
        },
        "bindings": {"result_sha256": "d" * 64, "resolved_request_sha256": "e" * 64},
    }
    pdf = build_public_run_pdf(
        project={"topology": "SPM"}, request={"resolved_config": config}, result=_result(), material={}, manifest=manifest,
    )
    first_page = pypdf.PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or ""
    for row in ("Solver and build provenance", "UI bundle SHA-256", "Platform", "Result SHA-256", "Resolved request SHA-256", "e" * 64):
        assert row in first_page, row
    assert "Torque method requested" in first_page


def test_pdf_plot_angle_axis_matches_the_apps_steps() -> None:
    assert _electrical_angle_ticks(0, 360) == [0, 45, 90, 135, 180, 225, 270, 315, 360]
    assert _electrical_angle_ticks(0, 60) == [0, 7.5, 15, 22.5, 30, 37.5, 45, 52.5, 60]
    assert _electrical_angle_ticks(0, 45) == [0, 7.5, 15, 22.5, 30, 37.5, 45]
    assert _electrical_angle_ticks(30, 30) == [30]
    # A full cycle sampled from 0 ends at 360; a partial window at its last angle.
    assert _angle_axis_end([index * 7.5 for index in range(48)]) == 360.0
    assert _angle_axis_end([index * 3.75 for index in range(13)]) == 45.0
    assert _angle_axis_end([0.0, 30.0, 60.0, 90.0]) == 90.0


@pytest.mark.parametrize("case_id,temperature", [
    ("prius-2004-tutorial-bemf-v1", 20), ("prius-2004-loaded-torque-v1", 60),
])
def test_reference_export_keeps_case_temperature_and_angle_convention(case_id, temperature):
    from backend.reference_models.prius import case_config

    groups = dict(_design_setting_groups(case_config(case_id)))
    reference = dict(groups["Published software reference"])
    assert reference["Case ID"] == case_id
    assert reference["Current angle convention"] == "Pyleecan d-axis Phi0"
    assert reference["Magnet temperature"] == f"{temperature} C"


def test_torque_constant_states_its_current_convention_in_pdf_and_csv() -> None:
    """#153: the summary stores Kt per peak ampere; Results shows it per rms ampere."""

    result = _result()
    result["summary"]["Ke_Vs_per_rad_mech"] = 0.2
    result["summary"]["lambda_pm_Wb"] = 0.05
    arguments = {"project": {}, "request": {}, "result": result, "material": {}, "manifest": {}}
    rows = list(csv.reader(io.StringIO(build_public_run_csv(**arguments).decode("utf-8"))))
    summary = {row[1]: row for row in rows if row[0] == "summary"}
    assert summary["Kt_Nm_per_A"][2:4] == ["N m/A peak", "0.425"]
    assert summary["Kt_Nm_per_A_rms"][2] == "N m/A rms"
    assert float(summary["Kt_Nm_per_A_rms"][3]) == pytest.approx(0.425 * 2**0.5)
    assert summary["Ke_Vs_per_rad_mech"][2] == "V s/rad (phase peak per mech rad/s)"
    assert summary["lambda_pm_Wb"][2] == "Wb peak"

    pdf = build_public_run_pdf(**arguments)
    text = " ".join(" ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages).split())
    assert "Torque constant" in text
    assert f"{_plain(0.425 * 2**0.5)} N m/A rms" in text
    assert "0.425 N m/A peak" in text
