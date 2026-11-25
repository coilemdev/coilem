"""The steady-state thermal estimate of a solved motor, for scripts and ``coilem thermal``.

    result = coilem.solve(motor, analyses=["torque", "back_emf", "losses"])
    estimate = coilem.thermal(result)
    print(estimate.hottest_part, estimate.hottest_C, estimate.winding_margin_K)

The estimate starts from the losses of a solved run, so the run must include
the ``losses`` analysis. Its cooling values are assumptions about the
installation: without any, the app's still-air starter values are used and
recorded with the result. The estimate is experimental; see MATERIALS.md.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.client._errors import InputError
from backend.client._results import Result

THERMAL_FILE_SCHEMA = "coilem.client_thermal/v1"
COOLING_MODES: tuple[str, ...] = ("still_air", "forced_air", "liquid_jacket")
INSULATION_CLASSES: tuple[str, ...] = ("A", "B", "F", "H")
# The three values that say how fast heat leaves. They belong to a kind of cooling.
COEFFICIENTS: tuple[str, ...] = ("housing_h_W_m2K", "end_space_h_W_m2K", "airgap_h_W_m2K")
# The app's starter values (THERMAL_STARTER in frontend/src/public/thermal.ts): illustrative, not measured.
STILL_AIR_STARTER: dict[str, Any] = {
    "cooling": "still_air",
    "ambient_C": 25.0,
    "insulation_class": "F",
    "housing_h_W_m2K": 10.0,
    "end_space_h_W_m2K": 10.0,
    "airgap_h_W_m2K": 20.0,
    "housing_thickness_mm": 3.0,
    "slot_liner_mm": 0.1,
    "contact_m2K_W": 0.001,
    "bearing_to_housing_K_W": 2.0,
    "rotor_to_bearing_K_W": 3.0,
    "hotspot_allowance_K": 15.0,
    # Outer-rotor motors only: hub, mount and airframe together.
    "mount_to_ambient_K_W": 10.0,
    "coefficient_source": "coilEM still-air starter v1: illustrative cooling, construction and hotspot assumptions; uncalibrated, not measured.",
}
# Conductor-grade aluminium is about 235 W/(m K). The model's own default is copper's, and it refuses
# an aluminium winding that names no conductivity, so an aluminium design starts from this value.
ALUMINIUM_CONDUCTOR_K_W_MK = 235.0
# Parts in the order a person reads them: hottest-running first, the air last.
PART_ORDER: tuple[str, ...] = ("end_winding", "winding", "teeth", "yoke", "housing", "mount", "magnets", "rotor", "bearings", "airgap", "end_air")
PART_NAMES: dict[str, str] = {
    "end_winding": "end winding", "winding": "slot winding", "teeth": "stator teeth", "yoke": "stator yoke", "housing": "housing",
    "mount": "stator mount", "magnets": "magnets", "rotor": "rotor", "bearings": "bearings", "airgap": "air gap", "end_air": "end-space air",
}


def thermal_inputs(
    *,
    outer_rotor: bool = False,
    aluminium: bool = False,
    cooling: str | None = None,
    ambient_C: float | None = None,  # noqa: N803 - the unit is part of the name
    insulation_class: str | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The complete thermal inputs for an estimate, as the request names them.

    The still-air starter values are the starting point and ``inputs`` (any
    thermal input by its name, see ``coilem schema``) is applied over them.
    Choosing another ``cooling`` drops the starter's three heat-transfer values
    and their source: another kind of cooling cannot inherit still-air numbers,
    so they must then be given in ``inputs``.

    An ``aluminium`` winding starts from aluminium's conductor conductivity
    (``ALUMINIUM_CONDUCTOR_K_W_MK``) where ``inputs`` gives none.

    Raises:
        InputError: A value is missing, unknown or out of range; ``.field`` is
            ``thermal.<name>``.
    """

    return _input_model(outer_rotor=outer_rotor, aluminium=aluminium, cooling=cooling, ambient_C=ambient_C,
                        insulation_class=insulation_class, inputs=inputs).model_dump(mode="json")


