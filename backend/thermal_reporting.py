"""Shared thermal rows for immutable run supplements and performance exports."""

from __future__ import annotations

import json
import math
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from backend.export_safety import literal_csv_cell

CALIBRATION_WARNING = "One multiplier cannot identify several uncertain heat paths; fitting does not grant qualification."
# A speed with no result keeps its map point for the record, but these values
# are what a held speed reports, so the exports leave them out.
WITHHELD_POINT_VALUES = ("torque_Nm", "winding_temperature_C", "magnet_temperature_C")
NOT_REPORTED = "Not reported: this speed has no result; its status_reason says why."
# Every saved version starts the verification_reason of a direct solve that ran
# to the comparison with these words, whether it passed or missed a band. A FAIL
# without them is a direct solve that raised. The status_reason sentence added
# for that case changed between versions, so it is not used.
DIRECT_COMPARISON = "Direct limiting-point comparison"
READ_AS_UNAVAILABLE = ("Read as unavailable: an earlier coilEM build saved this speed as a result "
                       "although its direct solve could not run. Saved value: ")


def rotor_loss_scope_note(summary: dict) -> str | None:
    """Explain the heat balance when the electromagnetic run reports rotor iron loss."""
    rotor = summary.get("rotor_iron_loss")
    watts = rotor.get("rotor_iron_loss_W") if isinstance(rotor, dict) else None
    if type(watts) in (int, float) and math.isfinite(watts):
        return f"The electromagnetic run reports {watts:g} W of rotor iron loss. The thermal heat balance excludes this component."
    return None


def direct_solve_failed(point) -> bool:
    """Whether the direct solve of this limiting point raised instead of reaching its comparison."""

    return (isinstance(point, dict) and point.get("verification_status") == "FAIL"
            and not str(point.get("verification_reason") or "").startswith(DIRECT_COMPARISON))


def read_rating_row(row):
    """A torque-curve speed as this version records it.

    Earlier builds left a speed whose direct solve raised ``experimental``,
    so it counted as held. Such a row is read as a new run saves it:
    unavailable, with the reason new runs give. Any other row is returned as is,
    including a completed direct solve that only missed a comparison band.
    """

    point = row.get("point") or {}
    if not direct_solve_failed(point) or "unavailable" in (row.get("status"), point.get("status")):
        return row
    detail = str(point.get("verification_reason") or "").strip() or "no reason was saved"
    reason = f"A direct solve at this point could not run ({detail}), so the value read from the maps is not reported."
    return {**row, "status": "unavailable", "status_reason": reason,
            "point": {**point, "status": "unavailable", "status_reason": reason,
                      "verification_reason": "Direct limiting-point solve failed: " + detail}}


def rating_row_held(row) -> bool:
    """A speed holds a torque only when neither the search nor its direct solve rejected it."""

    row = read_rating_row(row)
    point = row.get("point") or {}
    return row.get("status") != "unavailable" and point.get("status") != "unavailable" and point.get("torque_Nm") is not None


_AS_SAVED = object()  # A value the export reads as it was saved.


def _is_rating_row(value) -> bool:
    return isinstance(value, dict) and {"speed_rpm", "limiting_constraint", "point"} <= value.keys()


