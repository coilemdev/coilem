"""FEMM post-processing and analysis methods.

Extracted from femm_solver.py for maintainability.
Contains all methods for post-processing FEMM solve results:
- Waveform tiling (partial sweep → full 360°)
- Back-EMF computation from flux linkage derivatives
- THD calculation via FFT
- Efficiency estimation
- No-load sweep orchestration
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np

from backend.back_emf_harmonics import (
    analyze_back_emf_harmonics,
    harmonic_limit_for_quality,
)
from backend.geometry_drawer import (
    MotorGeometry,
    get_native_path_from_wine_path,
    get_wine_compatible_path,
    resolve_phase_current_peak,
)
from backend.logging_utils import tagged_log
from backend.material_catalog import (
    CONDUCTOR_PROPERTIES,
    MAGNET_PROPERTIES,
    STEEL_ANALYSIS_PROPERTIES,
)
from backend.models import (
    BackEMFWaveform,
    DemagCheck,
    LossBreakdown,
    MotorConfig,
    SlotFillCheck,
    ThermalEstimate,
    TorqueSpeedEnvelope,
    WeightInertia,
)

logger = logging.getLogger(__name__)

STEEL_PROPERTIES = STEEL_ANALYSIS_PROPERTIES

FEMM_BEMF_STEP_ENV = "OPENEM_FEMM_BEMF_STEP_DEG"


class FEMMPostprocessMixin:
    """Mixin providing post-processing methods for FEMMSolver.

    Expects the following attributes/methods from the host class (FEMMSolver)
    and sibling mixins (FEMMGeometryMixin, FEMMExtractionMixin):
    - _setup_problem(femm, config, geom): from FEMMSolver
    - _draw_full_geometry(femm, config, geom, rotor_offset_deg): from FEMMGeometryMixin
    - _apply_boundary(femm, geom): from FEMMGeometryMixin
    - _extract_flux_linkage(femm, config, geom): from FEMMExtractionMixin
    - _last_rotor_offset_rad: float
    """

    # Declare attributes/methods expected from FEMMSolver and sibling mixins (satisfies mypy)
    _last_rotor_offset_rad: float

    def _setup_problem(self, femm: Any, config: MotorConfig, geom: MotorGeometry) -> None: ...
    def _draw_full_geometry(self, femm: Any, config: MotorConfig, geom: MotorGeometry, rotor_offset_deg: float = 0.0) -> None: ...
    def _apply_boundary(self, femm: Any, geom: MotorGeometry) -> None: ...
    def _is_cancel_requested(self) -> bool:
        raise NotImplementedError

    def _raise_if_cancel_requested(self) -> None:
        raise NotImplementedError

    def _extract_flux_linkage(self, femm: Any, config: MotorConfig, geom: MotorGeometry) -> tuple[float, float, float]:
        raise NotImplementedError  # Provided by FEMMExtractionMixin

    def _extract_torque(self, femm: Any) -> float:
        raise NotImplementedError  # Provided by FEMMExtractionMixin

    def _persist_debug_json(
        self,
        filename: str,
        payload: dict[str, Any],
        solve_cache_dir: Path | None = None,
    ) -> None:
        """Persist a JSON debug artifact to any active debug/cache targets."""
        targets: list[Path] = []
        if solve_cache_dir is not None:
            targets.append(solve_cache_dir / filename)

        debug_dir = getattr(self, "debug_dir", None)
        if debug_dir:
            targets.append(Path(debug_dir) / filename)

        for target in targets:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            except Exception as exc:
                logger.warning(f"[DEBUG] Failed to persist {target.name}: {exc}")

    def _tile_waveform(
        self,
        angles_partial: list[float],
        values_partial: list[float],
        pole_pairs: int,
    ) -> tuple[list[float], list[float]]:
        """Tile a partial waveform (1 pole pitch) to full 360 electrical degrees.

        Exploits periodicity: the torque waveform repeats every pole pitch.
        For an 8-pole motor, 90 electrical degrees = 1 pole pitch.
        """
        period = angles_partial[-1] - angles_partial[0] if len(angles_partial) > 1 else 90.0
        num_tiles = max(1, int(round(360.0 / period)))

        angles_full = []
        values_full = []

        for tile in range(num_tiles):
            offset = tile * period
            # Don't duplicate the boundary point between tiles
            pts = angles_partial[:-1] if tile < num_tiles - 1 else angles_partial
            vals = values_partial[:-1] if tile < num_tiles - 1 else values_partial
            for a, v in zip(pts, vals):
                angles_full.append(a + offset)
                values_full.append(v)

        return angles_full, values_full

    def _compute_back_emf(
        self,
        elec_angles: list[float],
        psi_a: list[float],
        psi_b: list[float],
        psi_c: list[float],
        pole_pairs: int,
    ) -> tuple[list[float], list[float], list[float], list[float]]:
        """Compute back-EMF as e = -dΨ/dθ (S2-04).

        IMPORTANT: Differentiate FIRST on the partial waveform, THEN tile.
        Tiling flux linkage before differentiation creates a discontinuity
        at every tile seam (Ψ at end of sweep != Ψ at start), which causes
        massive dΨ spikes in np.gradient and explodes THD into the thousands.
        Tiling the derivative values avoids this because dΨ/dθ is genuinely
        periodic even when Ψ itself has a DC offset between tile endpoints.
        """
        if len(elec_angles) < 2:
            return elec_angles, psi_a, psi_b, psi_c

        # Step 1: Differentiate on the partial waveform (no tile-seam artifacts)
        angles_np = np.array(elec_angles)
        d_theta = np.gradient(np.radians(angles_np))
        d_theta[d_theta == 0] = 1e-10

        emf_a_partial = list(-np.gradient(np.array(psi_a)) / d_theta)
        emf_b_partial = list(-np.gradient(np.array(psi_b)) / d_theta)
        emf_c_partial = list(-np.gradient(np.array(psi_c)) / d_theta)

        # Step 2: Tile the derivative (periodic, no seam discontinuity)
        angles_full, emf_a = self._tile_waveform(elec_angles, emf_a_partial, pole_pairs)
        _, emf_b = self._tile_waveform(elec_angles, emf_b_partial, pole_pairs)
        _, emf_c = self._tile_waveform(elec_angles, emf_c_partial, pole_pairs)

        return angles_full, emf_a, emf_b, emf_c

    @staticmethod
    def _angle_bucket_key(angle_deg: float) -> int:
        """Quantize an electrical angle for sample deduping/lookup."""
        return int(round(angle_deg * 1000.0))

    def _build_noload_sweep_angles(
        self,
        config: MotorConfig,
        *,
        thd_analysis: bool = False,
    ) -> list[float]:
        """Build the FEMM no-load electrical-angle plan.

        The no-load plan is derived from the FEMM loaded step (4× coarser),
        not from :meth:`effective_step_deg` — that method now returns the
        Native-FEM step, which is 2× denser than FEMM at every tier. Keying
        the FEMM no-load plan off the Native step inadvertently doubled
        FEMM's no-load sweep: at Quick, 9 loaded + 19 no-load = 28 total,
        when it should be 9 + 9 = 18.
        """
        sp = config.solve_params
        quality = sp.solve_quality if sp is not None else "standard"
        min_positions = (
            96 if quality == "fine" else 48
        ) if thd_analysis else 4
        override_raw = os.environ.get(FEMM_BEMF_STEP_ENV)
        if override_raw is not None and override_raw.strip():
            try:
                override_step = float(override_raw)
            except ValueError as exc:
                raise ValueError(f"{FEMM_BEMF_STEP_ENV} must be numeric, got {override_raw!r}") from exc
            if not math.isfinite(override_step) or override_step <= 0.0:
                raise ValueError(f"{FEMM_BEMF_STEP_ENV} must be > 0, got {override_raw!r}")
            num_positions = max(min_positions, int(round(360.0 / override_step)))
            elec_step = 360.0 / num_positions
            return [i * elec_step for i in range(num_positions)]

        base_step = sp.effective_femm_loaded_step_deg() if sp else 7.5
        emf_step = max(15.0, min(90.0, base_step * 4.0))
        num_positions = max(min_positions, int(360.0 / emf_step))
        elec_step = 360.0 / num_positions
        return [i * elec_step for i in range(num_positions)]

    def _estimate_live_back_emf_from_flux_linkage(
        self,
        samples_by_angle: dict[int, tuple[float, float, float, float]],
        omega_elec_rad_s: float,
        target_key: int,
    ) -> tuple[float, float, float] | None:
        """Estimate one live back-EMF sample from solved no-load linkage points."""
        if target_key not in samples_by_angle:
            return None

        ordered_samples = sorted(samples_by_angle.items(), key=lambda item: item[1][0])
        if len(ordered_samples) < 2:
            return (0.0, 0.0, 0.0)

        elec_angles = [angle for _, (angle, _, _, _) in ordered_samples]
        flux_a = [psi_a for _, (_, psi_a, _, _) in ordered_samples]
        flux_b = [psi_b for _, (_, _, psi_b, _) in ordered_samples]
        flux_c = [psi_c for _, (_, _, _, psi_c) in ordered_samples]
        emf_a, emf_b, emf_c = self._compute_back_emf_scaled(
            flux_a,
            flux_b,
            flux_c,
            elec_angles,
            omega_elec_rad_s,
            basis_label="electrical-live",
            log_result=False,
        )

        for idx, (sample_key, _) in enumerate(ordered_samples):
            if sample_key == target_key:
                return (
                    float(emf_a[idx]),
                    float(emf_b[idx]),
                    float(emf_c[idx]),
                )
        return None

    @staticmethod
    def _calculate_thd_fft(waveform: list[float]) -> float:
        """Calculate THD using actual FFT.

        THD = sqrt(sum(V_n^2 for n>=2)) / V_1 × 100%

        Note: THD can legitimately exceed 100% for highly non-sinusoidal
        waveforms (e.g. square waves ~48%, trapezoidal higher). With very
        few sample points (<8), FFT resolution is poor — treat as estimate.
        """
        if not waveform or len(waveform) < 4:
            return 0.0

        try:
            fft_vals = np.fft.rfft(waveform)
            magnitudes = np.abs(fft_vals)

            if len(magnitudes) < 2:
                return 0.0

            fundamental = magnitudes[1]  # First harmonic
            if fundamental < 1e-10:
                return 0.0

            # Only include harmonics up to Nyquist/2 for reliability
            max_harmonic = min(len(magnitudes), max(8, len(magnitudes) // 2))
            harmonics_power = float(np.sum(magnitudes[2:max_harmonic] ** 2))
            thd = math.sqrt(harmonics_power) / fundamental * 100

            tagged_log(f"[THD] fundamental={fundamental:.4f}, harmonics_power={harmonics_power:.4f}, THD={thd:.1f}%, samples={len(waveform)}")
            return thd
        except Exception:
            return 0.0

    @staticmethod
    def _resolved_phase_current_peak(config: MotorConfig) -> float:
        """Resolve solve current into a peak phase current."""
        peak = resolve_phase_current_peak(config)
        if peak > 0.0:
            return peak
        return 50.0

    @staticmethod
    def _rectangular_slot_wire_area(config: MotorConfig) -> float:
        """Legacy rectangular slot estimate of the wire cross-section.

        Fallback for configs whose geometry IR carries no SlotWinding regions
        (e.g. the slotless no-load diagnostic), where the polygon-based sizing
        in ``_winding_conductor_geometry`` has no slot area to work from.
        """
        stator = config.stator
        winding = config.winding
        radial_depth_m = (stator.OD_mm - stator.ID_mm) / 2 / 1000
        tooth_pitch_m = math.pi * stator.ID_mm / stator.slot_count / 1000
        slot_area_m2 = radial_depth_m * tooth_pitch_m * 0.55 * 0.6
        fill_factor = 0.45
        total_conductors_per_slot = winding.turns_per_coil
        return max(1e-8, slot_area_m2 * fill_factor / total_conductors_per_slot)

    @staticmethod
    def _winding_conductor_geometry(config: MotorConfig) -> tuple[float, float]:
        """Size the winding wire and mean turn length from the design.

        Wire cross-section comes from the exact slot polygon area in the shared
        geometry IR combined with the design-tracking fill factor reported by
        the preview winding-layout metadata: because that fill factor scales
        with conductor count, the implied wire gauge follows the design and
        resistance responds linearly (not quadratically) to turn count.

        End turns are coil-span aware: distributed coils get a semicircular
        bundle spanning the actual (full-pitch) coil pitch, concentrated coils
        a tooth-hugging fold at one tooth-pitch scale.

        Returns (wire_area_m2, mean_turn_length_m).
        """
        # Local imports avoid a module-level cycle: backend.preview pulls in
        # geometry/validation modules that must not depend on femm_postprocess.
        from backend.geometry_ir import build_geometry_ir
        from backend.preview import _generate_winding_layout
        from backend.winding_utils import resolve_distributed_coil_span

        stator = config.stator
        winding = config.winding
        total_conductors_per_slot = winding.turns_per_coil

        report = build_geometry_ir(config).validation_report()
        if report.slot_winding_area_mm2 > 0:
            slot_area_m2 = report.slot_winding_area_mm2 / stator.slot_count * 1e-6
            _, metadata = _generate_winding_layout(
                stator.slot_count,
                config.rotor.pole_count,
                winding.type,
                winding.turns_per_coil,
                stator.ID_mm,
                winding.layers,
                winding.parallel_paths,
                winding.coil_span,
            )
            fill_factor = float(metadata["fill_factor"])
            wire_area_m2 = max(
                1e-8, slot_area_m2 * fill_factor / total_conductors_per_slot
            )
        else:
            # No SlotWinding regions in the IR (slotless diagnostic): fall
            # back to the legacy rectangular estimate.
            wire_area_m2 = FEMMPostprocessMixin._rectangular_slot_wire_area(config)

        stack_m = stator.stack_length_mm / 1000
        radial_depth_m = (stator.OD_mm - stator.ID_mm) / 2 / 1000
        # Slot pitch at the end-winding (mean stator) radius.
        slot_pitch_end_m = (
            math.pi * (stator.ID_mm + radial_depth_m * 1000) / stator.slot_count / 1000
        )
        if winding.type == "distributed":
            # Distributed end turns span the configured chorded coil pitch.
            coil_span_slots = float(
                resolve_distributed_coil_span(
                    stator.slot_count,
                    config.rotor.pole_count,
                    winding.coil_span,
                )
            )
        else:
            # Concentrated coil folds around a single tooth.
            coil_span_slots = 1.0
        end_turn_m = math.pi * coil_span_slots * slot_pitch_end_m / 2
        mean_turn_length_m = 2 * stack_m + 2 * end_turn_m
        return wire_area_m2, mean_turn_length_m

    @staticmethod
    def _series_turns_per_phase(config: MotorConfig) -> float:
        """Derive series turns per phase from the winding layout.

        S45-02/DW-04: ``layers`` split a physical slot bundle; they do not
        multiply terminal coils. Count one layer of the full-pitch layout so
        coils per phase = physical slots-per-phase / 2.
        """
        from backend.preview import _generate_winding_layout

        stator = config.stator
        winding = config.winding
        layout, _ = _generate_winding_layout(
            stator.slot_count,
            config.rotor.pole_count,
            winding.type,
            winding.turns_per_coil,
            stator.ID_mm,
            winding.layers,
            winding.parallel_paths,
            winding.coil_span,
        )
        slots_phase_a = float(
            sum(1 for slot in layout if slot.phase == "A" and slot.layer == 1)
        )
        if slots_phase_a <= 0:
            slots_phase_a = stator.slot_count / 3
        coils_per_phase = slots_phase_a / 2
        return winding.turns_per_coil * coils_per_phase

    @staticmethod
    def _compute_phase_resistance(config: MotorConfig) -> float:
        """Estimate per-phase winding resistance from geometry and layout."""
        winding = config.winding
        conductor = config.materials.conductor if config.materials else "copper"
        cond_props: dict[str, Any] = CONDUCTOR_PROPERTIES.get(conductor, CONDUCTOR_PROPERTIES["copper"])
        resistivity = 1.0 / float(cond_props["conductivity_S_m"])  # Ω·m

        wire_area_m2, mean_turn_length_m = (
            FEMMPostprocessMixin._winding_conductor_geometry(config)
        )
        turns_per_phase = FEMMPostprocessMixin._series_turns_per_phase(config)
        # p parallel paths: turns_per_phase / p series turns per path, p paths
        # in parallel — net resistance divides by p² relative to all-series.
        parallel = winding.parallel_paths
        total_wire_length = turns_per_phase * mean_turn_length_m
        return resistivity * total_wire_length / (wire_area_m2 * parallel**2)

    @staticmethod
    def _compute_copper_loss(config: MotorConfig, phase_resistance_ohm: float) -> float:
        """Compute 3-phase copper loss from peak phase current and resistance."""
        i_peak = FEMMPostprocessMixin._resolved_phase_current_peak(config)
        i_rms = i_peak / math.sqrt(2)
        return 3 * i_rms**2 * phase_resistance_ohm

    @staticmethod
    def _split_copper_loss_active_end(
        config: MotorConfig,
        copper_loss_w: float,
    ) -> tuple[float, float, float]:
        """Split total winding I²R by active and end-turn conductor length.

        The resistance model already derives a geometry-aware mean-turn length:
        two active axial legs plus two coil-span-aware end turns. Uniform wire
        area/resistivity/current make I²R proportional to conductor length, so
        this split adds no thermal-fit parameter and does not use ORNL data.

        Returns ``(active_w, end_w, active_fraction)`` as full-machine values.
        """
        total_w = float(copper_loss_w)
        if total_w < 0.0:
            raise ValueError("copper loss must be non-negative for axial split")
        _, mean_turn_length_m = FEMMPostprocessMixin._winding_conductor_geometry(
            config
        )
        active_length_m = 2.0 * float(config.stator.stack_length_mm) * 1.0e-3
        if mean_turn_length_m <= 0.0:
            raise ValueError("mean turn length must be positive for copper split")
        active_fraction = min(1.0, max(0.0, active_length_m / mean_turn_length_m))
        active_w = total_w * active_fraction
        end_w = total_w - active_w
        return active_w, end_w, active_fraction

    @staticmethod
    def _estimate_iron_masses(config: MotorConfig) -> tuple[float, float, float, float]:
        """Estimate stator/rotor iron masses plus stator teeth/yoke split."""
        stator = config.stator
        steel_grade = config.materials.stator_steel if config.materials else "M19"
        rotor_steel_grade = config.materials.rotor_steel if config.materials else steel_grade
        steel: dict[str, Any] = STEEL_PROPERTIES.get(steel_grade, STEEL_PROPERTIES["M19"])
        rotor_steel: dict[str, Any] = STEEL_PROPERTIES.get(rotor_steel_grade, steel)
        stack_m = stator.stack_length_mm / 1000

        stator_OD_m = stator.OD_mm / 1000
        stator_ID_m = stator.ID_mm / 1000
        yoke_thick_m = stator.yoke_thickness_mm / 1000
        yoke_outer_r = stator_OD_m / 2
        yoke_inner_r = yoke_outer_r - yoke_thick_m
        yoke_area = math.pi * (yoke_outer_r**2 - yoke_inner_r**2)
        yoke_mass = yoke_area * stack_m * float(steel["density_kg_m3"])

        teeth_outer_r = yoke_inner_r
        teeth_inner_r = stator_ID_m / 2
        teeth_area = math.pi * (teeth_outer_r**2 - teeth_inner_r**2) * 0.45
        teeth_mass = teeth_area * stack_m * float(steel["density_kg_m3"])
        stator_mass = yoke_mass + teeth_mass

        rotor_OD_m = config.rotor.OD_mm / 1000
        shaft_r = rotor_OD_m / 2 * 0.3
        rotor_area = math.pi * ((rotor_OD_m / 2) ** 2 - shaft_r**2)
        rotor_mass = rotor_area * stack_m * float(rotor_steel["density_kg_m3"]) * 0.85
        return stator_mass, rotor_mass, teeth_mass, yoke_mass

    @staticmethod
    def _build_loss_breakdown(
        config: MotorConfig,
        avg_torque: float,
        phase_resistance_ohm: float,
        copper_loss_w: float,
        core_loss_w: float,
        hysteresis_loss_w: float,
        eddy_current_loss_w: float,
        stator_core_mass_kg: float,
        rotor_core_mass_kg: float,
    ) -> LossBreakdown:
        """Assemble a full loss breakdown from already-computed components."""
        sp = config.solve_params
        rpm = sp.rated_speed_rpm if sp else 3000
        omega = rpm * 2 * math.pi / 60
        P_mech = abs(avg_torque) * omega
        P_total = copper_loss_w + core_loss_w
        P_input = P_mech + P_total
        copper_total_rounded = round(copper_loss_w, 2)
        active_copper_w, _, active_copper_fraction = (
            FEMMPostprocessMixin._split_copper_loss_active_end(
                config,
                copper_total_rounded,
            )
        )
        active_copper_rounded = round(active_copper_w, 2)
        # Subtract after rounding so serialized active + end equals serialized
        # total exactly (important for artifact power bookkeeping).
        end_copper_rounded = round(
            copper_total_rounded - active_copper_rounded,
            2,
        )
        return LossBreakdown(
            copper_loss_W=copper_total_rounded,
            active_copper_loss_W=active_copper_rounded,
            end_winding_copper_loss_W=end_copper_rounded,
            active_copper_fraction=active_copper_fraction,
            core_loss_W=round(core_loss_w, 2),
            hysteresis_loss_W=round(hysteresis_loss_w, 2),
            eddy_current_loss_W=round(eddy_current_loss_w, 2),
            total_loss_W=round(P_total, 2),
            mechanical_power_W=round(P_mech, 2),
            input_power_W=round(P_input, 2),
            stator_core_mass_kg=round(stator_core_mass_kg, 4),
            rotor_core_mass_kg=round(rotor_core_mass_kg, 4),
            phase_resistance_ohm=round(phase_resistance_ohm, 5),
        )

    @staticmethod
    def _compute_loss_breakdown(config: MotorConfig, avg_torque: float, peak_B_teeth: float, peak_B_yoke: float) -> LossBreakdown:
        """Compute detailed loss breakdown from motor config and solve results.

        Copper loss: I²R per phase, calculated from winding geometry.
        Core loss: Modified Steinmetz equation using per-grade coefficients.
        """
        sp = config.solve_params
        rpm = sp.rated_speed_rpm if sp else 3000
        i_phase = FEMMPostprocessMixin._resolved_phase_current_peak(config)
        f_elec = rpm * config.rotor.pole_count / 120  # electrical frequency
        phase_resistance_ohm = FEMMPostprocessMixin._compute_phase_resistance(config)
        i_rms = i_phase / math.sqrt(2)
        P_copper = 3 * i_rms**2 * phase_resistance_ohm

        # ── Core loss via modified Steinmetz ────────────────────────────
        steel_grade = config.materials.stator_steel if config.materials else "M19"
        steel: dict[str, Any] = STEEL_PROPERTIES.get(steel_grade, STEEL_PROPERTIES["M19"])
        k_h: float = float(steel.get("steinmetz_kh", 0.0275))
        k_e: float = float(steel.get("steinmetz_ke", 1.83e-5))
        alpha: float = float(steel.get("steinmetz_alpha", 1.8))
        stator_mass, rotor_mass, teeth_mass, yoke_mass = FEMMPostprocessMixin._estimate_iron_masses(config)

        # Steinmetz: P = (k_h × f × B^alpha + k_e × f^2 × B^2) × mass
        B_teeth = max(peak_B_teeth, 0.01)
        B_yoke = max(peak_B_yoke, 0.01)

        P_hyst_teeth = k_h * f_elec * (B_teeth**alpha) * teeth_mass
        P_eddy_teeth = k_e * (f_elec**2) * (B_teeth**2) * teeth_mass
        P_hyst_yoke = k_h * f_elec * (B_yoke**alpha) * yoke_mass
        P_eddy_yoke = k_e * (f_elec**2) * (B_yoke**2) * yoke_mass

        P_hysteresis = P_hyst_teeth + P_hyst_yoke
        P_eddy = P_eddy_teeth + P_eddy_yoke
        P_core = P_hysteresis + P_eddy

        # Build factor: real core losses are typically 1.5-2× analytical
        # due to manufacturing stress, cut edges, non-uniform flux
        build_factor = 1.5
        P_core *= build_factor
        P_hysteresis *= build_factor
        P_eddy *= build_factor

        return FEMMPostprocessMixin._build_loss_breakdown(
            config,
            avg_torque,
            phase_resistance_ohm,
            P_copper,
            P_core,
            P_hysteresis,
            P_eddy,
            stator_mass,
            rotor_mass,
        )

    @staticmethod
    def _estimate_efficiency(
        config: MotorConfig, avg_torque: float, peak_B_teeth: float = 0.0, peak_B_yoke: float = 0.0
    ) -> tuple[float, LossBreakdown | None]:
        """Estimate motor efficiency and return loss breakdown.

        Returns (efficiency_pct, LossBreakdown or None).
        """
        # Guard NaN/inf explicitly — `abs(nan) < 1e-6` evaluates False
        # (every NaN comparison is False), which prior to this guard let
        # NaN avg_torque flow into _compute_loss_breakdown and crash the
        # Pydantic LossBreakdown construction at the `round(nan, 2)` step.
        # Upstream FEMM torque-extractor dropouts (recorded as math.nan)
        # are the realistic source of a non-finite avg_torque, but keep
        # this guard even with the femm_solver.py nanmean fix — it's
        # cheap defense-in-depth and future callers may not bother.
        if (not math.isfinite(avg_torque)) or abs(avg_torque) < 1e-6 or config.solve_params is None:
            return 0.0, None

        breakdown = FEMMPostprocessMixin._compute_loss_breakdown(config, avg_torque, peak_B_teeth, peak_B_yoke)
        efficiency = breakdown.mechanical_power_W / breakdown.input_power_W * 100 if breakdown.input_power_W > 0 else 0.0
        return min(max(efficiency, 0), 100), breakdown

    @staticmethod
    def _compute_weight_inertia(config: MotorConfig) -> WeightInertia:
        """Compute motor weight breakdown and rotor moment of inertia.

        Calculates mass of each active component (stator iron, rotor iron,
        magnets, copper) from geometry and material densities. Rotor inertia
        is computed as the sum of cylindrical shell contributions.
        """
        stator = config.stator
        rotor = config.rotor
        winding = config.winding
        materials = config.materials

        # Material densities
        steel_grade = materials.stator_steel if materials else "M19"
        steel: dict[str, Any] = STEEL_PROPERTIES.get(steel_grade, STEEL_PROPERTIES["M19"])
        steel_density: float = float(steel["density_kg_m3"])

        rotor_steel_grade = materials.rotor_steel if materials else "M19"
        rotor_steel: dict[str, Any] = STEEL_PROPERTIES.get(rotor_steel_grade, STEEL_PROPERTIES["M19"])
        rotor_steel_density: float = float(rotor_steel["density_kg_m3"])

        magnet_grade = materials.magnet_grade if materials else "N42"
        magnet_props: dict[str, Any] = MAGNET_PROPERTIES.get(magnet_grade, MAGNET_PROPERTIES["N42"])
        magnet_density: float = float(magnet_props["density_kg_m3"])

        conductor = materials.conductor if materials else "copper"
        cond_props: dict[str, Any] = CONDUCTOR_PROPERTIES.get(conductor, CONDUCTOR_PROPERTIES["copper"])
        conductor_density: float = float(cond_props["density_kg_m3"])

        stack_m = stator.stack_length_mm / 1000

        # ── Stator iron mass (yoke + teeth) ────────────────────────────
        stator_OD_m = stator.OD_mm / 1000
        stator_ID_m = stator.ID_mm / 1000
        yoke_thick_m = stator.yoke_thickness_mm / 1000
        yoke_outer_r = stator_OD_m / 2
        yoke_inner_r = yoke_outer_r - yoke_thick_m
        yoke_area = math.pi * (yoke_outer_r**2 - yoke_inner_r**2)
        yoke_mass = yoke_area * stack_m * steel_density

        teeth_outer_r = yoke_inner_r
        teeth_inner_r = stator_ID_m / 2
        teeth_area = math.pi * (teeth_outer_r**2 - teeth_inner_r**2) * 0.45
        teeth_mass = teeth_area * stack_m * steel_density
        stator_core_mass = yoke_mass + teeth_mass

        # ── Magnet mass ────────────────────────────────────────────────
        # Each magnet: approximate as rectangular block
        mag_thick_m = rotor.magnet_thickness_mm / 1000
        mag_width_m = rotor.magnet_width_mm / 1000
        magnet_volume_each = mag_thick_m * mag_width_m * stack_m
        pole_count = rotor.pole_count
        total_magnet_mass = magnet_volume_each * pole_count * magnet_density

        # ── Rotor iron mass (excluding magnets) ────────────────────────
        rotor_OD_m = rotor.OD_mm / 1000
        shaft_r = rotor_OD_m / 2 * 0.3  # shaft ~30% of rotor OD
        rotor_total_area = math.pi * ((rotor_OD_m / 2) ** 2 - shaft_r**2)
        # Subtract magnet cross-section area from rotor
        magnet_cs_area = mag_thick_m * mag_width_m * pole_count
        rotor_iron_area = max(0, rotor_total_area - magnet_cs_area)
        rotor_core_mass = rotor_iron_area * stack_m * rotor_steel_density

        # ── Copper mass ────────────────────────────────────────────────
        # Same wire sizing and coil-span-aware mean turn as the phase
        # resistance estimate, so R and copper mass stay consistent.
        wire_area_m2, mean_turn_length_m = (
            FEMMPostprocessMixin._winding_conductor_geometry(config)
        )
        total_coils = stator.slot_count / 2
        total_wire_length = winding.turns_per_coil * total_coils * mean_turn_length_m
        copper_mass = total_wire_length * wire_area_m2 * conductor_density

        # ── Total mass ─────────────────────────────────────────────────
        total_mass = stator_core_mass + rotor_core_mass + total_magnet_mass + copper_mass

        # ── Rotor moment of inertia ────────────────────────────────────
        # J = (1/2) × m × (r_outer² + r_inner²) for a cylindrical shell
        rotor_outer_r = rotor_OD_m / 2
        # Rotor iron shell
        J_rotor_iron = 0.5 * rotor_core_mass * (rotor_outer_r**2 + shaft_r**2)
        # Magnets: approximate at outer surface of rotor
        mag_inner_r = rotor_outer_r - mag_thick_m
        J_magnets = 0.5 * total_magnet_mass * (rotor_outer_r**2 + mag_inner_r**2)
        rotor_inertia = J_rotor_iron + J_magnets

        # ── Active volume (stator OD envelope) ─────────────────────────
        active_volume_m3 = math.pi * (stator_OD_m / 2) ** 2 * stack_m
        active_volume_cm3 = active_volume_m3 * 1e6

        return WeightInertia(
            stator_core_kg=round(stator_core_mass, 4),
            rotor_core_kg=round(rotor_core_mass, 4),
            magnet_kg=round(total_magnet_mass, 4),
            copper_kg=round(copper_mass, 4),
            total_mass_kg=round(total_mass, 4),
            rotor_inertia_kg_m2=round(rotor_inertia, 6),
            stack_length_mm=stator.stack_length_mm,
            active_volume_cm3=round(active_volume_cm3, 1),
        )

    @staticmethod
    def _compute_torque_speed_envelope(
        config: MotorConfig,
        avg_torque: float,
        back_emf_V: float,
    ) -> TorqueSpeedEnvelope | None:
        """Compute torque-speed envelope from single operating point.

        Uses voltage-limited and current-limited constraints to build
        the constant-torque + field-weakening characteristic curve.
        Assumes a simple surface PM model with no reluctance torque.

        Args:
            config: Motor configuration
            avg_torque: Average torque at rated current and rated speed [Nm]
            back_emf_V: Back-EMF fundamental voltage at rated speed [V]
        """
        sp = config.solve_params
        if sp is None or avg_torque <= 0 or back_emf_V <= 0:
            return None

        rated_rpm = float(sp.rated_speed_rpm)
        if rated_rpm <= 0:
            return None
        pole_pairs = config.rotor.pole_count // 2

        # Back-EMF constant: Ke = V_peak / omega_e
        omega_rated = rated_rpm * 2 * math.pi / 60
        omega_e_rated = omega_rated * pole_pairs
        Ke = back_emf_V / omega_e_rated if omega_e_rated > 0 else 0.01

        # Estimate phase inductance from back-EMF and geometry
        # L ≈ V_emf / (omega_e × I_rated) as rough approximation
        I_rated = sp.current_amplitude_A / math.sqrt(2)  # RMS
        L_phase = back_emf_V / (omega_e_rated * I_rated * 3) if omega_e_rated * I_rated > 0 else 1e-4

        # DC bus voltage estimate: sqrt(2) × V_emf × 1.15 headroom at rated
        V_dc = back_emf_V * math.sqrt(2) * 1.15
        V_phase_max = V_dc / math.sqrt(3)  # line-to-neutral for SVPWM

        # Base speed: where back-EMF equals available voltage
        # V_phase = Ke × omega_e_base + I × X_s ≈ Ke × omega_e_base (approx)
        omega_e_base = V_phase_max / (Ke + L_phase * I_rated) if (Ke + L_phase * I_rated) > 0 else omega_e_rated
        base_rpm = omega_e_base / pole_pairs * 60 / (2 * math.pi)
        base_rpm = min(base_rpm, rated_rpm * 3)  # cap at 3× rated

        # Max speed: where torque drops to zero (all voltage for back-EMF)
        omega_e_max = V_phase_max / Ke if Ke > 0 else omega_e_base * 3
        max_rpm = omega_e_max / pole_pairs * 60 / (2 * math.pi)
        max_rpm = min(max_rpm, rated_rpm * 5)  # cap at 5× rated

        # Build envelope: 50 speed points
        n_points = 50
        speeds = []
        torques = []
        powers = []

        for i in range(n_points):
            rpm = (max_rpm / (n_points - 1)) * i if n_points > 1 else rated_rpm
            omega = rpm * 2 * math.pi / 60

            if rpm <= base_rpm:
                # Constant torque region
                T = avg_torque
            else:
                # Field weakening: torque ≈ rated_torque × (base_speed / speed)
                T = avg_torque * (base_rpm / rpm) if rpm > 0 else 0

            P = T * omega
            speeds.append(round(rpm, 1))
            torques.append(round(T, 3))
            powers.append(round(P, 1))

        peak_power = max(powers) if powers else 0

        return TorqueSpeedEnvelope(
            speed_rpm=speeds,
            torque_Nm=torques,
            power_W=powers,
            base_speed_rpm=round(base_rpm, 1),
            max_speed_rpm=round(max_rpm, 1),
            peak_power_W=round(peak_power, 1),
            rated_torque_Nm=round(avg_torque, 3),
        )

    @staticmethod
    def _compute_torque_speed_sweep(
        config: MotorConfig,
        avg_torque: float,
    ) -> TorqueSpeedEnvelope | None:
        """Build a solver-derived current-controlled torque-speed sweep.

        The electromagnetic torque comes from the completed field solve. Speed
        points are sampled up to the requested rated speed and shaft power is
        computed as ``T * omega_mech``. This deliberately does not fabricate a
        voltage-limited field-weakening knee from one operating point.
        """
        sp = config.solve_params
        if sp is None or avg_torque <= 0:
            return None

        max_rpm = float(sp.rated_speed_rpm)
        if max_rpm <= 0:
            return None

        n_points = 25
        speeds: list[float] = []
        torques: list[float] = []
        powers: list[float] = []

        for i in range(n_points):
            rpm = (max_rpm / (n_points - 1)) * i if n_points > 1 else max_rpm
            omega = rpm * 2 * math.pi / 60
            power = avg_torque * omega
            speeds.append(round(rpm, 1))
            torques.append(round(avg_torque, 3))
            powers.append(round(power, 1))

        peak_power = max(powers) if powers else 0

        return TorqueSpeedEnvelope(
            method="solver_current_sweep",
            speed_rpm=speeds,
            torque_Nm=torques,
            power_W=powers,
            base_speed_rpm=round(max_rpm, 1),
            max_speed_rpm=round(max_rpm, 1),
            peak_power_W=round(peak_power, 1),
            rated_torque_Nm=round(avg_torque, 3),
        )

    @staticmethod
    def _compute_thermal_estimate(
        config: MotorConfig,
        loss_breakdown: LossBreakdown,
        ambient_C: float = 40.0,
    ) -> ThermalEstimate:
        """Lumped-parameter steady-state thermal estimate.

        Thermal network: winding → slot insulation → stator teeth →
        stator yoke → housing → ambient. Core loss injected at stator
        iron node. Uses typical thermal resistances scaled by geometry.

        Insulation class H limit: 180°C winding hot-spot.
        """
        stator = config.stator
        sp = config.solve_params

        stack_m = stator.stack_length_mm / 1000
        stator_OD_m = stator.OD_mm / 1000
        stator_ID_m = stator.ID_mm / 1000

        # Thermal contact areas
        slot_perimeter_m = 2 * ((stator_OD_m - stator_ID_m) / 2 + stator_ID_m * math.pi / stator.slot_count * 0.55)
        slot_contact_area = slot_perimeter_m * stack_m * stator.slot_count  # total slot liner area
        housing_area = math.pi * stator_OD_m * stack_m  # outer cylindrical surface

        # Thermal resistances [K/W] — typical values scaled by geometry
        # Slot liner: ~0.2 mm kapton, k ≈ 0.12 W/mK
        liner_thickness = 0.2e-3  # m
        k_liner = 0.12  # W/mK
        R_slot_liner = liner_thickness / (k_liner * max(slot_contact_area, 1e-6))

        # Stator iron conduction (radial, teeth to yoke): k_steel ≈ 30 W/mK
        radial_path = (stator_OD_m - stator_ID_m) / 4  # half the radial depth
        iron_area = math.pi * (stator_OD_m + stator_ID_m) / 2 * stack_m * 0.5  # effective area
        R_iron = radial_path / (30.0 * max(iron_area, 1e-6))

        # Housing-to-ambient: natural convection h ≈ 15 W/m²K (TEFC = 25-40)
        h_conv = 20.0  # W/m²K — moderate cooling
        R_housing = 1.0 / (h_conv * max(housing_area, 1e-6))

        # Temperature rises
        # Copper loss heats winding → flows through slot liner → iron → housing → ambient
        # Core loss heats iron → flows to housing → ambient
        P_copper = loss_breakdown.copper_loss_W
        P_core = loss_breakdown.core_loss_W

        # Stator iron temperature rise
        delta_T_iron = (P_copper + P_core) * R_housing + P_core * R_iron
        stator_temp = ambient_C + delta_T_iron

        # Winding temperature rise (on top of iron)
        delta_T_winding = P_copper * (R_slot_liner + R_iron) + delta_T_iron
        winding_temp = ambient_C + delta_T_winding

        # Magnet temperature (heated by rotor losses, roughly follows iron temp)
        # Rotor losses are small fraction — magnet temp ≈ iron temp + small margin
        magnet_temp = stator_temp + 5.0  # rough estimate, rotor slightly hotter

        # Insulation class H: 180°C limit
        insulation_limit_C = 180.0
        thermal_margin = insulation_limit_C - winding_temp

        # Max continuous current: scale from rated current using thermal headroom
        # T_rise ∝ I² → I_max = I_rated × sqrt(T_max_rise / T_actual_rise)
        i_rated = sp.current_amplitude_A / math.sqrt(2) if sp else 35.0
        winding_rise = max(delta_T_winding, 1.0)
        max_rise_allowed = insulation_limit_C - ambient_C
        i_max_continuous = i_rated * math.sqrt(max_rise_allowed / winding_rise)
        # Cap at 2× rated to avoid absurd values
        i_max_continuous = min(i_max_continuous, i_rated * 2.0)

        return ThermalEstimate(
            winding_temp_C=round(winding_temp, 1),
            stator_core_temp_C=round(stator_temp, 1),
            magnet_temp_C=round(magnet_temp, 1),
            ambient_temp_C=ambient_C,
            winding_temp_rise_K=round(delta_T_winding, 1),
            max_continuous_current_A=round(i_max_continuous, 1),
            insulation_class="H",
            thermal_margin_K=round(thermal_margin, 1),
        )

    @staticmethod
    def _compute_demag_check(
        config: MotorConfig,
        peak_B_teeth: float = 0.0,
        magnet_temperature_C: float | None = None,
        magnet_element_B_T: list[float] | None = None,
    ) -> DemagCheck:
        """Check demagnetization risk at rated operating point.

        Estimates the magnet operating point under d-axis demagnetizing
        current and compares to the B-H curve knee point. Uses a simple
        magnetic circuit model.

        S48-03: pass ``magnet_temperature_C`` to derate Br/Hci. Pass
        ``magnet_element_B_T`` (per-element |B| in magnet regions) to use
        the worst-case element field instead of the circuit estimate.
        """
        from backend.thermal.magnet_temperature import derate_magnet_properties

        materials = config.materials
        magnet_grade = materials.magnet_grade if materials else "N42"
        # Defense in depth: MotorConfig already constrains magnet_grade via
        # Literal, but internal callers / model_construct can bypass Pydantic.
        if magnet_grade not in MAGNET_PROPERTIES:
            raise ValueError(f"unknown magnet_grade={magnet_grade!r}")
        mag_props: dict[str, Any] = MAGNET_PROPERTIES[magnet_grade]

        Br_room = float(mag_props["remanence_T"])
        mu_r = float(mag_props.get("relative_permeability", 1.05))
        # Room-temp path must not require Br(T)/Hc(T) coefficients — derating
        # at 20 °C is a no-op and previously crashed every solve when a grade
        # was in MAGNET_PROPERTIES but missing from _TEMP_COEFFS (EM blast radius).
        if magnet_temperature_C is None:
            Br = Br_room
            Hci = float(mag_props["coercivity_bH_kA_m"])
            temp_c = None
        else:
            temp_c = float(magnet_temperature_C)
            derated = derate_magnet_properties(mag_props, magnet_grade, temp_c)
            Br = float(derated["remanence_T"])
            Hci = float(derated["coercivity_kA_m"])

        # Magnet thickness and airgap
        mag_thick_m = config.rotor.magnet_thickness_mm / 1000
        airgap_m = (config.stator.ID_mm - config.rotor.OD_mm) / 2 / 1000

        # Permeance coefficient: Pc = lm / (mu_r × g)
        # Higher Pc = safer operating point
        Pc = mag_thick_m / (mu_r * max(airgap_m, 0.5e-3))

        # Operating B under no-load: B_op = Br × Pc / (1 + Pc)
        B_op_noload = Br * Pc / (1 + Pc)

        # Demagnetizing effect of stator current (d-axis)
        # Approximate: the armature reaction reduces B by a fraction
        # proportional to current and inversely to magnet thickness
        sp = config.solve_params
        I_d = sp.current_amplitude_A if sp else 50.0
        # Armature reaction MMF: N×I / pole-pair-gap
        # Simplified: delta_B ≈ mu0 × N × I / (2 × lm) × reduction_factor
        mu0 = 4 * math.pi * 1e-7
        turns_per_coil = config.winding.turns_per_coil
        delta_B = mu0 * turns_per_coil * I_d / (2 * mag_thick_m) * 0.3
        # 0.3 factor: not all armature MMF is demagnetizing

        B_operating = max(0, B_op_noload - delta_B)
        if magnet_element_B_T:
            # Worst-case element field in the magnet (lower B ⇒ closer to knee).
            B_operating = min(B_operating, min(magnet_element_B_T))

        # Knee point: where B drops to ~0.1 × Br for NdFeB at room temp
        # More precisely: B_knee ≈ Br + mu0 × mu_r × Hci × 1000 (H in A/m)
        B_knee = max(0, Br + mu0 * mu_r * Hci * 1000)

        # Margin
        margin_pct = (B_operating - B_knee) / Br * 100 if Br > 0 else 0
        knee_crossed = B_operating <= B_knee

        if margin_pct > 20:
            risk = "safe"
        elif margin_pct > 5:
            risk = "marginal"
        else:
            risk = "at_risk"

        return DemagCheck(
            magnet_operating_B_T=round(B_operating, 4),
            magnet_knee_B_T=round(B_knee, 4),
            remanence_T=round(Br, 4),
            coercivity_kA_m=round(Hci, 1),
            demagnetization_margin_pct=round(margin_pct, 1),
            risk_level=risk,
            magnet_temperature_C=temp_c,
            remanence_room_temp_T=Br_room if temp_c is not None else None,
            knee_crossed=knee_crossed,
        )

    @staticmethod
    def _compute_slot_fill_check(config: MotorConfig) -> SlotFillCheck:
        """Check whether specified winding physically fits in the slot.

        Computes the slot fill factor from geometry and flags infeasible
        configurations (fill > 0.65 for random-wound, typical limit).
        """
        stator = config.stator
        winding = config.winding

        # Slot area (simplified trapezoid)
        stator_ID_m = stator.ID_mm / 1000
        radial_depth_m = (stator.OD_mm - stator.ID_mm) / 2 / 1000 - stator.yoke_thickness_mm / 1000
        tooth_pitch_m = math.pi * stator_ID_m / stator.slot_count
        slot_width_m = tooth_pitch_m - stator.tooth_width_mm / 1000
        slot_area_m2 = max(1e-8, radial_depth_m * slot_width_m)
        slot_area_mm2 = slot_area_m2 * 1e6

        # Conductor cross-section per physical slot. Layers split the bundle;
        # they do not multiply conductors.
        conductors_per_slot = winding.turns_per_coil

        # Assume wire gauge fills available area with fill factor
        # Back-calculate wire area from a typical range
        # For random wound: max fill ≈ 0.45-0.65
        # Wire area = slot_area × fill_factor / conductors
        # We want to check if desired fill is feasible
        # Assume a standard wire gauge based on current
        sp = config.solve_params
        I_rms = (sp.current_amplitude_A / math.sqrt(2)) if sp else 35.0
        # Current density J = 5-10 A/mm² typical
        J_target = 7.0  # A/mm² moderate
        wire_area_mm2 = I_rms / (J_target * winding.parallel_paths)
        total_wire_mm2 = wire_area_mm2 * conductors_per_slot

        fill = total_wire_mm2 / slot_area_mm2 if slot_area_mm2 > 0 else 999
        max_fill = 0.65  # practical limit for random wound

        return SlotFillCheck(
            slot_area_mm2=round(slot_area_mm2, 2),
            wire_area_mm2=round(total_wire_mm2, 2),
            fill_factor=round(fill, 4),
            max_fill_factor=max_fill,
            feasible=fill <= max_fill,
            conductors_per_slot=conductors_per_slot,
        )

    # ── Sprint 4 Methods ──────────────────────────────────────────────────

    def _run_single_noload_position(
        self,
        config: MotorConfig,
        geom: MotorGeometry,
        femm,
        elec_angle_deg: float,
        *,
        solve_cache_dir: Path | None = None,
        cache_prefix: str = "noload",
    ) -> tuple[float, float, float]:
        """Solve one no-load FEMM position and return phase flux linkage."""
        pole_pairs = max(1, config.rotor.pole_count // 2)
        mech_angle_rad = math.radians(elec_angle_deg / pole_pairs)
        noload_fem_path = get_wine_compatible_path("openem_noload.fem")
        noload_fem_native_path = Path(get_native_path_from_wine_path(noload_fem_path))

        self._setup_noload_problem(config, geom, mech_angle_rad, femm)
        femm.mi_saveas(noload_fem_path)

        if solve_cache_dir is not None:
            try:
                cache_filename = f"{cache_prefix}_{elec_angle_deg:.1f}deg.fem"
                cache_file_path = solve_cache_dir / cache_filename
                shutil.copy2(noload_fem_native_path, cache_file_path)
            except Exception as e:
                logger.warning(f"[CACHE] Failed to copy noload .fem file at {elec_angle_deg:.1f}°: {e}")

        femm.mi_createmesh()
        femm.mi_analyze()
        # Wine-flush race: sleep BEFORE loadsolution so the .ans file is on
        # disk by the time FEMM's postprocessor tries to read it.
        time.sleep(0.4)
        femm.mi_loadsolution()
        time.sleep(0.15)

        # Postprocessor health probe. Without this, a failed loadsolution
        # silently feeds zero flux linkage into back-EMF and the error only
        # surfaces much later as a confusing mo_getpointvalues nil error.
        try:
            _ = femm.mo_numelements()
        except Exception as probe_exc:
            raise RuntimeError(
                f"FEMM postprocessor failed to load for no-load position at elec_angle={elec_angle_deg:.2f}°. Probe error: {probe_exc}"
            ) from probe_exc

        flux_a, flux_b, flux_c = self._extract_flux_linkage(femm, config, geom)

        try:
            femm.mo_close()
            femm.mi_close()
        except Exception:
            if self._is_cancel_requested():
                self._raise_if_cancel_requested()
            raise

        return flux_a, flux_b, flux_c

    def _run_single_cogging_position(
        self,
        config: MotorConfig,
        geom: MotorGeometry,
        femm,
        elec_angle_deg: float,
        *,
        solve_cache_dir: Path | None = None,
        cache_prefix: str = "cogging",
    ) -> float:
        """Solve one no-load FEMM position and return cogging torque in N·m.

        Cogging torque is the reluctance torque the rotor permanent magnets
        produce against the slotted stator at *zero winding current*. It is
        extracted with the same weighted Maxwell stress-tensor block integral
        used for the loaded sweep (``mo_blockintegral(22)`` inside
        ``_extract_torque``), but evaluated on a J=0 solution so the only
        excitation is the PM field.

        Reuses ``_setup_noload_problem`` so the geometry, mesh seed, and rotor
        offset exactly match the back-EMF no-load path — the only difference
        from ``_run_single_noload_position`` is that we integrate torque on the
        rotor blocks instead of phase flux linkage. ``_setup_noload_problem``
        sets ``self._last_rotor_offset_rad`` to this position's offset, which
        ``_extract_torque`` reads to select the rotated rotor blocks.

        Raises:
            FEMMTorqueExtractionError: if the stress-tensor integral still
                fails after one postprocessor-reload retry. The caller records
                ``math.nan`` for the affected position so a single dropout does
                not poison the cogging metric (mirrors the loaded sweep).
        """
        # Local import keeps femm_postprocess free of a module-level dependency
        # on femm_extraction (avoids an import cycle between the mixins).
        from backend.femm_extraction import FEMMTorqueExtractionError

        pole_pairs = max(1, config.rotor.pole_count // 2)
        mech_angle_rad = math.radians(elec_angle_deg / pole_pairs)
        cogging_fem_path = get_wine_compatible_path("openem_cogging.fem")
        cogging_fem_native_path = Path(get_native_path_from_wine_path(cogging_fem_path))

        self._setup_noload_problem(config, geom, mech_angle_rad, femm)
        femm.mi_saveas(cogging_fem_path)

        if solve_cache_dir is not None:
            try:
                cache_filename = f"{cache_prefix}_{elec_angle_deg:.1f}deg.fem"
                shutil.copy2(cogging_fem_native_path, solve_cache_dir / cache_filename)
            except Exception as e:
                logger.warning(f"[CACHE] Failed to copy cogging .fem file at {elec_angle_deg:.1f}°: {e}")

        femm.mi_createmesh()
        femm.mi_analyze()
        # Wine-flush race: sleep BEFORE loadsolution so the .ans file is on
        # disk by the time the postprocessor reads it (mirrors the no-load and
        # loaded sweep timing).
        time.sleep(0.4)
        femm.mi_loadsolution()
        time.sleep(0.15)

        # Postprocessor health probe — surfaces a failed loadsolution here
        # instead of as a confusing downstream block-integral nil error.
        try:
            _ = femm.mo_numelements()
        except Exception as probe_exc:
            raise RuntimeError(
                f"FEMM postprocessor failed to load for cogging position at "
                f"elec_angle={elec_angle_deg:.2f}°. Probe error: {probe_exc}"
            ) from probe_exc

        # Extract cogging torque with one retry on the same Wine flush race the
        # loaded sweep guards against (see the torque retry in _solve_locked).
        try:
            cogging_nm = self._extract_torque(femm)
        except FEMMTorqueExtractionError as first_exc:
            logger.warning(
                "[COGGING] Stress-tensor extraction failed at elec=%.2f° on "
                "first try; retrying after postprocessor reload. %s",
                elec_angle_deg, first_exc,
            )
            try:
                femm.mo_close()
            except Exception:
                pass
            time.sleep(1.0)
            femm.mi_loadsolution()
            time.sleep(0.4)
            cogging_nm = self._extract_torque(femm)

        try:
            femm.mo_close()
            femm.mi_close()
        except Exception:
            if self._is_cancel_requested():
                self._raise_if_cancel_requested()
            raise

        return cogging_nm

    @staticmethod
    def _cogging_points_per_period(config: MotorConfig) -> int:
        """Number of no-load solves per cogging pitch.

        Resolution is what matters for cogging: the waveform is a sharp,
        high-frequency ripple, so we want enough points across a single
        cogging period to resolve its peak and first few harmonics. This
        count is the number of FEMM solves the sweep costs (it samples one
        cogging period only).

        Presets follow the Fast / Balanced / Accurate convention
        (8 / 16 / 32 samples per period); scales with solve quality and is
        overridable via OPENEM_FEMM_COGGING_POINTS, clamped to a sane range.
        """
        env_override = os.environ.get("OPENEM_FEMM_COGGING_POINTS")
        if env_override:
            try:
                return max(4, min(64, int(env_override)))
            except ValueError:
                logger.warning(
                    "[COGGING] Ignoring non-integer OPENEM_FEMM_COGGING_POINTS=%r",
                    env_override,
                )
        quality = (
            config.solve_params.solve_quality
            if config.solve_params is not None
            else None
        )
        # Fast / Balanced / Accurate → quick / standard / fine.
        by_quality = {"quick": 8, "standard": 16, "fine": 32}
        return by_quality.get(quality or "standard", 16)

    def _run_cogging_sweep(
        self,
        config: MotorConfig,
        geom: MotorGeometry,
        femm,
        on_progress=None,
        solve_cache_dir=None,
        progress_offset: int = 0,
        progress_total: int | None = None,
    ) -> dict:
        """Dedicated no-load cogging-torque sweep (S4-02).

        Cogging torque is a pure no-load quantity, so this sweep runs whether
        or not the loaded torque sweep ran. It is periodic over the cogging
        pitch τ_c = 360° / lcm(Ns, 2p) (mechanical), so we sweep exactly ONE
        cogging period at zero current and extract torque at each position.
        The result is reported against mechanical angle (the physical primary
        axis); the UI tiles it across a full revolution for visualization only.

        Returns a dict with one-period ``mechanical_angle_deg`` /
        ``electrical_angle_deg`` / ``torque_Nm`` lists plus geometry
        (``periods_per_rev``, ``cog_period_mech_deg``, ``cog_period_elec_deg``,
        ``points_per_period``, ``step_mech_deg``) and metrics
        (``peak_to_peak_Nm``, ``rms_Nm``, ``mean_Nm``, ``max_Nm``, ``min_Nm``,
        ``peak_Nm``). NOTE: ripple-percent is intentionally NOT reported — mean
        cogging torque is ~0, so a percent-of-mean metric is meaningless.
        """
        # Local import avoids a module-level cycle (SolveCancelledError lives
        # in femm_solver, which imports this mixin).
        from backend.femm_solver import SolveCancelledError

        slot_count = config.stator.slot_count
        pole_count = config.rotor.pole_count
        pole_pairs = max(1, pole_count // 2)
        periods_per_rev = math.lcm(slot_count, pole_count)
        cog_period_mech_deg = 360.0 / periods_per_rev

        points = self._cogging_points_per_period(config)
        # Sample one cogging period on the half-open interval [0, τ_c) so the
        # endpoint (identical to the next period's start) isn't double-counted.
        step_mech_deg = cog_period_mech_deg / points
        mech_angles = [i * step_mech_deg for i in range(points)]
        elec_angles = [a * pole_pairs for a in mech_angles]

        logger.info(
            "[COGGING] No-load cogging sweep: lcm(%d,%d)=%d periods/rev → "
            "τ_c=%.3f° mech, %d samples/period (step=%.4f° mech)",
            slot_count, pole_count, periods_per_rev, cog_period_mech_deg,
            points, step_mech_deg,
        )

        total = progress_total if progress_total is not None else points
        torque_nm: list[float] = []
        for idx, mech_angle in enumerate(mech_angles):
            self._raise_if_cancel_requested()
            elec_angle = elec_angles[idx]
            try:
                cog_nm = self._run_single_cogging_position(
                    config,
                    geom,
                    femm,
                    elec_angle,
                    solve_cache_dir=solve_cache_dir,
                    cache_prefix=f"cogging_pos{idx}",
                )
            except SolveCancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                cog_nm = math.nan
                logger.warning(
                    "[COGGING] Position %d (mech=%.2f°) extraction failed; "
                    "recording NaN. %s",
                    idx, mech_angle, exc,
                )
            torque_nm.append(cog_nm)
            logger.info(
                "[COGGING] Position %d: mech=%.2f° elec=%.2f° cogging=%.5f Nm",
                idx, mech_angle, elec_angle, cog_nm,
            )
            if on_progress is not None:
                # Stream the actual cogging torque so the live viewer can plot
                # values point-by-point. NaN drops are sanitized to null by the
                # SSE encoder; the frontend skips non-finite samples.
                on_progress(
                    progress_offset + idx + 1,
                    total,
                    cog_nm,
                    "cogging_sweep",
                    elec_angle,
                )

        # Metrics from the finite samples. Peak-to-peak and RMS are the
        # meaningful cogging metrics; mean is ~0 and kept for debug only.
        finite = [v for v in torque_nm if math.isfinite(v)]
        if finite:
            max_nm = float(max(finite))
            min_nm = float(min(finite))
            peak_to_peak_nm = max_nm - min_nm
            mean_nm = float(sum(finite) / len(finite))
            rms_nm = float((sum(v * v for v in finite) / len(finite)) ** 0.5)
            peak_nm = float(max(abs(v) for v in finite))
        else:
            max_nm = min_nm = peak_to_peak_nm = mean_nm = rms_nm = peak_nm = 0.0

        logger.info(
            "[COGGING] Metrics: peak-to-peak=%.5f Nm, RMS=%.5f Nm, mean=%.5f Nm "
            "(%d periods/rev)",
            peak_to_peak_nm, rms_nm, mean_nm, periods_per_rev,
        )

        return {
            "mechanical_angle_deg": mech_angles,
            "electrical_angle_deg": elec_angles,
            "torque_Nm": torque_nm,
            "periods_per_rev": periods_per_rev,
            "cog_period_mech_deg": cog_period_mech_deg,
            "cog_period_elec_deg": cog_period_mech_deg * pole_pairs,
            "points_per_period": points,
            "step_mech_deg": step_mech_deg,
            "peak_to_peak_Nm": peak_to_peak_nm,
            "rms_Nm": rms_nm,
            "mean_Nm": mean_nm,
            "max_Nm": max_nm,
            "min_Nm": min_nm,
            "peak_Nm": peak_nm,
        }

    def _run_noload_sweep(
        self,
        config: MotorConfig,
        geom: MotorGeometry,
        femm,
        on_progress=None,
        solve_cache_dir=None,
        thd_analysis: bool = False,
        seed_samples: dict[int, tuple[float, float, float, float]] | None = None,
        progress_offset: int = 0,
        progress_total: int | None = None,
    ) -> dict:
        """Run no-load (zero current) sweep for back-EMF and flux linkage (S4-01).

        This sweep uses:
        - J=0 (zero winding current)
        - 360° electrical coverage
        - Step size scaled from solve_params.rotor_step_deg (4x multiplier, clamped 15°–90°)

        Args:
            solve_cache_dir: Optional Path to cache directory for saving .fem files (S6-05)
            thd_analysis: When True, enforce 48 Standard or 96 Fine positions
                         for the versioned periodic flux-linkage DFT.

        Returns:
            dict with "waveform" (BackEMFWaveform) and "fundamental_V", "thd_pct"
        """
        logger.info("[SOLVE] Running no-load sweep for back-EMF (S4-01)")
        rated_speed_rpm = config.solve_params.rated_speed_rpm if config.solve_params else 3000
        omega_mech_rad_s = 2 * math.pi * rated_speed_rpm / 60

        pole_pairs = config.rotor.pole_count // 2
        omega_elec_rad_s = omega_mech_rad_s * pole_pairs
        planned_angles = self._build_noload_sweep_angles(config, thd_analysis=thd_analysis)
        samples_by_angle = dict(seed_samples or {})
        remaining_angles = [elec_angle_deg for elec_angle_deg in planned_angles if self._angle_bucket_key(elec_angle_deg) not in samples_by_angle]
        total_progress = progress_total if progress_total is not None else progress_offset + len(remaining_angles)

        for pos_idx, elec_angle_deg in enumerate(remaining_angles):
            self._raise_if_cancel_requested()
            flux_a, flux_b, flux_c = self._run_single_noload_position(
                config,
                geom,
                femm,
                elec_angle_deg,
                solve_cache_dir=solve_cache_dir,
                cache_prefix=f"noload_pos{pos_idx}",
            )
            sample_key = self._angle_bucket_key(elec_angle_deg)
            samples_by_angle[sample_key] = (elec_angle_deg, flux_a, flux_b, flux_c)
            logger.info(f"[NOLOAD] Position {pos_idx}: elec={elec_angle_deg:.0f}° psi_a={flux_a:.6f} psi_b={flux_b:.6f} psi_c={flux_c:.6f}")

            if on_progress is not None:
                live_back_emf = self._estimate_live_back_emf_from_flux_linkage(
                    samples_by_angle,
                    omega_elec_rad_s,
                    sample_key,
                )
                if live_back_emf is None:
                    phase_a_live = 0.0
                    phase_b_live = 0.0
                    phase_c_live = 0.0
                else:
                    phase_a_live, phase_b_live, phase_c_live = live_back_emf

                on_progress(
                    progress_offset + pos_idx + 1,
                    total_progress,
                    0.0,
                    "noload_sweep",
                    elec_angle_deg,
                    phase_a_live,
                    phase_b_live,
                    phase_c_live,
                )

        self._raise_if_cancel_requested()

        # Compute signoff back-EMF from the planned uniform full-cycle grid.
        # Seed samples may include denser partial-grid positions from a loaded
        # sweep; those are useful for live estimates, but mixing them into the
        # final FFT would make the scalar metrics nonuniform-grid artifacts.
        ordered_samples = [samples_by_angle[self._angle_bucket_key(angle)] for angle in planned_angles]
        elec_angles = [angle for angle, _, _, _ in ordered_samples]
        flux_a_list = [flux_a for _, flux_a, _, _ in ordered_samples]
        flux_b_list = [flux_b for _, _, flux_b, _ in ordered_samples]
        flux_c_list = [flux_c for _, _, _, flux_c in ordered_samples]

        legacy_emf_a, legacy_emf_b, legacy_emf_c = self._compute_back_emf_scaled(
            flux_a_list, flux_b_list, flux_c_list, elec_angles, omega_mech_rad_s, basis_label="mechanical"
        )
        back_emf_a, back_emf_b, back_emf_c = self._compute_back_emf_scaled(
            flux_a_list, flux_b_list, flux_c_list, elec_angles, omega_elec_rad_s, basis_label="electrical"
        )

        # Compute summary metrics from the physically-scaled electrical waveform.
        harmonic_analysis = None
        if thd_analysis:
            quality = config.solve_params.solve_quality if config.solve_params else "standard"
            harmonic_analysis = analyze_back_emf_harmonics(
                angles_elec_deg=elec_angles,
                phase_a_flux_linkage_Wb=flux_a_list,
                phase_b_flux_linkage_Wb=flux_b_list,
                phase_c_flux_linkage_Wb=flux_c_list,
                electrical_angular_speed_rad_s=omega_elec_rad_s,
                max_harmonic=harmonic_limit_for_quality(quality),
            )
            fundamental_rms = harmonic_analysis.harmonics[0].phase_a_rms_V
            fundamental_peak = fundamental_rms * math.sqrt(2.0)
            thd = harmonic_analysis.phase_a_thd_h12_pct
        else:
            # Fast path: extract fundamental only, skip THD
            fundamental_peak, _ = self._compute_thd_fft(back_emf_a)
            thd = None
            fundamental_rms = fundamental_peak / math.sqrt(2.0)

        legacy_fundamental_peak, _ = self._compute_thd_fft(legacy_emf_a)
        waveform_peak = max(max(abs(v) for v in phase) for phase in (back_emf_a, back_emf_b, back_emf_c))
        legacy_waveform_peak = max(max(abs(v) for v in phase) for phase in (legacy_emf_a, legacy_emf_b, legacy_emf_c))
        legacy_fundamental_rms = legacy_fundamental_peak / math.sqrt(2.0)

        thd_text = f"{thd:.1f}%" if thd is not None else "Disabled"
        logger.info(
            "[SOLVE] No-load back-EMF: fundamental_rms=%.2fV (physical peak=%.2fV, legacy peak=%.2fV), THD=%s (S4-01, thd_analysis=%s)",
            fundamental_rms,
            fundamental_peak,
            legacy_fundamental_peak,
            thd_text,
            "ON" if thd_analysis else "OFF",
        )

        waveform = BackEMFWaveform(
            electrical_angle_deg=elec_angles,
            phase_a_V=back_emf_a,
            phase_b_V=back_emf_b,
            phase_c_V=back_emf_c,
        )

        debug_payload = {
            "electrical_angle_deg": elec_angles,
            "flux_linkage": {
                "phase_a_wb": flux_a_list,
                "phase_b_wb": flux_b_list,
                "phase_c_wb": flux_c_list,
            },
            "legacy_mechanical_speed": {
                "omega_rad_s": omega_mech_rad_s,
                "phase_a_v": legacy_emf_a,
                "phase_b_v": legacy_emf_b,
                "phase_c_v": legacy_emf_c,
                "fundamental_peak_v": float(legacy_fundamental_peak),
                "fundamental_rms_v": float(legacy_fundamental_rms),
                "waveform_peak_v": float(legacy_waveform_peak),
            },
            "physical_electrical_speed": {
                "omega_rad_s": omega_elec_rad_s,
                "phase_a_v": back_emf_a,
                "phase_b_v": back_emf_b,
                "phase_c_v": back_emf_c,
                "fundamental_peak_v": float(fundamental_peak),
                "fundamental_rms_v": float(fundamental_rms),
                "waveform_peak_v": float(waveform_peak),
                "thd_pct": float(thd) if thd is not None else None,
                "harmonic_analysis": (
                    harmonic_analysis.model_dump(mode="json")
                    if harmonic_analysis is not None
                    else None
                ),
            },
        }
        self._persist_debug_json("noload_back_emf_report.json", debug_payload, solve_cache_dir)

        return {
            "waveform": waveform,
            "fundamental_V": float(fundamental_rms),
            "fundamental_peak_V": float(fundamental_peak),
            "peak_V": float(waveform_peak),
            "thd_pct": float(thd) if thd is not None else None,
            "harmonic_analysis": harmonic_analysis,
            "flux_linkage": {
                "electrical_angle_deg": elec_angles,
                "phase_a_wb": flux_a_list,
                "phase_b_wb": flux_b_list,
                "phase_c_wb": flux_c_list,
            },
            "legacy_flux_linkage_voltage": {
                "fundamental_peak_V": float(legacy_fundamental_peak),
                "fundamental_rms_V": float(legacy_fundamental_rms),
                "peak_V": float(legacy_waveform_peak),
            },
        }

    def _setup_noload_problem(self, config: MotorConfig, geom: MotorGeometry, rotor_offset_rad: float, femm):
        """Setup FEMM problem for no-load case (zero current, S4-01).

        Reuses the full geometry pipeline but applies J=0 to all slots,
        giving a pure permanent-magnet excitation for back-EMF extraction.
        """
        rotor_offset_deg = math.degrees(rotor_offset_rad)

        self._setup_problem(femm, config, geom)
        self._last_rotor_offset_rad = rotor_offset_rad
        self._draw_full_geometry(femm, config, geom, rotor_offset_deg=rotor_offset_deg)
        from backend.femm_geometry import _slot_current_assignments, _slot_layer_label_radius

        split_distributed_layers = (
            config.winding.type == "distributed"
            and config.winding.layers >= 2
        )

        # Apply zero-current coil materials to every slot (J=0)
        for i, slot in enumerate(geom.slots):
            assignments = _slot_current_assignments(config, slot)
            if split_distributed_layers and len(assignments) > 1:
                for assignment in assignments:
                    layer = int(assignment["layer"])
                    slot_r = _slot_layer_label_radius(
                        slot.inner_radius_mm,
                        slot.outer_radius_mm,
                        layer,
                        len(assignments),
                    )
                    lx = slot_r * math.cos(slot.center_angle_rad)
                    ly = slot_r * math.sin(slot.center_angle_rad)

                    slot_mat = f"Coil_s{i}_l{layer}"
                    femm.mi_addmaterial(slot_mat, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
                    femm.mi_addblocklabel(lx, ly)
                    femm.mi_selectlabel(lx, ly)
                    set_blockprop = getattr(self, "_set_femm_blockprop", None)
                    if callable(set_blockprop):
                        set_blockprop(femm, slot_mat, config, geom, "slot")
                    else:
                        femm.mi_setblockprop(slot_mat, 1, 0, "<None>", 0, 0, 0)
                    femm.mi_clearselected()
                continue

            slot_r = (slot.inner_radius_mm + slot.outer_radius_mm) / 2
            lx = slot_r * math.cos(slot.center_angle_rad)
            ly = slot_r * math.sin(slot.center_angle_rad)

            slot_mat = f"Coil_s{i}"
            # J=0 (5th arg) — no winding current for no-load case
            femm.mi_addmaterial(slot_mat, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
            femm.mi_addblocklabel(lx, ly)
            femm.mi_selectlabel(lx, ly)
            set_blockprop = getattr(self, "_set_femm_blockprop", None)
            if callable(set_blockprop):
                set_blockprop(femm, slot_mat, config, geom, "slot")
            else:
                femm.mi_setblockprop(slot_mat, 1, 0, "<None>", 0, 0, 0)
            femm.mi_clearselected()

        self._apply_boundary(femm, geom)

    def _compute_back_emf_scaled(
        self,
        flux_a: list,
        flux_b: list,
        flux_c: list,
        elec_angles_deg: list,
        angular_velocity_rad_s: float,
        *,
        basis_label: str,
        log_result: bool = True,
    ) -> tuple:
        """Compute back-EMF from flux linkage derivatives (S4-01, S4-11).

        Applies voltage scaling: ``e = ω × dΨ/dθ``.

        ``elec_angles_deg`` is sampled over electrical angle, so the physically
        correct scaling uses electrical angular velocity. Some legacy comparison
        paths still use mechanical speed against the electrical-angle derivative;
        callers pass the desired basis explicitly so both can be inspected.

        Bug fix: np.gradient must use the actual angular spacing (in radians)
        as the second argument. Without it, the derivative is dΨ/d(index)
        (spacing=1), making the result dependent on the number of samples
        and off by a factor of Δθ_rad.
        """
        # Convert electrical angles to radians for proper derivative spacing
        elec_angles_rad = np.radians(np.array(elec_angles_deg))

        # Numerical differentiation: dΨ/dθ [Wb/rad] — uses actual angular spacing
        dflux_a = np.gradient(np.array(flux_a), elec_angles_rad)
        dflux_b = np.gradient(np.array(flux_b), elec_angles_rad)
        dflux_c = np.gradient(np.array(flux_c), elec_angles_rad)

        # Back-EMF = ω × dΨ/dθ [V]
        emf_a = list(angular_velocity_rad_s * dflux_a)
        emf_b = list(angular_velocity_rad_s * dflux_b)
        emf_c = list(angular_velocity_rad_s * dflux_c)

        if log_result:
            logger.info(
                "[EMF] Back-EMF scaled with %s ω=%.1f rad/s, Δθ=%.1f°",
                basis_label,
                angular_velocity_rad_s,
                np.degrees(elec_angles_rad[1] - elec_angles_rad[0]),
            )

        return emf_a, emf_b, emf_c

    def _compute_thd_fft(self, waveform: list) -> tuple:
        """Compute THD via FFT (S4-01).

        Requires at least 8 samples for meaningful results (captures up to
        the 3rd harmonic).  With fewer samples, returns (fundamental, 0.0)
        since the FFT has no usable harmonic bins.

        Returns:
            (fundamental_peak_voltage, thd_percent)

        Note: FFT bin magnitudes scale as peak × N/2, so we normalize by
        2/N to return the actual peak voltage of the fundamental.
        """
        n = len(waveform)
        if n < 2:
            return 0.0, 0.0

        fft_vals = np.fft.fft(waveform)
        magnitudes = np.abs(fft_vals)
        fundamental_raw = magnitudes[1]

        # Normalize FFT magnitude to peak voltage: V_peak = |X[k]| × 2/N
        fundamental_peak = fundamental_raw * 2.0 / n

        if n < 8 or fundamental_raw < 1e-10:
            logger.warning(
                f"[THD] Insufficient data for THD: n={n}, fundamental_peak={fundamental_peak:.4f}V. Need ≥8 samples (have {n}). Returning THD=0."
            )
            return float(fundamental_peak), 0.0

        # THD = sqrt(sum(H_n^2 for n=2..N/2)) / H_1  (ratio is scale-invariant)
        harmonics_power = float(np.sum(magnitudes[2 : n // 2] ** 2))
        thd = 100 * np.sqrt(harmonics_power) / fundamental_raw

        logger.info(f"[THD] n={n}, fundamental_peak={fundamental_peak:.4f}V, harmonics_power={harmonics_power:.4f}, THD={thd:.1f}%")

        return float(fundamental_peak), float(thd)
