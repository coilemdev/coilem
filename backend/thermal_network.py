"""Geometry-derived lumped thermal estimates (#19), not a thermal rating.

All cooling/contact inputs are explicit. MATERIALS.md documents every path and
its approximations. No electromagnetic source or public solver policy changes.
"""

from __future__ import annotations

import math
from collections import defaultdict
from functools import lru_cache

import numpy as np

from backend.geometry_ir import build_geometry_ir
from backend.magnet_temperature import GRADE_TEMPERATURE
from backend.models import IronLoss, LossBreakdown, MotorConfig, WindingResistance
from backend.models.thermal import (
    CORE_REASON,
    ROTOR_REASON,
    CopperFeedback,
    RotorHeating,
    ThermalInputs,
    ThermalLink,
    ThermalNetwork,
    ThermalNodeResult,
    ThermalResult,
    ThermalSlab,
)
from backend.rotor_layout import is_outer_rotor
from backend.winding_resistance import _winding_coils

INSULATION_LIMIT_C = {"A": 105.0, "B": 130.0, "F": 155.0, "H": 180.0}
# An inner-rotor stator sits in a housing; an outer-rotor stator sits on a hub
# that bolts to a mount. A result carries whichever of the two its layout has.
MATERIAL_NODES = frozenset({"winding", "end_winding", "teeth", "yoke", "housing", "mount", "rotor", "magnets"})
ROTOR_NODES = frozenset({"rotor", "magnets", "airgap", "end_air", "bearings"})
RESULT_NODES = MATERIAL_NODES | ROTOR_NODES | {"ambient"}


def _conductance_elements(network: ThermalNetwork):
    """Local symmetric conductance blocks; slab order is (mean, face a, face b).

    Integrating k*A*T''=-Q/L gives Tmean=(Ta+Tb)/2+Q*R/12 and
    outward Qa=Q/2+(Tb-Ta)/R. Eliminating Q gives this three-terminal
    block. Its eigenvalues are 0, 2/R and 18/R: passive despite the
    positive face-to-face off-diagonal. See ANALYTICAL_REDUCTION_FIX.md.
    """
    for link in network.links:
        yield (link.a, link.b), np.array([[1., -1.], [-1., 1.]]) / link.resistance_K_W
    for slab in network.slabs:
        yield (slab.mean, slab.a, slab.b), np.array([[12., -6., -6.], [-6., 4., 2.], [-6., 2., 4.]]) / slab.resistance_K_W


def boundary_heat_flows(network: ThermalNetwork, temperatures: dict[str, float]) -> dict[str, float]:
    """Signed heat rejected into each fixed boundary, including slab ports."""
    flows = dict.fromkeys(network.fixed_C, 0.0)
    for nodes, conductance in _conductance_elements(network):
        # Row sums vanish. Subtract a datum to avoid cancellation of absolute
        # temperatures at high conductance; boundary heat can be negative.
        local = np.array([temperatures[n] - temperatures[nodes[0]] for n in nodes])
        outgoing = conductance @ local
        for i, node in enumerate(nodes):
            if node in flows:
                flows[node] -= float(outgoing[i])
    return flows


def _network_system(network: ThermalNetwork):
    """Assemble link and three-terminal slab balances for unknown temperatures.

    Every component must reach a fixed boundary. Connectivity is checked before
    the linear solve, so an unheated floating component cannot invent a value.
    """

    elements = list(_conductance_elements(network))
    reached = set(network.fixed_C)
    while True:
        expanded = reached | {end for nodes, _ in elements if reached.intersection(nodes) for end in nodes}
        if expanded == reached:
            break
        reached = expanded
    if reached != set(network.nodes):
        raise ValueError("Thermal network has nodes disconnected from a temperature boundary")
    unknown = [node for node in network.nodes if node not in network.fixed_C]
    index = {node: i for i, node in enumerate(unknown)}
    matrix = np.zeros((len(unknown), len(unknown)))
    rhs = np.array([network.heat_W.get(node, 0.0) for node in unknown])
    for nodes, conductance in elements:
        for i, a in enumerate(nodes):
            if a not in index:
                continue
            for j, b in enumerate(nodes):
                if b in index:
                    matrix[index[a], index[b]] += conductance[i, j]
                else:
                    rhs[index[a]] -= conductance[i, j] * network.fixed_C[b]
    return unknown, matrix, rhs


