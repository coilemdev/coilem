"""The thermal network against a published set of motor temperature measurements.

One source so far: ORNL/TM-2005/33, which loaded the 2004 Prius traction motor
at 900 rpm until its end turns levelled off, at four coolant temperatures, and
reports the losses, the casing temperature beside each of three end-turn
thermocouples, and the temperatures those thermocouples read. It also reports
what its own three-dimensional conduction model predicted from the same inputs.

The network is given the report's inputs and nothing from a coilEM solve:

* the published copper, stator iron, rotor iron and magnet losses;
* the published conductivities;
* the casing temperature beside the thermocouple as the housing temperature,
  which is how the report set up its own model;
* the report's fitted oil coefficient as the end-space coefficient.

Three inputs the network needs are not in the report as numbers, and each is
handled in the open:

* **Stator-to-housing contact.** The report gives a layer conductivity with no
  thickness. The contact resistance is set once, so the stator's outer face
  matches the report's own model there in the one case it describes part by
  part, then held for all twelve points.
* **Slot liner thickness.** Assumed, with a range.
* **Slot conductivity.** The report gives a range for the mixture between the
  wire bundles; the network takes one value for the whole slot, so the range
  is carried through.

What this cannot show: the network has no oil. The report's oil sits at
114-131 C and cools the end turns; the network's end-space air only reaches the
casing. So this is a check of the conduction path from the winding to a housing
of known temperature in a real machine, with real losses.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from backend.loss_breakdown import operating_point_losses
from backend.models import IronLoss, MotorConfig
from backend.models.thermal import ThermalInputs
from backend.public_policy import parse_public_solve_request
from backend.thermal_network import build_network, solve_network

ROOT = Path(__file__).resolve().parents[2]
DATA = "benchmarks/thermal-v0.6/published/ornl-tm-2005-33.json"
FIXTURE = "frontend/src/public/examples/prius-2004-loaded-torque-v1.coilem"
SPEED_RPM = 900.0
# Not in the report. A slot liner in a machine of this class is a few tenths of a millimetre.
LINER_MM = {"low": 0.1, "base": 0.25, "high": 0.4}
# Never the exit for any real heat here: the report's model leaves the bearings out.
NO_PATH_K_W = 1e4
# Large enough that the housing node sits at the measured casing temperature.
HELD_W_M2K = 1e7
PARTS = ("stator_outer", "yoke", "tooth_yoke_interface", "teeth", "stator_bore", "winding", "end_winding", "rotor", "magnets", "end_air")


@lru_cache(maxsize=1)
def published() -> dict:
    return json.loads((ROOT / DATA).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def design() -> MotorConfig:
    config, _, _ = parse_public_solve_request(json.loads((ROOT / FIXTURE).read_text(encoding="utf-8")))
    return config


def slot_conductivity(level: str) -> float:
    """The report's mixture range: its ends, and their geometric mean as the base value."""

    low, high = published()["conductivity_W_mK"]["slot_mixture"]
    # A more conductive slot gives the cooler ("low") prediction.
    return {"low": high, "base": math.sqrt(low * high), "high": low}[level]


def heat_records(point: dict, *, copper_W: float | None = None, stator_iron_W: float | None = None):
    """The winding and loss records for one published point, carrying the published losses."""

    config = design()
    copper = point["copper_W"] if copper_W is None else copper_W
    iron_W = point["stator_iron_W"] if stator_iron_W is None else stator_iron_W
    sized = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={
        "current_amplitude_A": point["current_A_rms"] * math.sqrt(2), "current_amplitude_convention": "peak",
        "rated_speed_rpm": SPEED_RPM, "mechanical_loss_W": 0.0,
    })})
    iron = IronLoss(
        status="experimental", steel="M350-50A", electrical_frequency_Hz=SPEED_RPM / 60 * config.rotor.pole_count / 2,
        iron_loss_W=iron_W, iron_hysteresis_loss_W=0.5 * iron_W, iron_eddy_loss_W=0.5 * iron_W,
        stator_iron_mass_kg=1, validated_max_frequency_Hz=1000, validated_max_flux_density_T=1.5,
    )
    winding, losses = operating_point_losses(sized, point["torque_Nm"], iron)
    active = winding.active_fraction
    losses = losses.model_copy(update={
        "copper_loss_W": copper, "copper_active_loss_W": copper * active, "copper_end_winding_loss_W": copper * (1 - active),
        "iron_loss_W": iron_W, "mechanical_loss_W": 0.0,
    })
    return sized, winding, losses, iron