def _input_model(*, outer_rotor: bool, aluminium: bool, cooling: str | None, ambient_C: float | None,  # noqa: N803
                 insulation_class: str | None, inputs: Mapping[str, Any] | None) -> Any:
    """The validated inputs, with only the starter and given values marked as set.

    The estimate reads which inputs were set (an aluminium winding must name its
    conductor conductivity), so the model is built once and never from its own dump.
    """

    from pydantic import ValidationError

    from backend.models.thermal import ThermalInputs

    if not isinstance(inputs, Mapping) and inputs is not None:
        raise InputError("thermal inputs must be a mapping of input names to values", field="thermal")
    given = dict(inputs or {})
    for name, value in (("cooling", cooling), ("ambient_C", ambient_C), ("insulation_class", insulation_class)):
        if value is not None:
            given[name] = value
    values = dict(STILL_AIR_STARTER)
    if not outer_rotor:
        values.pop("mount_to_ambient_K_W")
    if aluminium:
        values["conductor_k_W_mK"] = ALUMINIUM_CONDUCTOR_K_W_MK
    chosen = given.get("cooling", "still_air")
    if chosen not in COOLING_MODES:
        raise InputError(f"cooling must be one of {', '.join(COOLING_MODES)} (got {chosen!r})", field="thermal.cooling")
    if chosen != "still_air":
        for name in (*COEFFICIENTS, "coefficient_source"):
            values.pop(name)
        missing = [name for name in (*COEFFICIENTS, "coefficient_source") if given.get(name) in (None, "")]
        if missing:
            raise InputError(
                f"{chosen} cooling needs {', '.join(missing)}: the still-air starter values do not apply to it",
                field=f"thermal.{missing[0]}",
                suggestion="Give the three heat-transfer values for your installation and a coefficient_source saying where they come from.",
            )
    values.update(given)
    try:
        return ThermalInputs.model_validate(values)
    except ValidationError as exc:
        problems = [(f"thermal.{'.'.join(str(part) for part in error['loc'])}" if error["loc"] else "thermal", error["msg"])
                    for error in exc.errors()]
        field, message = problems[0]
        raise InputError(f"{field}: {message}", field=field, problems=problems) from None


class ThermalEstimate:
    """A steady-state thermal estimate.

    ``data`` holds the whole estimate as the app returns it (JSON-compatible)
    and ``inputs`` the complete inputs it used, starter values included.
    ``status`` is ``"experimental"`` for an estimate with temperatures and
    ``"unavailable"`` when none could be given; ``status_reason`` says why.
    """

    __slots__ = ("data", "inputs")

    def __init__(self, data: Mapping[str, Any], inputs: Mapping[str, Any] | None = None) -> None:
        if not isinstance(data, Mapping) or data.get("kind") != "steady_state_thermal":
            raise ValueError("Not a coilEM thermal estimate")
        self.data: dict[str, Any] = dict(data)
        self.inputs: dict[str, Any] = dict(inputs if inputs is not None else data.get("inputs") or {})

    @property
    def status(self) -> str:
        return self.data["status"]

    @property
    def status_reason(self) -> str:
        return self.data["status_reason"]

    @property
    def available(self) -> bool:
        return self.status != "unavailable" and self.hottest_part is not None

    @property
    def parts(self) -> dict[str, dict[str, Any]]:
        """Every part with its temperature, limit, margin and heat, hottest-running parts first."""

        nodes = self.data.get("nodes") or {}
        return {name: nodes[name] for name in PART_ORDER if name in nodes}

    @property
    def temperatures_C(self) -> dict[str, float | None]:  # noqa: N802 - the unit is part of the name
        return {name: part.get("temperature_C") for name, part in self.parts.items()}

    @property
    def hottest_part(self) -> str | None:
        return self.data.get("hottest_node")

    @property
    def hottest_C(self) -> float | None:  # noqa: N802
        return self.temperatures_C.get(self.hottest_part) if self.hottest_part else None

    @property
    def winding_margin_K(self) -> float | None:  # noqa: N802
        """Room left under the winding's limit, for the winding part closest to it. Negative means over."""

        margins = [part["margin_K"] for name, part in self.parts.items() if name in ("winding", "end_winding") and part.get("margin_K") is not None]
        return min(margins) if margins else None

    @property
    def total_heat_W(self) -> float | None:  # noqa: N802
        return self.data.get("total_heat_W")

    def metrics(self) -> dict[str, float | str | None]:
        """The headline numbers as one flat row."""

        temperatures = self.temperatures_C
        winding = [temperatures[name] for name in ("winding", "end_winding") if temperatures.get(name) is not None]
        limit = next((part.get("limit_C") for name, part in self.parts.items() if name in ("winding", "end_winding")), None)
        return {
            "status": self.status,
            "hottest_part": self.hottest_part,
            "hottest_C": self.hottest_C,
            "winding_C": max(winding) if winding else None,
            "winding_limit_C": limit,
            "winding_margin_K": self.winding_margin_K,
            "magnets_C": temperatures.get("magnets"),
            "total_heat_W": self.total_heat_W,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"schema": THERMAL_FILE_SCHEMA, "inputs": copy.deepcopy(self.inputs), "thermal": copy.deepcopy(self.data)}

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def summary_text(self) -> str:
        """One line for a terminal: the hottest part and the winding's margin, or why there is no estimate."""

        if not self.available:
            return f"no estimate: {self.status_reason}"
        text = f"hottest part is the {PART_NAMES.get(self.hottest_part, self.hottest_part)} at {self.hottest_C:.1f} C"
        margin = self.winding_margin_K
        if margin is not None:
            text += f"; winding {abs(margin):.1f} K {'over' if margin < 0 else 'under'} its limit"
        return text

    def __repr__(self) -> str:
        return f"ThermalEstimate({self.summary_text()})"


