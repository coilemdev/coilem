"""Torque-curve records saved before a failed direct solve was marked unavailable.

Earlier builds caught a direct solve that raised, set the point's verification
to FAIL with the exception text as its reason, added a sentence to its
status_reason and left the speed experimental, so it counted as held. Reports
read such a speed as unavailable. A completed direct solve that only missed a
comparison band keeps its result.
"""

from __future__ import annotations

import copy
import csv
import io
import json

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate

from backend.models import DriveLimits
from backend.performance_report import build_performance_csv, build_performance_pdf
from backend.public_main import app
from backend.temperature_maps import solve_temperature_bracket
from backend.thermal_rating import coupled_point, thermal_rating, verify_limiting_point
from backend.thermal_reporting import direct_solve_failed, rating_row_held, read_rating_row, thermal_csv_rows, thermal_story
from tests.test_flux_linkage_map import _config
from tests.test_performance_report import CONTEXT, _csv_rows, data  # noqa: F401 - data is a fixture
from tests.test_temperature_maps import TemperatureSolver
from tests.test_thermal_network import inputs

# The sentence each earlier build added to the status_reason when its direct solve raised.
RAISED_SENTENCES = (" Direct verification failed.", " The direct solve of this point failed.")
# What a completed direct solve that missed a band added, in the same builds.
BAND_SENTENCES = (" Direct verification failed: iron loss.",
                  " The direct solve differs from the maps beyond the registered band in: iron loss.")
COMPARED = "Direct limiting-point comparison: iron loss"
FAILURE = "Magneto2D stopped: forced legacy failure"
READABLE = f"A direct solve at this point could not run ({FAILURE}), so the value read from the maps is not reported."
COUPLED = "Coupled experimental estimate under entered heat assumptions."


def as_saved(point: dict, sentence: str, verification_reason: str) -> dict:
    """A row as an earlier build saved it: the row copied its status and reason from the checked point."""

    point = {**point, "verification_status": "FAIL", "verification_reason": verification_reason,
             "status_reason": point["status_reason"] + sentence}
    return dict(speed_rpm=point["speed_rpm"], status=point["status"], status_reason=point["status_reason"],
                limiting_constraint="voltage", point=point, user_magnet_case=None)


def test_rows_from_the_live_direct_check_and_older_builds_are_read_the_same_way(tmp_path):
    bracket = solve_temperature_bracket(_config(), 20, 80, peak_current_A=20, solve=TemperatureSolver(), store_root=tmp_path)
    cooling = inputs(housing_h_W_m2K=1000, end_space_h_W_m2K=1000, airgap_h_W_m2K=500)
    limits = DriveLimits(dc_bus_V=24, peak_current_A=20, max_speed_rpm=1000)
    unchecked = coupled_point(bracket, cooling, speed_rpm=1000, current_peak_A=2, gamma_deg=20)
    assert unchecked.status == "experimental"
    saved = unchecked.model_dump(mode="json")

    # This fake solver does not scale iron loss with speed, so the direct solve completes and misses that band.
    band_miss = unchecked.model_copy(deep=True)
    verify_limiting_point(bracket, cooling, limits, band_miss, TemperatureSolver())
    assert band_miss.verification_status == "FAIL" and band_miss.status == "experimental"
    row = dict(speed_rpm=1000.0, status=band_miss.status, status_reason=band_miss.status_reason,
               limiting_constraint="voltage", point=band_miss.model_dump(mode="json"), user_magnet_case=None)
    assert not direct_solve_failed(row["point"])
    assert read_rating_row(row) is row and rating_row_held(row)

    # A direct solve that raises in this build is saved unavailable, and reading it changes nothing.
    def broken(_config):
        raise RuntimeError(FAILURE)

    current = thermal_rating(bracket, cooling, DriveLimits(dc_bus_V=24, peak_current_A=2, continuous_current_A=1, max_speed_rpm=1000),
                             speed_samples=2, current_samples=2, angle_samples=2, direct_solve=broken)
    checked = [row.model_dump(mode="json") for row in current.points if row.point is not None]
    assert checked
    for row in checked:
        assert read_rating_row(row) is row and not rating_row_held(row)
        assert row["status_reason"] == READABLE

    # The same raise, as each earlier build saved it: experimental, with the exception as the verification reason.
    for sentence in RAISED_SENTENCES:
        legacy = as_saved(saved, sentence, FAILURE)
        before = copy.deepcopy(legacy)
        assert direct_solve_failed(legacy["point"]) and not rating_row_held(legacy)
        read = read_rating_row(legacy)
        assert legacy == before, "Reading a saved record does not change it"
        assert read["status"] == read["point"]["status"] == "unavailable"
        # The reason new runs give, so old and new rows read alike.
        assert read["status_reason"] == read["point"]["status_reason"] == checked[0]["status_reason"] == READABLE
        assert read["point"]["verification_reason"] == checked[0]["point"]["verification_reason"]
        assert read["point"]["torque_Nm"] == saved["torque_Nm"], "The map point stays on record"
        assert read_rating_row(read) is read

    # A completed solve that missed a band, as the same builds saved it, keeps its result.
    for sentence in BAND_SENTENCES:
        row = as_saved(saved, sentence, COMPARED)
        assert read_rating_row(row) is row and rating_row_held(row)
    # An exception with no text still did not reach the comparison.
    assert not rating_row_held(as_saved(saved, RAISED_SENTENCES[1], ""))


