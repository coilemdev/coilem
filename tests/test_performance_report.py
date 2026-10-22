"""Performance report (#142): the Torque-speed tab's results as a PDF, the performance CSV and the id/iq table."""

from __future__ import annotations

import csv
import io
import math

import pytest
from fastapi.testclient import TestClient

from backend.drive_performance import efficiency_map, torque_speed_envelope
from backend.performance_report import (
    IDIQ_STEPS,
    ReportContext,
    SolvedPoint,
    build_idiq_table_csv,
    build_performance_csv,
    build_performance_pdf,
    performance_data,
)
from backend.public_main import app
from tests.test_drive_performance import LAMBDA_PM, LIMITS, POLE_PAIRS, _map

L_D, L_Q = 0.0004, 0.0008  # an IPM: reluctance torque pulls MTPA toward negative i_d
INPUTS = {"phase_resistance_ohm": 0.05, "winding_temperature_C": 80.0, "mechanical_loss_W": 5.0}
CONTEXT = ReportContext(
    design_name="IPM <test> & co", current_unit="A rms", dc_bus_source="estimated", map_preset="preview",
    solved_point=SolvedPoint(speed_rpm=3000.0, torque_Nm=10.0, current_angle_deg=20.0),
)


@pytest.fixture(scope="module")
def data():
    return performance_data(_map(L_D, L_Q), LIMITS, **INPUTS)


def _csv_rows(content: bytes) -> list[list[str]]:
    lines = content.decode("utf-8").splitlines()
    assert lines[0] == "report_schema,coilem.performance_report.v1"
    return list(csv.reader(lines[1:]))[1:]


def _value(rows: list[list[str]], section: str, field: str) -> float:
    return float(next(row[3] for row in rows if row[0] == section and row[1] == field))


def test_the_report_carries_the_tabs_envelope_and_efficiency_map(data):
    flux_map = _map(L_D, L_Q)
    envelope = torque_speed_envelope(flux_map, LIMITS, phase_resistance_ohm=0.05, winding_temperature_C=80.0)
    efficiency = efficiency_map(
        flux_map, LIMITS, phase_resistance_ohm=0.05, winding_temperature_C=80.0, mechanical_loss_W=5.0, envelope=envelope
    )
    assert data.envelope == envelope
    assert data.efficiency == efficiency


def test_the_csv_holds_the_same_numbers(data):
    rows = _csv_rows(build_performance_csv(data, CONTEXT))
    peak = data.curve("peak")
    assert _value(rows, "result", "peak_torque") == pytest.approx(peak.torque_Nm[0], rel=1e-11)
    assert _value(rows, "result", "base_speed") == pytest.approx(peak.base_speed_rpm, rel=1e-11)
    assert _value(rows, "result", "best_efficiency") == pytest.approx(data.best_efficiency_pct, rel=1e-11)
    speeds = [float(row[3]) for row in rows if row[0] == "torque_speed_peak" and row[1] == "speed"]
    assert speeds == pytest.approx(peak.speed_rpm, rel=1e-11)
    cells = sum(value is not None for line in data.efficiency.efficiency_pct for value in line)
    assert sum(row[0] == "efficiency_map" and row[1] == "efficiency" for row in rows) == cells
    assert _value(rows, "input", "peak_current_rms") == pytest.approx(LIMITS.peak_current_A / math.sqrt(2))
    assert next(row[3] for row in rows if row[1] == "dc_bus_source") == "estimated"
    assert sum(row[0] == "map_point" and row[1] == "status" for row in rows) == len(data.flux_map.points)


def test_mtpa_follows_the_analytic_trajectory(data):
    saliency = L_Q - L_D

    def torque(current, gamma):
        i_d, i_q = -current * math.sin(math.radians(gamma)), current * math.cos(math.radians(gamma))
        return 1.5 * POLE_PAIRS * (LAMBDA_PM * i_q + (L_D - L_Q) * i_d * i_q)

    for row in data.mtpa[1:]:
        current = row.current_peak_A
        i_d = (LAMBDA_PM - math.sqrt(LAMBDA_PM**2 + 8 * saliency**2 * current**2)) / (4 * saliency)
        best = math.degrees(math.asin(-i_d / current))
        # Within 0.1% of the most torque everywhere; below the first map current the
        # torque is too flat in angle to pin the angle, above it the angle is exact.
        assert torque(current, row.gamma_deg) == pytest.approx(torque(current, best), rel=1e-3)
        if current >= data.flux_map.current_peak_A[1]:
            assert row.gamma_deg == pytest.approx(best, abs=0.1)
    assert data.mtpa[-1].current_peak_A == LIMITS.peak_current_A
    # A surface-magnet motor has no reluctance torque: MTPA stays on the q-axis.
    spm = performance_data(_map(0.0005, 0.0005), LIMITS, **INPUTS)
    assert max(abs(row.gamma_deg) for row in spm.mtpa) < 0.15