def report_inputs(point: dict, casing_C: float, *, contact_m2K_W: float, level: str = "base", **changes) -> ThermalInputs:
    """The published inputs as network inputs. ``changes`` replaces single inputs for a sensitivity row."""

    data = published()
    k = data["conductivity_W_mK"]
    config = design()
    gap_m = (config.stator.ID_mm - config.rotor.OD_mm) / 2 * 1e-3
    rotor_heat = point["rotor_iron_W"] + point["magnet_W"]
    values = {
        "cooling": "liquid_jacket", "ambient_C": casing_C, "housing_h_W_m2K": HELD_W_M2K,
        "end_space_h_W_m2K": data["oil_to_end_turn_W_m2K"],
        # The report models the oil-filled gap as a solid of this conductivity. The network
        # takes one coefficient per gap surface, two in series across the gap.
        "airgap_h_W_m2K": 2 * k["gap_mixture"] / gap_m,
        "coefficient_source": "ORNL/TM-2005/33: measured casing temperature as the boundary, the report's oil coefficient and gap conductivity",
        "housing_thickness_mm": 3, "slot_liner_mm": LINER_MM[level], "contact_m2K_W": contact_m2K_W,
        "bearing_to_housing_K_W": NO_PATH_K_W, "rotor_to_bearing_K_W": NO_PATH_K_W,
        "steel_k_W_mK": k["iron_radial"], "conductor_k_W_mK": k["copper"], "magnet_k_W_mK": k["magnet"],
        "liner_k_W_mK": k["slot_insulation_and_wedge"],
        "slot_k_model": "user", "slot_k_W_mK": slot_conductivity(level), "slot_k_source": "ORNL/TM-2005/33 Table 15 mixture range",
        "extra_rotor_heat_W": rotor_heat, "extra_rotor_heat_to_magnets_fraction": point["magnet_W"] / rotor_heat,
        "insulation_class": "H", "hotspot_allowance_K": 0,
    }
    values.update(changes)
    if values.get("slot_k_model") != "user":
        values.pop("slot_k_W_mK", None)
        values.pop("slot_k_source", None)
    return ThermalInputs.model_validate(values)


def part_temperatures(point: dict, casing_C: float, *, contact_m2K_W: float, level: str = "base",
                      copper_W: float | None = None, stator_iron_W: float | None = None, **changes) -> dict[str, float]:
    """Every network temperature for one point, surface ports included."""

    sized, winding, losses, iron = heat_records(point, copper_W=copper_W, stator_iron_W=stator_iron_W)
    inputs = report_inputs(point, casing_C, contact_m2K_W=contact_m2K_W, level=level, **changes)
    temperatures, _, _ = solve_network(build_network(sized, inputs, winding, losses, iron))
    return temperatures


def _point(coolant_C: float) -> dict:
    return next(point for point in published()["points"] if point["coolant_C"] == coolant_C)


@lru_cache(maxsize=1)
def fitted_contact() -> float:
    """The contact resistance that puts the stator's outer face where the report's model has it.

    The report describes one case part by part. Its stator iron is coolest at
    the outside, next to the casing; that temperature and the casing's fix the
    drop across the contact for the heat flowing through it.
    """

    parts = published()["source_model_parts"]
    point = _point(parts["coolant_C"])
    casing = point["thermocouples"][parts["thermocouple"]]["casing_C"]
    target = parts["stator_iron_C"][0]
    low, high = 1e-6, 1e-1
    for _ in range(60):
        middle = math.sqrt(low * high)
        if part_temperatures(point, casing, contact_m2K_W=middle)["stator_outer"] < target:
            low = middle
        else:
            high = middle
    return math.sqrt(low * high)


def resistance_note() -> dict:
    """coilEM's winding resistance for this design beside what the published copper loss implies.

    Not a thermal result. It is recorded because the two disagree by more than
    the temperature rise can explain, which matters to anyone who feeds this
    design's own copper loss into the estimate.
    """

    point = published()["points"][0]
    _, winding, _, _ = heat_records(point)
    measured = sum(couple["measured_C"] for couple in point["thermocouples"].values()) / len(point["thermocouples"])
    hot = winding.phase_resistance_20C_ohm * (1 + winding.temperature_coefficient_per_K * (measured - 20))
    current = point["current_A_rms"]
    implied = [p["copper_W"] / (3 * p["current_A_rms"] ** 2) for p in published()["points"]]
    return {
        "coolant_C": point["coolant_C"], "current_A_rms": current, "end_turn_C": measured,
        "coilem_phase_resistance_20C_ohm": winding.phase_resistance_20C_ohm,
        "coilem_phase_resistance_at_end_turn_temperature_ohm": hot,
        "coilem_copper_loss_W": 3 * current**2 * hot,
        "published_copper_loss_W": point["copper_W"], "published_total_loss_W": point["total_loss_W"],
        "published_implied_phase_resistance_ohm": sum(implied) / len(implied),
    }


def _stats(values: list[float]) -> dict:
    return {"mean": sum(values) / len(values), "min": min(values), "max": max(values)}