def mixed_rating() -> dict:
    def point(torque, winding, magnets, reason, verification, verification_reason):
        return dict(status="experimental", status_reason=reason, speed_rpm=0.0, torque_Nm=torque, current_peak_A=1.0,
                    winding_temperature_C=winding, magnet_temperature_C=magnets, iterations=4, temperature_residual_K=0.01,
                    verification_status=verification, verification_reason=verification_reason)

    def row(rpm, reason, value):
        return dict(speed_rpm=rpm, status="experimental", status_reason=reason, limiting_constraint="voltage",
                    point={**value, "speed_rpm": rpm}, user_magnet_case=None)

    band = COUPLED + BAND_SENTENCES[1]
    raised = COUPLED + RAISED_SENTENCES[1]
    return dict(kind="thermally_limited_rating", status="experimental", status_reason="Experimental.", inputs={}, limits={},
                control="mtpa", coupling={}, notes=[], points=[
        row(0, COUPLED, point(5.25, 61.5, 44.25, COUPLED, "PASS", "Direct limiting-point comparison: within registered bands")),
        row(500, band, point(5.678, 62.71, 44.83, band, "FAIL", COMPARED)),
        row(1000, raised, point(6.543, 64.44, 46.66, raised, "FAIL", FAILURE)),
    ])


def pdf_text(content: bytes) -> str:
    # Paragraphs wrap, so compare with single spaces.
    return " ".join(" ".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages).split())


def check_exports(rating: dict, cells: dict, root: str, extracted: str):
    """The saved failure is not held in either export; the band miss and the confirmed speed are."""

    for value in ("6.543", "64.44", "46.66"):
        assert value not in extracted, value
    for value in ("5.25", "61.5", "44.25", "5.678", "62.71", "44.83"):
        assert value in extracted, value
    assert READABLE in extracted
    assert "The direct solve of this point failed" not in extracted
    assert "differs from the maps beyond the registered band in: iron loss" in extracted

    for name in ("torque_Nm", "winding_temperature_C", "magnet_temperature_C"):
        assert cells[f"{root}[2].point.{name}"][3] in ("", None), name
        assert cells[f"{root}[2].point.{name}"][4].startswith("Not reported")
    assert str(cells[f"{root}[1].point.torque_Nm"][3]) == "5.678"
    assert cells[f"{root}[1].point.torque_Nm"][4] == ""
    assert str(cells[f"{root}[2].point.current_peak_A"][3]) in ("1.0", "1")
    # Read as unavailable, with the saved value kept beside it.
    for path in (f"{root}[2].status", f"{root}[2].point.status"):
        assert cells[path][3] == "unavailable"
        assert cells[path][4].startswith("Read as unavailable") and cells[path][4].endswith("experimental")
    assert cells[f"{root}[2].status_reason"][3] == READABLE
    assert cells[f"{root}[2].status_reason"][4].endswith(rating["points"][2]["status_reason"])
    assert cells[f"{root}[2].point.verification_status"][3] == "FAIL" and cells[f"{root}[2].point.verification_status"][4] == ""
    assert (cells[f"{root}[1].status"][3], cells[f"{root}[1].status"][4]) == ("experimental", "")


def test_a_saved_failure_is_left_out_of_the_thermal_reports():
    rating = mixed_rating()
    before = copy.deepcopy(rating)
    output = io.BytesIO()
    SimpleDocTemplate(output, pagesize=A4).build(thermal_story(rating, rating=True))
    extracted = pdf_text(output.getvalue())
    # The performance report flattens the rating itself; the frozen record nests it under "result".
    for record, root in ((rating, "points"), ({"result": rating}, "result.points")):
        check_exports(rating, {row[1]: row for row in thermal_csv_rows(record)}, root, extracted)
    assert rating == before


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def test_a_saved_failure_is_left_out_of_the_downloaded_reports(client):
    from backend.solve_workspace import user_data_root

    rating = mixed_rating()
    identity = "e" * 32
    folder = user_data_root() / "thermal_analyses"
    folder.mkdir(parents=True, exist_ok=True)
    saved = json.dumps(dict(id=identity, kind="rating", design_name="Legacy", result=rating, inputs={}))
    (folder / f"{identity}.json").write_text(saved)
    rows = list(csv.reader(io.StringIO(client.get(f"/performance/thermal/report/{identity}/csv").text)))
    extracted = pdf_text(client.get(f"/performance/thermal/report/{identity}/pdf").content)
    check_exports(rating, {row[1]: row for row in rows}, "result.points", extracted)
    assert (folder / f"{identity}.json").read_text() == saved, "Reports read the record; they do not rewrite it"


def test_a_saved_failure_is_left_out_of_the_performance_reports(data):  # noqa: F811 - the imported fixture
    rating = mixed_rating()
    context = CONTEXT.model_copy(update={"thermal_rating": rating})
    rows = [row for row in _csv_rows(build_performance_csv(data, context)) if row and row[0] == "thermal_rating"]
    check_exports(rating, {row[1]: row for row in rows}, "points", pdf_text(build_performance_pdf(data, context)))