def solve_network(network: ThermalNetwork) -> tuple[dict[str, float], float, float]:
    """Solve a fixed-heat network and independently check its boundary balance."""
    unknown, matrix, rhs = _network_system(network)
    try:
        values = np.linalg.solve(matrix, rhs) if unknown else []
    except np.linalg.LinAlgError as exc:
        raise ValueError("Thermal network is singular") from exc
    temperatures = {**network.fixed_C, **dict(zip(unknown, map(float, values)))}
    if any(not math.isfinite(t) or t <= -273.15 for t in temperatures.values()):
        raise ValueError("Thermal network returned nonphysical temperatures")
    rejection = sum(boundary_heat_flows(network, temperatures).values())
    error = rejection - sum(network.heat_W.values())
    if abs(error) > 1e-6 * max(1.0, sum(network.heat_W.values())):
        raise ValueError("Thermal network failed its energy balance")
    return temperatures, rejection, error


def solve_copper_feedback(
    reference_network: ThermalNetwork, coefficient_per_K: float, copper_nodes: tuple[str, ...],
) -> tuple[ThermalNetwork, dict[str, float], float, float, float, float]:
    """Exact equilibrium Q_i(T_i)=Q20_i*[1+alpha*(T_i-20)] at fixed current.

    G is the passive conductance matrix, D=diag(alpha*Q20). Stable cooling
    requires G-D positive definite, equivalently rho(sqrt(D)*inv(G)*sqrt(D))<1.
    That criterion rejects even a finite algebraic solution on an unstable branch.
    Thermal capacitances are not needed to determine this sign criterion.
    """
    if not math.isfinite(coefficient_per_K) or coefficient_per_K < 0:
        raise ValueError("Invalid conductor resistance temperature coefficient")
    unknown, matrix, rhs = _network_system(reference_network)
    index = {node: i for i, node in enumerate(unknown)}
    if not copper_nodes or len(set(copper_nodes)) != len(copper_nodes) or any(n not in index for n in copper_nodes):
        raise ValueError("Copper feedback needs distinct unknown-temperature nodes")
    slope = np.array([coefficient_per_K * reference_network.heat_W.get(n, 0) if n in copper_nodes else 0 for n in unknown])
    try:
        root = np.sqrt(slope)
        gain = float(np.linalg.eigvalsh(root[:, None] * np.linalg.solve(matrix, np.diag(root)))[-1])
        # Guard the singular boundary at floating-point precision, not a thermal
        # acceptance band or an empirical runaway-temperature threshold.
        if not math.isfinite(gain) or gain >= 1 - 1e-12:
            raise ValueError("No stable thermal equilibrium: copper resistance feedback overwhelms cooling at this current.")
        values = np.linalg.solve(matrix - np.diag(slope), rhs - 20 * slope)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Copper-temperature equilibrium is numerically unresolved") from exc
    temperatures = {**reference_network.fixed_C, **dict(zip(unknown, map(float, values)))}
    heat = dict(reference_network.heat_W)
    for node in copper_nodes:
        factor = 1 + coefficient_per_K * (temperatures[node] - 20)
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("Copper-temperature equilibrium gives nonphysical conductor resistance")
        heat[node] = reference_network.heat_W.get(node, 0) * factor
    resolved = ThermalNetwork.model_validate({**reference_network.model_dump(), "heat_W": heat})
    checked, rejection, error = solve_network(resolved)
    residual = max(abs(checked[n] - temperatures[n]) for n in unknown)
    if not math.isfinite(residual) or residual > 1e-6:
        raise ValueError("Copper-temperature equilibrium failed its temperature consistency check")
    return resolved, checked, rejection, error, max(0.0, gain), residual


def slab_mean_resistance(length_m: float, conductivity: float, cross_area_m2: float, *, two_sided: bool) -> float:
    """Uniform-generation mean: L/(12 k A) for two faces, L/(3 k A) for one.

    The one-face case has the other face insulated. Contact/convection
    resistances are separate and receive no generation correction.
    """

    if min(length_m, conductivity, cross_area_m2) <= 0:
        raise ValueError("Slab dimensions and conductivity must be positive")
    return length_m / ((12 if two_sided else 3) * conductivity * cross_area_m2)


def cylindrical_resistance(inner_m: float, outer_m: float, length_m: float, conductivity: float) -> float:
    if not 0 < inner_m < outer_m or min(length_m, conductivity) <= 0:
        raise ValueError("Invalid cylindrical conduction geometry")
    return math.log(outer_m / inner_m) / (2 * math.pi * conductivity * length_m)


