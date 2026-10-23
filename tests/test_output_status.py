"""Every 0.5.0 output says whether it is qualified or experimental, with the reason (public issue 143).

The d/q card, losses and efficiency, the iron-loss map, the torque-speed
envelope, the efficiency map, the magnet temperature derating and the phase
resistance each carry a status in the UI, the run PDF and CSV, and the
performance PDF and CSV.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pytest

from backend.loss_breakdown import operating_point_losses
from backend.magnet_temperature import magnet_temperature_record
from backend.models.performance import (
    DQ_FLUX_LINKAGE_STATUS_REASON,
    MAGNET_TEMPERATURE_STATUS_REASON,
    PHASE_RESISTANCE_STATUS_REASON,
    DqFluxLinkage,
)
from backend.models.result import SolveMetadata
from backend.performance_report import ReportContext, build_performance_csv, build_performance_pdf, performance_data
from backend.public_report import build_public_run_csv, build_public_run_pdf
from tests.test_drive_performance import LIMITS, _map
from tests.test_loss_breakdown import RAW, _config, _iron, _stored_result
from tests.test_magnet_temperature import _config as _magnet_config

pypdf = pytest.importorskip("pypdf")

REASONS = {
    "DQ_FLUX_LINKAGE_STATUS_REASON": DQ_FLUX_LINKAGE_STATUS_REASON,
    "PHASE_RESISTANCE_STATUS_REASON": PHASE_RESISTANCE_STATUS_REASON,
    "MAGNET_TEMPERATURE_STATUS_REASON": MAGNET_TEMPERATURE_STATUS_REASON,
}


def _pdf_text(pdf: bytes) -> str:
    return " ".join(" ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages).split())


def _status_rows(content: bytes) -> dict[str, str]:
    rows = csv.reader(io.StringIO(content.decode("utf-8")))
    return {row[1]: row[3] for row in rows if len(row) >= 4 and row[0] == "status"}


@pytest.mark.parametrize("reason", REASONS.values())
def test_reasons_print_in_a_report_and_stay_inside_the_public_boundary(reason: str) -> None:
    assert reason.isascii(), "the PDF's standard fonts have no Greek letters"
    assert "femm" not in reason.lower() and "thermal" not in reason.lower()


def test_records_without_a_benchmark_gate_say_they_are_experimental() -> None:
    winding, _ = operating_point_losses(_config(current_amplitude_A=10.0, rated_speed_rpm=3000), 2.0, _iron())
    assert (winding.status, winding.status_reason) == ("experimental", PHASE_RESISTANCE_STATUS_REASON)
    dq = DqFluxLinkage(i_d_A=0.0, i_q_A=10.0, lambda_d_Wb=0.01, lambda_q_Wb=0.001, torque_dq_Nm=0.3)
    assert (dq.status, dq.status_reason) == ("experimental", DQ_FLUX_LINKAGE_STATUS_REASON)

    record = magnet_temperature_record(_magnet_config(100.0))
    assert record["magnet_temperature_status"] == "experimental"
    assert record["magnet_temperature_status_reason"] == MAGNET_TEMPERATURE_STATUS_REASON
    metadata = SolveMetadata(solver_name="magneto2d", mesh_element_count=100, rotor_positions=2, timestamp="2026-10-22T00:00:00Z", **record)
    assert metadata.magnet_temperature_status == "experimental"


def _derated_result(*, with_statuses: bool) -> dict:
    result = _stored_result()
    record = magnet_temperature_record(_magnet_config(100.0))
    if not with_statuses:
        record = {key: value for key, value in record.items() if "status" not in key}
    result["solve_metadata"].update(record)
    if with_statuses:
        result["summary"]["dq_flux_linkage"].update(status="experimental", status_reason=DQ_FLUX_LINKAGE_STATUS_REASON)
    return result


@pytest.mark.parametrize("with_statuses", [True, False], ids=["recorded", "stored-before-statuses"])
def test_the_run_pdf_and_csv_give_each_output_its_status_and_reason(with_statuses: bool) -> None:
    result = _derated_result(with_statuses=with_statuses)
    arguments = {"project": RAW, "request": {"resolved_config": RAW}, "result": result, "material": {}, "manifest": {}}

    status = _status_rows(build_public_run_csv(**arguments))
    loss = result["summary"]["loss_breakdown"]
    assert status == {
        "dq_flux_linkage": "experimental", "dq_flux_linkage_reason": DQ_FLUX_LINKAGE_STATUS_REASON,
        "phase_resistance": "experimental", "phase_resistance_reason": PHASE_RESISTANCE_STATUS_REASON,
        "iron_loss": "experimental", "iron_loss_reason": "Grade limits.",
        "efficiency": "experimental", "efficiency_reason": loss["efficiency_status_reason"],
        "magnet_temperature": "experimental", "magnet_temperature_reason": MAGNET_TEMPERATURE_STATUS_REASON,
    }

    text = _pdf_text(build_public_run_pdf(**arguments))
    assert "Status of the performance outputs" in text
    for output in (
        "d/q flux linkage and inductances: experimental.",
        "Phase resistance and copper loss: experimental.",
        "Iron loss and its density map: experimental.",
        "Efficiency: experimental.",
    ):
        assert output in text, output
    assert "100 C, experimental derating" in text
    for reason in REASONS.values():
        assert reason in text


def test_a_run_at_the_catalogue_20C_has_no_derating_status() -> None:
    # A 20 °C run records its magnet values but derates nothing, as the Solve page shows.
    result = _stored_result()
    result["solve_metadata"].update(magnet_temperature_record(_magnet_config(20.0)))
    arguments = {"project": RAW, "request": {"resolved_config": RAW}, "result": result, "material": {}, "manifest": {}}

    assert "magnet_temperature" not in _status_rows(build_public_run_csv(**arguments))
    text = _pdf_text(build_public_run_pdf(**arguments))
    assert "20 C, catalogue values" in text
    assert "Magnet temperature derating" not in text

def test_a_run_without_performance_outputs_has_no_status_section() -> None:
    result = _stored_result()
    for key in ("dq_flux_linkage", "winding_resistance", "loss_breakdown", "iron_loss"):
        result["summary"].pop(key)
    arguments = {"project": RAW, "request": {"resolved_config": RAW}, "result": result, "material": {}, "manifest": {}}
    assert _status_rows(build_public_run_csv(**arguments)) == {}
    assert "Status of the performance outputs" not in _pdf_text(build_public_run_pdf(**arguments))


@pytest.mark.parametrize("derated", [True, False])
def test_the_performance_report_lists_every_output_with_its_status(derated: bool) -> None:
    data = performance_data(_map(0.0004, 0.0008), LIMITS, phase_resistance_ohm=0.05, winding_temperature_C=80.0, mechanical_loss_W=0.0)
    context = ReportContext(design_name="IPM", magnet_temperature_derated=derated)

    status = _status_rows(build_performance_csv(data, context))
    expected = {
        "torque_speed": data.envelope.status, "torque_speed_reason": data.envelope.status_reason,
        "efficiency_map": data.efficiency.status, "efficiency_map_reason": data.efficiency.status_reason,
        "dq_flux_linkage": "experimental", "dq_flux_linkage_reason": DQ_FLUX_LINKAGE_STATUS_REASON,
        "phase_resistance": "experimental", "phase_resistance_reason": PHASE_RESISTANCE_STATUS_REASON,
    }
    if derated:
        expected.update(magnet_temperature="experimental", magnet_temperature_reason=MAGNET_TEMPERATURE_STATUS_REASON)
    assert status == expected

    text = _pdf_text(build_performance_pdf(data, context))
    for output in (
        "Torque-speed envelope", "Efficiency map", "Map flux linkage, MTPA trajectory and inductances", "Phase resistance and copper loss",
    ):
        assert output in text, output
    assert ("Magnet temperature derating" in text) is derated
    assert f"Experimental: {DQ_FLUX_LINKAGE_STATUS_REASON}" in text
    assert "0.05 ohm at 80 degC, experimental" in text


def test_the_app_mirrors_the_status_reasons() -> None:
    source = Path("frontend/src/public/outputStatus.ts").read_text(encoding="utf-8")
    for name, reason in REASONS.items():
        match = re.search(rf"export const {name} = ((?:\s*\+?\s*(?:'[^']*'|\"[^\"]*\"))+);", source)
        assert match, name
        parts = re.findall(r"'([^']*)'|\"([^\"]*)\"", match.group(1))
        assert "".join(single or double for single, double in parts) == reason, name