def thermal_csv_rows(record, prefix="thermal"):
    """Flatten every value, including node reasons, convergence and calibration."""

    units = (("_rms_A", "A rms"), ("_per_K", "1/K"), ("_ohm", "ohm"),
             ("_C", "C"), ("_K", "K"), ("_W", "W"), ("_A", "A peak"),
             ("_rpm", "rpm"), ("_Nm", "N m"), ("_V", "V peak"))

    def unit_of(path):
        return next((unit for suffix, unit in units if path.endswith(suffix)), "")

    def walk(value, path, withheld=(), saved=_AS_SAVED):
        """``withheld`` names this dict's values that are left out of the export.

        ``saved`` is the saved counterpart of a value read differently (see
        :func:`read_rating_row`); a cell that differs from it keeps the saved value as its reason.
        """
        if isinstance(value, dict):
            if _is_rating_row(value) and (read := read_rating_row(value)) is not value:
                value, saved = read, value
            rejected = _is_rating_row(value) and not rating_row_held(value)
            for key, child in sorted(value.items()):
                child_path = f"{path}.{key}" if path else key
                if key in withheld and not isinstance(child, (dict, list)):
                    yield [prefix, literal_csv_cell(child_path), unit_of(child_path), "", NOT_REPORTED]
                else:
                    yield from walk(child, child_path, WITHHELD_POINT_VALUES if rejected and key == "point" else (),
                                    saved.get(key, _AS_SAVED) if isinstance(saved, dict) else _AS_SAVED)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, f"{path}[{index}]")
        else:
            reason = CALIBRATION_WARNING if path.endswith(".calibration_multiplier") else ""
            if saved is not _AS_SAVED and saved != value:
                reason = literal_csv_cell(READ_AS_UNAVAILABLE + str(saved))
            yield [prefix, literal_csv_cell(path), unit_of(path), literal_csv_cell("" if value is None else value), reason]
    yield from walk(record, "")