def compare() -> dict:
    data = published()
    contact = fitted_contact()
    rows, means = [], []
    for point in data["points"]:
        mean_row = {"coolant_C": point["coolant_C"], "casing_C": 0.0, "measured_C": 0.0, "source_model_mid_C": 0.0, "network_C": 0.0}
        for name, couple in point["thermocouples"].items():
            casing = couple["casing_C"]
            predicted = {level: part_temperatures(point, casing, contact_m2K_W=contact, level=level) for level in LINER_MM}
            network = predicted["base"]["end_winding"]
            rows.append({
                "coolant_C": point["coolant_C"], "thermocouple": name, "casing_C": casing, "oil_C": point["oil_C"],
                "measured_C": couple["measured_C"], "source_model_C": couple["source_model_C"],
                "network_C": network, "network_range_C": [predicted["low"]["end_winding"], predicted["high"]["end_winding"]],
                "network_slot_winding_C": predicted["base"]["winding"], "network_end_space_C": predicted["base"]["end_air"],
                "difference_K": network - couple["measured_C"],
                "rise_ratio": (network - casing) / (couple["measured_C"] - casing),
                "inside_network_range": predicted["low"]["end_winding"] <= couple["measured_C"] <= predicted["high"]["end_winding"],
            })
            share = 1 / len(point["thermocouples"])
            mean_row["casing_C"] += share * casing
            mean_row["measured_C"] += share * couple["measured_C"]
            mean_row["source_model_mid_C"] += share * sum(couple["source_model_C"]) / 2
            mean_row["network_C"] += share * network
        mean_row["difference_K"] = mean_row["network_C"] - mean_row["measured_C"]
        mean_row["rise_ratio"] = (mean_row["network_C"] - mean_row["casing_C"]) / (mean_row["measured_C"] - mean_row["casing_C"])
        means.append(mean_row)

    parts = data["source_model_parts"]
    detail_point = _point(parts["coolant_C"])
    detail_casing = detail_point["thermocouples"][parts["thermocouple"]]["casing_C"]
    detail = part_temperatures(detail_point, detail_casing, contact_m2K_W=contact)

    reference_point = data["points"][0]
    reference_casing = sum(c["casing_C"] for c in reference_point["thermocouples"].values()) / len(reference_point["thermocouples"])
    reference = part_temperatures(reference_point, reference_casing, contact_m2K_W=contact)["end_winding"]
    moved = 200.0
    sensitivity = []
    for label, changes in (
        ("Contact resistance halved", {"contact_m2K_W": contact / 2}),
        ("Contact resistance doubled", {"contact_m2K_W": contact * 2}),
        ("Tool's starter contact resistance, 0.001 m2K/W", {"contact_m2K_W": 0.001}),
        ("Slot liner 0.1 mm", {"slot_liner_mm": 0.1}),
        ("Slot liner 0.4 mm", {"slot_liner_mm": 0.4}),
        ("Slot conductivity at the report's upper value", {"slot_k_W_mK": data["conductivity_W_mK"]["slot_mixture"][1]}),
        ("Slot conductivity at the report's lower value", {"slot_k_W_mK": data["conductivity_W_mK"]["slot_mixture"][0]}),
        ("Tool's own slot model instead of an entered value", {"slot_k_model": "series_lower_bound"}),
        ("End-space coefficient 10 W/m2K", {"end_space_h_W_m2K": 10}),
        ("End-space coefficient 40 W/m2K", {"end_space_h_W_m2K": 40}),
        ("Tool's default steel conductivity, 20 W/mK", {"steel_k_W_mK": 20.0}),
        ("Tool's default liner conductivity, 0.2 W/mK", {"liner_k_W_mK": 0.2}),
        ("200 W counted as copper loss instead of stator iron loss",
         {"copper_W": reference_point["copper_W"] + moved, "stator_iron_W": reference_point["stator_iron_W"] - moved}),
    ):
        arguments = {"contact_m2K_W": contact, **changes}
        value = part_temperatures(reference_point, reference_casing, **arguments)["end_winding"]
        sensitivity.append({"change": label, "network_C": value, "shift_K": value - reference})

    differences = [row["difference_K"] for row in rows]
    return {
        "schema": "coilem-thermal-published-result-1",
        "source": data["source"], "data": DATA, "design": FIXTURE,
        "fitted_contact_m2K_W": contact,
        "assumed": {"slot_liner_mm": LINER_MM, "slot_k_W_mK": {level: slot_conductivity(level) for level in LINER_MM}},
        "rows": rows, "thermocouple_means": means,
        "summary": {
            "points": len(rows),
            "difference_K": _stats(differences),
            "rise_ratio": _stats([row["rise_ratio"] for row in rows]),
            "mean_difference_K": _stats([row["difference_K"] for row in means]),
            "mean_rise_ratio": _stats([row["rise_ratio"] for row in means]),
            "measured_inside_network_range": sum(row["inside_network_range"] for row in rows),
            "source_model_difference_K": _stats([sum(row["source_model_C"]) / 2 - row["measured_C"] for row in rows]),
        },
        "parts": {
            "coolant_C": parts["coolant_C"], "thermocouple": parts["thermocouple"], "casing_C": detail_casing,
            "source_model": {key: value for key, value in parts.items() if key.endswith("_C") and key != "coolant_C"},
            "network": {name: detail[name] for name in PARTS},
        },
        "sensitivity": {
            "coolant_C": reference_point["coolant_C"], "casing_C": reference_casing, "network_C": reference,
            "rows": sensitivity,
        },
        "resistance": resistance_note(),
    }