def thermal(
    result: Result | str | Path,
    *,
    cooling: str | None = None,
    ambient_C: float | None = None,  # noqa: N803
    insulation_class: str | None = None,
    inputs: Mapping[str, Any] | None = None,
    copper_feedback: bool = True,
) -> ThermalEstimate:
    """Estimate the steady-state temperature of each part of a solved motor.

    Args:
        result: A :class:`Result` from :func:`solve`, or the path of a file
            written by ``Result.save`` or ``coilem solve``. It must come from a
            solve that included the ``losses`` and ``torque`` analyses.
        cooling: ``"still_air"`` (default), ``"forced_air"`` or
            ``"liquid_jacket"``. Anything but still air needs the three
            heat-transfer values and their source in ``inputs``.
        ambient_C: Temperature of the air or coolant that carries the heat away.
        insulation_class: ``"A"``, ``"B"``, ``"F"`` (default) or ``"H"``.
        inputs: Any other thermal input by its name, for example
            ``{"housing_h_W_m2K": 60, "contact_m2K_W": 0.0005}``. An outer-rotor
            motor also takes ``mount_to_ambient_K_W``.
        copper_feedback: Let the copper loss rise with the winding temperature
            until the two agree, as the app does. False keeps the solved loss.

    Returns:
        A :class:`ThermalEstimate`. One whose ``status`` is ``"unavailable"``
        has no temperatures, for example when the motor would settle far too
        hot for the entered cooling; ``status_reason`` says why.

    Raises:
        InputError: The result has no losses or no torque
            (``error_code`` ``THERMAL_LOSSES_MISSING``), a thermal input is
            not accepted (``.field`` is ``thermal.<name>``), or the design has
            mechanical loss and ``inputs`` has no ``mechanical_split`` saying
            which parts it heats.
    """

    from backend.client._solve import prepared_config
    from backend.loss_breakdown import operating_point_losses
    from backend.models import IronLoss
    from backend.rotor_layout import is_outer_rotor
    from backend.thermal_network import thermal_estimate

    if not isinstance(result, Result):
        try:
            result = Result.load(result)
        except OSError as exc:
            raise InputError(f"{result}: cannot read the result file ({exc.strerror or exc})", field="result",
                             error_code="DESIGN_FILE_UNREADABLE") from None
        except (ValueError, KeyError) as exc:
            raise InputError(f"{result}: not a coilEM solve result ({exc})", field="result") from None
    if result.request is None:
        raise InputError("The result does not carry the request it was solved from, so its design is unknown.", field="result",
                         suggestion="Use a result from coilem.solve, Result.save or `coilem solve`.")
    summary = result.summary
    if not summary.get("iron_loss") or summary.get("avg_torque_Nm") is None:
        raise InputError(
            "This result was solved without losses or without torque. The thermal estimate starts from both.",
            field="analyses", error_code="THERMAL_LOSSES_MISSING",
            suggestion="Solve again with the torque and losses analyses, for example --analyses torque,back_emf,losses.",
        )
    config = prepared_config(result.request)
    values = _input_model(outer_rotor=is_outer_rotor(config), aluminium=config.materials.conductor == "aluminum",
                          cooling=cooling, ambient_C=ambient_C, insulation_class=insulation_class, inputs=inputs)
    iron = IronLoss.model_validate(summary["iron_loss"])
    winding, losses = operating_point_losses(config, float(summary["avg_torque_Nm"]), iron)
    if winding is None or losses is None:
        raise InputError("The winding resistance of this design cannot be formed, so its copper loss is unknown.", field="winding")
    if losses.mechanical_loss_W > 0 and values.mechanical_split is None:
        # The app asks the same: friction and windage heat has to be put somewhere before it can be balanced.
        raise InputError(
            f"This design has {losses.mechanical_loss_W:g} W of mechanical loss, and the estimate needs to know which parts it heats.",
            field="thermal.mechanical_split",
            suggestion='Give the shares, which must total 1, for example --thermal \'mechanical_split={"bearings": 1, "housing": 0, "rotor": 0}\'. '
                       "For an outer-rotor motor the housing share heats the mount.",
        )
    estimate = thermal_estimate(config, values, winding, losses, iron, with_copper_feedback=copper_feedback)
    # The network itself is a few hundred lines of links; scripts read the parts.
    return ThermalEstimate(estimate.model_dump(mode="json", exclude={"network"}), values.model_dump(mode="json"))