def thermal_story(record, *, rating=False, figure=None, heading=None):
    """The thermal pages of a report.

    ``figure`` is drawn under the status line (the run report's part heat map).
    ``heading`` builds a section heading from its title, so the pages take the
    headings of the report they are part of.
    """
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    body.fontSize = 8
    body.leading = 11
    body.spaceBefore = 3
    styles["Heading3"].keepWithNext = True
    # The run report's heading blue, so the thermal pages read as part of it.
    for name in ("Heading2", "Heading3"):
        styles[name].textColor = colors.HexColor("#1E40AF")
    styles["Heading3"].fontName = "Helvetica-Bold"
    styles["Heading3"].fontSize = 10.5

    def text(value):
        if isinstance(value, float):
            # Four significant figures, and never an exponent for a size people read as a
            # whole number: 12,000 rpm is 12000, not 1.2e+04.
            value = f"{value:.0f}" if 1e4 <= abs(value) < 1e15 else f"{value:.4g}"
        if isinstance(value, str):
            value = value.replace("NOT_COMPARED", "Not compared")
        return Paragraph(escape(str(value if value is not None else "Unavailable")), body)

    def table(headers, rows, widths):
        result = Table([[text(cell) for cell in headers], *[[text(cell) for cell in row] for row in rows]], colWidths=widths, repeatRows=1)
        result.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#CFDCEE")),
                                   ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#1E40AF")),
                                   ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return result

    title = "Thermally limited torque" if rating else "Steady-state thermal estimate"
    opening = [heading(title) if heading else Paragraph(title, styles["Heading2"]),
               text(record.get("status", "unavailable") + ": " + record.get("status_reason", "No record"))]
    if figure is not None and not rating:
        opening += [figure, text("Each part is drawn in the colour of its estimated temperature. Parts outside this cross-section "
                                 "(end winding, housing or mount, bearings) are in the table below.")]
    # The heading stays with what it introduces.
    story = [Spacer(1, 4 * mm), KeepTogether(opening)]
    if rating:
        rows = []
        # Read each speed as this version records it, so an older record says what a new one would.
        points = [read_rating_row(row) for row in record.get("points", [])]
        for row in points:
            point = row.get("point") or {}
            # A rejected speed does not show the numbers it was rejected for; its reason follows the table.
            held = [point.get(name) for name in WITHHELD_POINT_VALUES] if rating_row_held(row) else ["-"] * 3
            rows.append([row["speed_rpm"], *held, row.get("limiting_constraint"), row.get("status"),
                         point.get("verification_status", "NOT_COMPARED")])
        story.append(table(["rpm", "N m", "Winding C", "Magnet C", "Limit", "Status", "Direct check"], rows,
                           [15*mm, 17*mm, 22*mm, 22*mm, 40*mm, 24*mm, 33*mm]))
        for row in points:
            point = row.get("point") or {}
            story.append(text(f"{row['speed_rpm']:g} rpm: {row.get('status_reason', '')} {point.get('verification_reason', '')}"))
            if row.get("user_magnet_case"):
                case = row["user_magnet_case"]
                story.append(text(f"User magnet sensitivity: {case.get('magnet_temperature_C')} C, "
                                  f"{case.get('torque_Nm')} N m; {case.get('status')}: {case.get('status_reason')}"))
    else:
        rotor = record.get("rotor_heating")
        if rotor:
            story.append(Paragraph("Rotor and magnet heating scope", styles["Heading3"]))
            story.append(text("Heat transfer only at rotor/magnets." if rotor["basis"] == "heat_transfer_only"
                              else "Heat transfer plus supplied heat at rotor/magnets."))
            story.append(text(rotor["status_reason"]))
            story.append(text(f"Additional rotor/magnet heat: {rotor['additional_heat_W']:.4g} W; "
                              f"mechanical heat assigned to rotor: {rotor['mechanical_heat_to_rotor_W']:.4g} W. "
                              "Zero additional heat means internal losses are omitted, not known to be zero. "
                              "Margins apply only to this scenario."))
        feedback = record.get("copper_feedback")
        if feedback:
            story.append(Paragraph("Copper-temperature feedback", styles["Heading3"]))
            story.append(text(f"{feedback['status']}: {feedback['status_reason']}"))
            story.append(text("These thermal losses are separate from the original EM-run loss and efficiency summary."))
            story.append(table(["Quantity", "Recorded value"], [
                ["Copper loss at 20 C (W)", feedback["reference_copper_loss_W"]],
                ["Equilibrium copper loss (W)", feedback["copper_loss_W"]],
                ["Active / end winding loss (W)", f"{feedback['copper_active_loss_W']:.4g} / {feedback['copper_end_winding_loss_W']:.4g}"],
                ["Phase current (A rms)", feedback["phase_current_rms_A"]],
                ["Effective phase resistance (ohm)", feedback["phase_resistance_ohm"]],
                ["Wire source", feedback["wire_source"]],
                ["Method", feedback["method"]],
                ["Temperature consistency residual (K)", feedback["temperature_residual_K"]],
            ], [80*mm, 93*mm]))
        elif record.get("status") == "experimental" and record.get("nodes"):
            story.append(text("Saved estimate uses fixed copper losses; recompute to include temperature feedback."))
        rows = [[name, node.get("temperature_C"), node.get("margin_K"), node.get("status"), node.get("status_reason")]
                for name, node in record.get("nodes", {}).items()]
        story.append(table(["Node", "Temp C", "Margin K", "Status", "Reason"], rows,
                           [28*mm, 20*mm, 20*mm, 25*mm, 80*mm]))
        story.append(text("Hottest material node: " + str(record.get("hottest_node"))))
        story.append(text("Zero-extra-rotor-heat sensitivity: " + json.dumps(record.get("baseline_without_extra_rotor_C"))))
    if rating:
        story.append(text("Recorded drive limits: " + json.dumps(record.get("limits", {}))))
        story.append(text("Control: " + str(record.get("control", "Unavailable"))))
        for row in record.get("points", []):
            point = row.get("point") or {}
            story.append(text(f"{row['speed_rpm']:g} rpm: {point.get('iterations', 0)} iterations; "
                              f"temperature residual {point.get('temperature_residual_K')} K; "
                              f"relaxation settings {record.get('coupling', {})}"))
    story.append(Paragraph("Cooling, limits and calibration inputs", styles["Heading3"]))
    story.append(table(["Input", "Recorded value"], [[key, (f"{value}. {CALIBRATION_WARNING}" if key == "calibration_multiplier"
        else json.dumps(value) if isinstance(value, (dict, list)) else value)]
        for key, value in record.get("inputs", {}).items()], [68*mm, 105*mm]))
    for note in record.get("notes", []):
        story.append(text(note))
    return story
