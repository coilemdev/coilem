"""Pinned published motor geometry, independent of optional reference runtimes.

Each published reference registers one ``ReferenceModel``. Pipeline code asks
``reference_model(config)`` for the hook it needs rather than testing for a
reference by name, so adding a reference does not touch the solve path.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable

# Imported lazily, so the ordinary solve path never loads reference assets.
_MODULES = {
    "pyleecan_prius_2004": "backend.reference_models.prius",
    "lrk_12s14p": "backend.reference_models.lrk",
}


@dataclass(frozen=True)
class ReferenceModel:
    reference_id: str
    # Short name for messages, e.g. "Prius".
    label: str
    # build_ir(config, geom) -> GeometryIR with the exact published regions.
    build_ir: Callable[..., Any]
    # Raises ValueError when the config edits the pinned design or picks an unregistered case.
    check_config: Callable[[Any], None]
    geometry_asset_sha256: Callable[[], str]
    qualification_reason: str
    magnet_temperatures_C: tuple[float, ...]
    # How the current angle is measured, for metadata, reports and the preview.
    current_angle_convention: str = "q-axis gamma"
    current_angle_label: str = "Current angle"
    phase_current_convention: str = "q_axis"
    # Replaces the generic excitation when the reference publishes its own (and
    # then also opts out of the clockwise current-angle rewrite).
    excitation_sample: Callable[..., Any] | None = None
    # Sets explicit per-region current densities on a built mesh artifact.
    exact_currents: Callable[..., Any] | None = None
    # (config) -> the A/B/C currents exact_currents holds, or None when the
    # config's own excitation applies. Losses and the operating point read the
    # current from here, not from the solve settings the case ignores.
    fixed_phase_currents_a: Callable[[Any], tuple[float, float, float] | None] | None = None
    # Native solver environment overrides: (config, armature_only_field) -> dict.
    solver_overrides: Callable[..., dict[str, str]] | None = None
    # Rewrites a native report in place: (report, config, artifact).
    postprocess_report: Callable[..., None] | None = None
    # True when postprocess_report replaces the solver's flux linkage from the
    # reference's own winding regions. Otherwise the solver bins slot regions
    # by the generic winding map, which the reference's map must then equal.
    owns_flux_linkage: bool = False
    # Published slot/phase/direction rows for the preview winding view.
    published_winding: Callable[[], list[dict[str, Any]]] | None = None
    published_winding_label: str | None = None
    # Published conductor, used when the design names no wire.
    wire: Any = None
    # Rows for the report's "Published software reference" settings group.
    report_settings: Callable[[dict[str, Any], dict[str, Any]], list[tuple[str, str]]] | None = None


def reference_model(source: Any) -> ReferenceModel | None:
    """The registered model for a config, a config dict or a reference id; None for ordinary designs."""

    if source is None or isinstance(source, str):
        reference_id = source
    elif isinstance(source, dict):
        reference_id = source.get("geometry_reference")
    else:
        reference_id = getattr(source, "geometry_reference", None)
    if not reference_id:
        return None
    try:
        module = _MODULES[reference_id]
    except KeyError:
        raise ValueError(f"Unknown published geometry reference: {reference_id}") from None
    # Built per lookup, so it always reads the module's current functions.
    return importlib.import_module(module).model()