def test_inductance_rows_are_the_tabs_secant_values(data):
    assert [row.current_peak_A for row in data.inductance] == data.flux_map.current_peak_A[1:]
    for row in data.inductance:
        assert row.l_d_H == pytest.approx(L_D)
        assert row.l_q_H == pytest.approx(L_Q)


def test_the_idiq_table_covers_the_map_and_is_exact_at_its_points(data):
    largest = data.flux_map.current_peak_A[-1]
    assert all(math.hypot(row.i_d_A, row.i_q_A) <= largest * (1 + 1e-9) and row.i_d_A <= 0 <= row.i_q_A for row in data.idiq)
    # A quarter disk of the 21 x 21 grid: about pi/4 of it, each axis end included.
    assert 0.75 * IDIQ_STEPS**2 < len(data.idiq) < 0.82 * IDIQ_STEPS**2
    points = {(point.current_peak_A, point.gamma_deg): point for point in data.flux_map.points}
    on_node = [row for row in data.idiq if row.i_q_A == 0.0 and -row.i_d_A in data.flux_map.current_peak_A and row.i_d_A < 0]
    assert on_node
    for row in on_node:
        point = points[(-row.i_d_A, 90)]
        assert (row.lambda_d_Wb, row.lambda_q_Wb, row.torque_Nm) == pytest.approx(
            (point.lambda_d_Wb, point.lambda_q_Wb, point.avg_torque_Nm), abs=1e-12
        )
    lines = build_idiq_table_csv(data, CONTEXT).decode("utf-8").splitlines()
    header = next(index for index, line in enumerate(lines) if not line.startswith("#"))
    assert lines[header] == "i_d_A,i_q_A,current_peak_A,current_rms_A,gamma_deg,lambda_d_Wb,lambda_q_Wb,torque_Nm"
    assert len(lines) - header - 1 == len(data.idiq)
    assert "experimental" in "\n".join(lines[:header])


def test_the_pdf_shows_the_results_with_their_status(data):
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(build_performance_pdf(data, CONTEXT)))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    peak = data.curve("peak")
    assert f"{peak.torque_Nm[0]:.4g} N m" in text
    assert f"{data.best_efficiency_pct:.1f}%" in text
    assert "IPM <test> & co" in text and "estimated from the back EMF" in text
    assert text.count("Experimental") >= 5  # every chart carries its status
    assert "Solved point" in text and "e+0" not in text


@pytest.fixture
def client():
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        yield test_client


def _body(**context):
    return {
        "map": _map(L_D, L_Q).model_dump(mode="json"),
        "limits": LIMITS.model_dump(mode="json"),
        **INPUTS,
        "context": {"design_name": "My motor / v2", **context},
    }


@pytest.mark.parametrize(
    ("kind", "media", "filename"),
    [
        ("pdf", "application/pdf", "My-motor-v2-performance.pdf"),
        ("csv", "text/csv", "My-motor-v2-performance.csv"),
        ("idiq", "text/csv", "My-motor-v2-idiq-table.csv"),
    ],
)
def test_the_route_returns_each_download(client, kind, media, filename):
    response = client.post(f"/performance/report/{kind}", json=_body())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media)
    assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'


def test_the_route_refuses_bad_requests(client):
    assert client.post("/performance/report/xlsx", json=_body()).status_code == 422
    body = _body()
    body["limits"]["dc_bus_V"] = -5
    assert client.post("/performance/report/pdf", json=body).status_code == 422
    body = _body(current_unit="mA")
    assert client.post("/performance/report/pdf", json=body).status_code == 422