def end_winding_surface(config: MotorConfig, winding: WindingResistance, slot_area_m2: float) -> tuple[float, float]:
    """Square homogenized bundle, two ends per actual coil; return area, side.

    Assume the same gross area/fill as the active slots, consistent with the
    transverse mixture conductivity. Copper-only area would double-count the
    insulation in k while omitting it from the geometry. Actual packing is unknown.
    """

    coils = len(_winding_coils(config))
    if not coils:
        raise ValueError("End-winding area needs a coil layout")
    side = math.sqrt(slot_area_m2 / (2 * coils))
    return coils * 2 * winding.end_turn_length_mm * 1e-3 * 4 * side, side


def axial_winding_resistance(active_length: float, end_length: float, copper_area: float, conductivity: float) -> float:
    """Symmetric coil: two active legs and two end arcs meet at common junctions.

    Integrate each half-leg/half-arc from its insulated symmetry plane. The
    mean-to-junction drops are Qnet*L/(12*k*A) for each aggregate; eliminating
    the junction adds BOTH drops. Side heat exchange is distributed in each part.
    """
    if not all(math.isfinite(v) and v > 0 for v in (active_length, end_length, copper_area, conductivity)):
        raise ValueError("Axial winding dimensions and conductivity must be positive and finite")
    return (active_length + end_length) / (12 * conductivity * copper_area)


@lru_cache(maxsize=128)
def _square_robin_factor(biot: float, terms: int = 256) -> float:
    """Mean rise / (q*a^2/k), square [-a,a]^2, four identical Robin faces.

    mu*tan(mu)=Bi; squared projection weights of the uniform source onto
    cos(mu*x/a) give the double sum. Positive tails converge from below.
    A small-Bi asymptote avoids loss of precision in the first root.
    """
    if biot < 1e-7:
        return 1 / (2 * biot) + 1 / 6
    roots = []
    for n in range(terms):
        lo, hi = n * math.pi, (n + .5) * math.pi
        for _ in range(60):
            mu = (lo + hi) / 2
            if mu - n * math.pi < math.atan2(biot, mu):
                lo = mu
            else:
                hi = mu
        roots.append((lo + hi) / 2)
    mu = np.array(roots)
    weights = 2 * (np.sin(mu) / mu)**2 / (1 + np.sin(2 * mu) / (2 * mu))
    return float(np.sum(weights[:, None] * weights / (mu[:, None]**2 + mu**2)))


def square_bundle_resistance(side: float, full_surface_area: float, conductivity: float, coefficient: float) -> float:
    """Uniform net heat in a square bundle, cooled to one well-mixed end-air node.

    Exposure is represented by a uniformly reduced coefficient, not a resolved
    patch of insulated faces. Includes conduction AND convection; do not add 1/hA.
    """
    if not all(math.isfinite(v) and v > 0 for v in (side, full_surface_area, conductivity, coefficient)):
        raise ValueError("Square bundle dimensions, conductivity and coefficient must be positive and finite")
    biot = coefficient * side / (2 * conductivity)
    return _square_robin_factor(biot) * side / (conductivity * full_surface_area)


def build_network(
    config: MotorConfig, inputs: ThermalInputs, winding: WindingResistance,
    losses: LossBreakdown, iron: IronLoss,
) -> ThermalNetwork:
    """Reduce exact IR areas to documented rectangular/annular heat paths."""

    outer_layout = is_outer_rotor(config)
    if outer_layout and inputs.mount_to_ambient_K_W is None:
        raise ValueError("An outer-rotor estimate needs the mount-to-surroundings resistance")
    if iron.status == "unavailable" or iron.iron_loss_W is None or losses.iron_loss_W is None:
        raise ValueError("Thermal estimate requires an available stator iron loss; missing heat is not zero")
    if not math.isclose(iron.iron_loss_W, losses.iron_loss_W, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError("Iron-loss record and loss breakdown disagree")
    if losses.mechanical_loss_W > 0 and inputs.mechanical_split is None:
        raise ValueError("Mechanical loss needs an explicit destination split")
    if config.materials.conductor == "aluminum" and "conductor_k_W_mK" not in inputs.model_fields_set:
        raise ValueError("Aluminium thermal estimates need an explicit conductor conductivity")
    areas = defaultdict(float)
    for region in build_geometry_ir(config).regions:
        areas[region.kind] += region.area_mm2 * 1e-6
    length = config.stator.stack_length_mm * 1e-3
    outer, inner = config.stator.OD_mm * 0.0005, config.stator.ID_mm * 0.0005
    yoke = config.stator.yoke_thickness_mm * 1e-3
    depth = outer - inner - yoke
    if depth <= 0 or not 0 < winding.copper_fill < 1:
        raise ValueError("Thermal geometry needs positive slot depth and a copper fill between zero and one")
    # A pinned reference can represent the whole stator as one region. Divide
    # its steel area by the template's radial yoke boundary, without discarding heat.
    teeth_area = areas["StatorTooth"]
    yoke_area = areas["StatorYoke"]
    if not teeth_area:
        total_steel = yoke_area
        # The yoke ring lies at the stator's back: its outside for an inner rotor, its hub side for an outer one.
        yoke_ring = math.pi * ((inner + yoke)**2 - inner**2) if outer_layout else math.pi * (outer**2 - (outer - yoke)**2)
        yoke_area = min(total_steel, yoke_ring)
        teeth_area = total_steel - yoke_area
    slot_area = areas["SlotWinding"]
    if min(teeth_area, yoke_area, slot_area, areas["Magnet"]) <= 0:
        raise ValueError("Thermal template needs winding, tooth, yoke and magnet regions")
    slot_width = slot_area / config.stator.slot_count / depth
    wall_area = 2 * depth * config.stator.slot_count * length
    k_slot = 1 / (winding.copper_fill / inputs.conductor_k_W_mK + (1 - winding.copper_fill) / inputs.impregnation_k_W_mK)
    if inputs.slot_k_model == "user":
        k_slot = inputs.slot_k_W_mK
    liner = inputs.slot_liner_mm * 1e-3
    if 2 * liner >= slot_width:
        raise ValueError("Slot liner leaves no winding width in the equivalent slot")
    # The stator has two cylindrical faces: one meets the air gap, the other is
    # the back of the yoke. Which is the outside depends on the layout.
    gap_radius, back_radius = (outer, inner) if outer_layout else (inner, outer)
    contact_area = 2 * math.pi * back_radius * length
    gap_area = 2 * math.pi * gap_radius * length
    end_face_area = math.pi * (outer**2 - inner**2)
    end_area, bundle_side = end_winding_surface(config, winding, slot_area)
    magnet_thickness = config.rotor.magnet_thickness_mm * 1e-3
    if outer_layout:
        # The rotor is a shell around the stator: magnets on its inner face, its
        # outer face and one closed end open to the surroundings.
        shell_inner, shell_outer = config.rotor.ID_mm * 0.0005, config.rotor.OD_mm * 0.0005
        magnet_face_radius = shell_inner - magnet_thickness
        if not gap_radius < magnet_face_radius < shell_inner < shell_outer:
            raise ValueError("Outer-rotor thermal geometry needs magnets and a rotor shell outside the stator")
        rotor_gap_area = 2 * math.pi * magnet_face_radius * length
        shell_exterior_area = 2 * math.pi * shell_outer * length + math.pi * shell_outer**2
        shell_cap_area = math.pi * shell_inner**2
    else:
        housing_outer = outer + inputs.housing_thickness_mm * 1e-3
        exterior_area = 2 * math.pi * housing_outer * length + 2 * math.pi * (housing_outer**2 - inner**2)
        rotor_gap_area = 2 * math.pi * config.rotor.OD_mm * 0.0005 * length
    magnet_face = areas["Magnet"] / magnet_thickness * length
    links = []
    slabs = []

    def link(a, b, resistance, assumption):
        links.append(ThermalLink(a=a, b=b, resistance_K_W=resistance * inputs.calibration_multiplier, assumption=assumption))

    def slab(mean, a, b, resistance, assumption):
        slabs.append(ThermalSlab(mean=mean, a=a, b=b, resistance_K_W=resistance * inputs.calibration_multiplier,
                                 assumption=assumption))

    link("winding", "teeth", slab_mean_resistance(slot_width - 2 * liner, k_slot, wall_area / 2, two_sided=True)
         + liner / (inputs.liner_k_W_mK * wall_area),
         "Uniform-generation slab mean, explicit liner; slot conductivity model: " + inputs.slot_k_model)
    slab("teeth", "stator_bore", "tooth_yoke_interface", depth / (inputs.steel_k_W_mK * (teeth_area / depth) * length),
         "Exact uniform-generation planar slab mean and two faces; winding-side heat is distributed at the tooth mean; IR aggregate width")
    if outer_layout:
        slab("yoke", "tooth_yoke_interface", "stator_back", yoke / (inputs.steel_k_W_mK * contact_area),
             "Exact uniform-generation planar yoke mean and two faces; perfect tooth/yoke interface; "
             "constant hub-circumference area, the smaller face, so the resistance is not understated")
        link("stator_back", "mount", inputs.contact_m2K_W / contact_area,
             "Yoke-to-hub contact; conduction in the hub itself belongs to the entered mount resistance")
        link("mount", "ambient", inputs.mount_to_ambient_K_W,
             "User-entered resistance from the stator hub through the mount to the surroundings")
        link("rotor", "ambient", cylindrical_resistance(shell_inner, shell_outer, length, inputs.steel_k_W_mK)
             + 1 / (inputs.housing_h_W_m2K * shell_exterior_area),
             "User-entered outside coefficient on the rotor shell: its cylinder over the stack length and one closed end; "
             "no inferred speed correlation; a longer shell would shed more")
    else:
        slab("yoke", "tooth_yoke_interface", "stator_outer", yoke / (inputs.steel_k_W_mK * contact_area),
             "Exact uniform-generation planar yoke mean and two faces; perfect tooth/yoke interface; constant outer-circumference area")
        link("stator_outer", "housing", inputs.contact_m2K_W / contact_area
             + cylindrical_resistance(outer, housing_outer, length, inputs.housing_k_W_mK),
             "Stator outer surface contact and unheated cylindrical housing; no generated-heat correction")
        link("housing", "ambient", 1 / (inputs.housing_h_W_m2K * exterior_area),
             "User-entered housing coefficient; shell and annular end faces at the coolant/ambient boundary")
    link("winding", "end_winding", axial_winding_resistance(length, winding.end_turn_length_mm * 1e-3,
         slot_area * winding.copper_fill, inputs.conductor_k_W_mK),
         "Symmetric active-leg and end-arc mean-to-junction resistances in series; side heat exchange distributed in each part")
    link("end_winding", "end_air", square_bundle_resistance(bundle_side, end_area, k_slot,
         inputs.end_space_h_W_m2K * inputs.end_winding_exposed_fraction),
         "Uniform-net-source square bundle, same gross fill as slots; Robin conduction/convection; exposure uniformly reduces h")
    if outer_layout:
        link("end_air", "rotor", 1 / (inputs.end_space_h_W_m2K * shell_cap_area),
             "Air inside the rotor to the closed end of the shell, using the user coefficient; "
             "no air exchange through openings in the shell is assumed, so an open rotor runs cooler than this")
        link("end_air", "mount", 1 / (inputs.end_space_h_W_m2K * end_face_area),
             "Air inside the rotor to the stator carrier face on the mount side, using the user coefficient")
    else:
        link("end_air", "housing", 1 / (inputs.end_space_h_W_m2K * 2 * end_face_area),
             "Internal end-space convection to annular end caps using user coefficient")
    link("stator_bore", "airgap", 1 / (inputs.airgap_h_W_m2K * gap_area),
         "Per-surface gap coefficient on stator bore; no inferred speed correlation")
    link("airgap", "rotor", 1 / (inputs.airgap_h_W_m2K * rotor_gap_area),
         "Per-surface gap coefficient on rotor surface")
    link("magnets", "rotor", slab_mean_resistance(magnet_thickness, inputs.magnet_k_W_mK, magnet_face, two_sided=False),
         "Uniform-source magnet mean, insulated gap-side face and isothermal rotor contact; no adhesive or pocket contact model")
    stator_support = "mount" if outer_layout else "housing"
    link("rotor", "bearings", inputs.rotor_to_bearing_K_W, "User-entered shaft/bearing thermal path")
    link("bearings", stator_support, inputs.bearing_to_housing_K_W, f"User-entered bearing-to-{stator_support} thermal path")

    tooth_heat, yoke_heat = iron.iron_teeth_loss_W, iron.iron_yoke_loss_W
    if tooth_heat is None or yoke_heat is None:
        tooth_heat = iron.iron_loss_W * teeth_area / (teeth_area + yoke_area)
        yoke_heat = iron.iron_loss_W - tooth_heat
    if not math.isclose(tooth_heat + yoke_heat, iron.iron_loss_W, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError("Tooth/yoke heat must sum to total stator iron loss")
    heat = dict(winding=losses.copper_active_loss_W, end_winding=losses.copper_end_winding_loss_W,
                teeth=tooth_heat, yoke=yoke_heat,
                rotor=inputs.extra_rotor_heat_W * (1 - inputs.extra_rotor_heat_to_magnets_fraction),
                magnets=inputs.extra_rotor_heat_W * inputs.extra_rotor_heat_to_magnets_fraction)
    if inputs.mechanical_split is not None:
        for node, fraction in inputs.mechanical_split.model_dump().items():
            # The split's housing share is the stator support's: the mount of an outer-rotor motor.
            node = stator_support if node == "housing" else node
            heat[node] = heat.get(node, 0) + losses.mechanical_loss_W * fraction
    nodes = ["winding", "end_winding", "teeth", "yoke", stator_support, "rotor", "magnets", "airgap", "end_air", "bearings", "ambient",
             "stator_bore", "tooth_yoke_interface", "stator_back" if outer_layout else "stator_outer"]
    return ThermalNetwork(nodes=nodes, links=links, slabs=slabs, fixed_C={"ambient": inputs.ambient_C}, heat_W=heat)


def thermal_estimate(
    config: MotorConfig, inputs: ThermalInputs, winding: WindingResistance,
    losses: LossBreakdown, iron: IronLoss, *, with_copper_feedback: bool = False,
) -> ThermalResult:
    """Unqualified node averages and an extra-rotor-heat sensitivity, with balance."""

    feedback = None
    baseline = None
    copper_nodes = ("winding", "end_winding")
    try:
        reference = build_network(config, inputs, winding, losses, iron)
        if with_copper_feedback:
            # Always normalise to R20, regardless of the supplied EM run's
            # configured winding temperature; do not apply the correction twice.
            reference_copper = 3 * losses.phase_current_rms_A**2 * winding.phase_resistance_20C_ohm
            active = reference_copper * winding.active_fraction
            reference = reference.model_copy(update={"heat_W": {
                **reference.heat_W, "winding": active, "end_winding": reference_copper - active,
            }})
            network, temperatures, rejection, error, gain, residual = solve_copper_feedback(
                reference, winding.temperature_coefficient_per_K, copper_nodes)
            # The existing resistance record supports -50..250 C. A stable
            # algebraic root outside that domain is not an actionable prediction.
            if any(not -50 <= temperatures[n] <= 250 for n in copper_nodes):
                raise ValueError("The winding would settle outside -50 to 250 C with these cooling values, which is beyond what "
                                 "this estimate supports. Raise the cooling values or lower the current.")
            effective_factor = sum(weight * (1 + winding.temperature_coefficient_per_K * (temperatures[node] - 20))
                                   for node, weight in (("winding", winding.active_fraction), ("end_winding", 1 - winding.active_fraction)))
            feedback = CopperFeedback(
                temperature_coefficient_per_K=winding.temperature_coefficient_per_K,
                phase_current_rms_A=losses.phase_current_rms_A,
                phase_resistance_20C_ohm=winding.phase_resistance_20C_ohm,
                phase_resistance_ohm=winding.phase_resistance_20C_ohm * effective_factor,
                reference_copper_loss_W=reference_copper,
                copper_active_loss_W=network.heat_W["winding"], copper_end_winding_loss_W=network.heat_W["end_winding"],
                copper_loss_W=sum(network.heat_W[n] for n in copper_nodes),
                loop_gain=gain, temperature_residual_K=residual, wire_source=winding.wire_source,
            )
        else:
            network = reference
            temperatures, rejection, error = solve_network(network)
        if inputs.extra_rotor_heat_W:
            heat = dict(reference.heat_W)
            heat["rotor"] -= inputs.extra_rotor_heat_W * (1 - inputs.extra_rotor_heat_to_magnets_fraction)
            heat["magnets"] -= inputs.extra_rotor_heat_W * inputs.extra_rotor_heat_to_magnets_fraction
            baseline_network = reference.model_copy(update={"heat_W": heat})
            if with_copper_feedback:
                _, baseline, _, _, _, _ = solve_copper_feedback(baseline_network, winding.temperature_coefficient_per_K, copper_nodes)
            else:
                baseline, _, _ = solve_network(baseline_network)
    except ValueError as exc:
        return ThermalResult(status="unavailable", status_reason=str(exc), inputs=inputs)
    grade = GRADE_TEMPERATURE.get(config.materials.magnet_grade)
    nodes = {}
    mechanical_rotor = losses.mechanical_loss_W * inputs.mechanical_split.rotor if inputs.mechanical_split else 0
    rotor_heating = RotorHeating(
        basis="heat_transfer_plus_supplied_heat" if inputs.extra_rotor_heat_W + mechanical_rotor > 0 else "heat_transfer_only",
        additional_heat_W=inputs.extra_rotor_heat_W, mechanical_heat_to_rotor_W=mechanical_rotor,
    )
    calibrated = inputs.calibration_source is not None
    estimate_reason = "Calibrated estimate against the recorded measurement. No independent bench qualification." if calibrated else CORE_REASON
    for name, temperature in temperatures.items():
        if name not in RESULT_NODES:
            continue  # Internal surface ports are not component-average outputs.
        experimental_rotor = name in ROTOR_NODES
        reason = ROTOR_REASON if experimental_rotor else CORE_REASON
        if name == "bearings":
            reason = ("Heat-transfer estimate including the entered mechanical heat allocation; bearing friction is not "
                      "independently calculated. Missing rotor/magnet losses may change this temperature. No bench qualification.")
        elif name in {"airgap", "end_air"}:
            reason = ("Heat-transfer estimate under entered cooling and heat assumptions. Missing rotor/magnet losses "
                      "may change this temperature. No bench qualification.")
        if calibrated and not experimental_rotor:
            reason = estimate_reason
        limit = None
        if name in {"winding", "end_winding"}:
            limit = INSULATION_LIMIT_C[inputs.insulation_class] - inputs.hotspot_allowance_K
        elif name == "magnets" and grade:
            limit = grade.max_operating_C
        nodes[name] = ThermalNodeResult(
            temperature_C=temperature, heat_W=network.heat_W.get(name, 0),
            status="experimental", status_reason=reason,
            limit_C=limit, margin_K=limit - temperature if limit is not None else None,
        )
    if baseline is not None:
        baseline = {name: value for name, value in baseline.items() if name in nodes and nodes[name].temperature_C is not None}
    return ThermalResult(
        inputs=inputs, status_reason=estimate_reason, nodes=nodes, baseline_without_extra_rotor_C=baseline, network=network,
        total_heat_W=sum(network.heat_W.values()), rejected_heat_W=rejection, energy_balance_error_W=error,
        hottest_node=max((n for n in nodes if n in MATERIAL_NODES and nodes[n].temperature_C is not None),
                         key=lambda n: nodes[n].temperature_C),
        calibrated=calibrated, copper_feedback=feedback, rotor_heating=rotor_heating,
        notes=[("Material nodes are lumped representative temperatures, not hotspots. Outer rotor: heat leaves through the "
                "entered mount resistance and from the rotor shell's outer face; the shell is taken as closed, with no "
                "air exchange through its openings. " if is_outer_rotor(config) else
                "Material nodes are lumped representative temperatures, not hotspots; housing uses an outer-surface proxy. ")
               + "Insulation-class limits are reduced by the entered hotspot allowance.",
               "Tooth/yoke paths distinguish planar slab means and surface temperatures; "
               "winding-side heat remains a distributed tooth-mean approximation.",
               "One calibration multiplier cannot identify several uncertain heat paths.",
               "Rotor/magnet eddy-current, AC copper and inverter losses are not calculated. "
               "Zero additional heat is an omission, not evidence of zero loss.",
               "Temperatures and margins apply only to the entered heat scenario; omitted losses can affect all nodes. "
               "They are not safe operating limits.",
               "The legacy declared magnet/rotor frequency limit is ignored; no universal frequency validity threshold is established.",
               "Cooling coefficients apply at this operating point; no speed law or rotating thermal qualification is inferred.",
               "Slot conductivity is a labelled series lower bound unless a user value/source is supplied.",
               "Conductivities and reduced mean-path geometry are editable engineering assumptions; see MATERIALS.md."]
              + (["Copper losses use separate active/end winding equilibrium temperatures at fixed current. "
                  "Iron loss, mechanical/extra rotor heat and thermal paths are held fixed; no EM or magnet-temperature re-solve.",
                  "Any zero-extra-rotor-heat sensitivity independently recomputes copper feedback."] if with_copper_feedback else []),
    )
