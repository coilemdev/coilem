"""Data contracts for motor configuration. """

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.custom_materials import CustomSteel, is_custom_steel_id

MIN_IPM_MAGNET_WIDTH_MM = 0.1
MIN_SPM_MAGNET_WIDTH_MM = 5.0
MIN_STATOR_SLOT_OPENING_MM = 2.0
MIN_STATOR_TOOTH_WIDTH_MM = 2.0


class StatorConfig(BaseModel):
    """Stator geometry and properties."""

    OD_mm: float = Field(..., ge=30, le=500, description="Outer diameter in mm")
    ID_mm: float = Field(..., ge=20, le=450, description="Inner diameter (bore) in mm")
    slot_count: int = Field(..., ge=6, le=96, description="Number of slots")
    stack_length_mm: float = Field(..., ge=10, le=300, description="Stack length in mm")
    slot_opening_mm: float = Field(
        ...,
        ge=MIN_STATOR_SLOT_OPENING_MM,
        le=50,
        description="Bore-side slot opening width in mm",
    )
    # Schema v3 made this the physical tooth width at the yoke-side slot body
    # instead of a bore-pitch offset, so the same motor now stores a larger number
    # and the old le=50 became too tight: a 6-slot 50kW design migrates from 30mm
    # to 63.5mm. The widest tooth the other bounds can produce is the slot-body
    # pitch at OD 500 / ID 20 / 6 slots, about 260mm. Overlap is enforced properly
    # by validate_geometry's tooth-vs-slot-body-pitch check; this is only a sanity
    # range.
    tooth_width_mm: float = Field(
        ...,
        ge=MIN_STATOR_TOOTH_WIDTH_MM,
        le=260,
        description="Tooth width at the slot body beside the yoke, in mm",
    )
    yoke_thickness_mm: float = Field(..., ge=2, le=100, description="Yoke thickness in mm")
    tooth_shoe_enabled: bool = Field(
        default=False, description="Add a widened shoe (tooth tip) at the stator bore."
    )
    tooth_shoe_height_mm: float = Field(
        default=1.5,
        ge=0.5,
        le=10.0,
        description="Radial thickness of the stator tooth shoe at the bore (mm).",
    )
    tooth_shoe_overhang_mm: float = Field(
        default=1.5,
        ge=0.0,
        le=15.0,
        description="Extra arc width per side of the shoe tip beyond the tooth body (mm).",
    )
    @field_validator("ID_mm")
    @classmethod
    def id_must_be_less_than_od(cls, v, info):
        """ID must be less than OD."""
        if info.data and "OD_mm" in info.data and v >= info.data["OD_mm"]:
            raise ValueError("ID_mm must be less than OD_mm")
        return v

    @model_validator(mode="after")
    def tooth_shoe_must_fit_slot_pitch(self):
        """When the shoe is enabled, the flare must fit the slot mouth.

        The bore-side tooth body already spans ``slot_pitch - slot_opening``
        at the bore (the slot opening is the remaining gap between adjacent
        teeth). The shoe adds ``tooth_shoe_overhang_mm`` per side, so the
        post-shoe mouth becomes ``slot_opening_mm - 2*overhang_mm``.
        Requiring this to stay positive keeps adjacent shoe tips from
        colliding and mirrors the hard geometry limit in
        ``_tooth_shoe_half_angles``.
        """
        if not self.tooth_shoe_enabled:
            return self
        if 2.0 * self.tooth_shoe_overhang_mm >= self.slot_opening_mm:
            raise ValueError(
                "tooth shoe overhang is too large for the slot opening: "
                f"2*overhang ({2.0 * self.tooth_shoe_overhang_mm:g} mm) must be "
                f"less than slot_opening_mm ({self.slot_opening_mm:g} mm) so the "
                "post-shoe slot mouth stays positive"
            )
        return self


class RotorConfig(BaseModel):
    """Rotor geometry and magnet properties."""

    OD_mm: float = Field(..., ge=15, le=450, description="Outer diameter in mm")
    ID_mm: Optional[float] = Field(
        default=None,
        ge=0,
        le=440,
        description="Optional inner diameter in mm",
    )
    magnet_thickness_mm: float = Field(..., ge=2, le=50, description="Magnet thickness in mm")
    magnet_width_mm: float = Field(
        ...,
        ge=MIN_IPM_MAGNET_WIDTH_MM,
        le=200,
        description=(
            "Magnet width in mm: straight tangential bar length for flat-buried IPM, "
            "surface arc length for SPM, or slab length for V-shape IPM"
        ),
    )
    pole_count: int = Field(..., ge=2, le=32, description="Number of poles")
    magnet_embrace: float = Field(
        default=0.8, ge=0, le=1, description="Magnet coverage fraction (0-1)"
    )
    bridge_thickness_mm: float = Field(
        default=1.5,
        ge=0,
        le=20,
        description=(
            "Minimum radial steel bridge from a straight flat-buried IPM pocket "
            "corner to the rotor outer surface in mm"
        ),
    )
    ipm_topology: Literal["flat_buried", "v_shape", "pyleecan_holem50", "spoke", "barrier"] = Field(
        default="flat_buried",
        description="IPM rotor pocket family. Pyleecan HoleM50 is available for the Prius benchmark fixture.",
    )
    flat_buried_magnet_shape: Literal["straight", "legacy_arc"] = Field(
        default="straight",
        description=(
            "Flat-buried magnet construction. New designs use straight rectangular bars; "
            "legacy_arc is retained only for migrated pre-v4 project compatibility."
        ),
    )
    side_bridge_thickness_mm: float = Field(
        default=1.2,
        ge=0,
        le=20,
        description=(
            "Minimum tangential steel web between adjacent flat buried magnet pockets"
        ),
    )
    pocket_clearance_mm: float = Field(
        default=0.25,
        ge=0,
        le=5,
        description="Nominal air/mechanical clearance around buried IPM magnets",
    )
    magnet_angle_deg: float = Field(
        default=0.0,
        ge=-60,
        le=60,
        description="Flat-pole pocket angular offset in degrees",
    )
    v_angle_deg: float = Field(
        default=60.0,
        ge=0,
        le=120,
        description="V-shape IPM included magnet angle in degrees",
    )
    v_depth_mm: float = Field(
        default=22.0,
        ge=0,
        le=200,
        description="Radial depth of the V-shape IPM apex from the rotor outer surface",
    )
    inner_web_thickness_mm: float = Field(
        default=8.0,
        ge=0,
        le=20,
        description="Steel web thickness between paired V-shape IPM magnets",
    )
    outer_bridge_thickness_mm: float = Field(
        default=1.5,
        ge=0,
        le=20,
        description="Steel bridge thickness from V-shape IPM magnet tips to the rotor surface",
    )
    holem50_w0_mm: float = Field(
        default=42.0,
        ge=0.0,
        le=200.0,
        description="Pyleecan HoleM50 W0 pocket width in mm",
    )
    holem50_w1_mm: float = Field(
        default=0.0,
        ge=0.0,
        le=200.0,
        description="Pyleecan HoleM50 W1 central opening width in mm",
    )
    holem50_w2_mm: float = Field(
        default=0.0,
        ge=0.0,
        le=200.0,
        description="Pyleecan HoleM50 W2 magnet offset width in mm",
    )
    holem50_w3_mm: float = Field(
        default=14.0,
        ge=0.0,
        le=200.0,
        description="Pyleecan HoleM50 W3 tangential bridge width in mm",
    )
    holem50_w4_mm: float = Field(
        default=18.9,
        ge=0.1,
        le=200.0,
        description="Pyleecan HoleM50 W4 magnet width in mm",
    )
    holem50_h0_mm: float = Field(
        default=10.96,
        ge=0.0,
        le=200.0,
        description="Pyleecan HoleM50 H0 pocket radial depth in mm",
    )
    holem50_h1_mm: float = Field(
        default=1.5,
        ge=0.0,
        le=20.0,
        description="Pyleecan HoleM50 H1 tangential bridge thickness in mm",
    )
    holem50_h2_mm: float = Field(
        default=1.0,
        ge=0.0,
        le=20.0,
        description="Pyleecan HoleM50 H2 magnet shoulder height in mm",
    )
    holem50_h3_mm: float = Field(
        default=6.5,
        ge=0.1,
        le=50.0,
        description="Pyleecan HoleM50 H3 magnet height in mm",
    )
    holem50_h4_mm: float = Field(
        default=0.0,
        ge=0.0,
        le=20.0,
        description="Pyleecan HoleM50 H4 radial bridge offset in mm",
    )
    flux_barrier_count: Optional[int] = Field(default=None, ge=0, le=8, description="[FUTURE]")
    barrier_widths_mm: Optional[list[float]] = Field(default=None, description="[FUTURE]")

    @field_validator("ID_mm")
    @classmethod
    def id_must_be_less_than_od(cls, v, info):
        """Rotor ID must be less than OD when provided."""
        if v is None:
            return v
        if info.data and "OD_mm" in info.data and v >= info.data["OD_mm"]:
            raise ValueError("ID_mm must be less than OD_mm")
        return v


class WindingConfig(BaseModel):
    """Winding configuration."""

    type: Literal["distributed", "concentrated"] = Field(
        default="distributed", description="Winding type"
    )
    turns_per_coil: int = Field(..., ge=1, le=500, description="Turns per coil")
    layers: int = Field(default=2, ge=1, le=2, description="Number of layers (1 or 2)")
    parallel_paths: int = Field(
        default=1, ge=1, le=6, description="Number of parallel paths"
    )
    coil_span: Optional[int] = Field(
        default=None,
        ge=1,
        le=96,
        description=(
            "Distributed-winding coil span in slots. Omit for full pitch (3q); "
            "short-pitch values are validated against the slot/pole combination."
        ),
    )


class MaterialsConfig(BaseModel):
    """Material selections."""

    stator_steel: str = Field(
        default="M350-50A", description="Bundled nonlinear electrical-steel model"
    )
    rotor_steel: str = Field(
        default="M350-50A", description="Bundled nonlinear electrical-steel model"
    )
    # Keep in sync with backend.material_catalog.MAGNET_PROPERTIES keys. Unknown
    # grades must 422 at config parse time — never crash post-solve demag.
    magnet_grade: Literal[
        "N35", "N42", "N48", "N52", "N48SH", "Ferrite_Y30", "Prius_2004_NdFeB"
    ] = Field(default="N42", description="Magnet grade")
    conductor: Literal["copper", "aluminum"] = Field(
        default="copper", description="Conductor material"
    )
    custom_steels: dict[str, CustomSteel] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def validate_steel_selections(self):
        for key, material in self.custom_steels.items():
            if key != material.id:
                raise ValueError("Custom steel key must match its content identity.")
        supported = {"M350-50A"}
        for grade in (self.stator_steel, self.rotor_steel):
            if grade not in supported and not (is_custom_steel_id(grade) and grade in self.custom_steels):
                raise ValueError("Steel selection requires a bundled grade or its embedded custom material definition.")
        return self


class SolveParams(BaseModel):
    """Electromagnetic simulation parameters."""

    solve_quality: Literal["quick", "standard", "fine", "custom"] = Field(
        default="standard",
        description=(
            "Solve quality preset controlling position count vs. speed tradeoff. "
            "'quick' (60° sweep, fastest), 'standard' (180° sweep, balanced), "
            "'fine' (360° sweep, publication quality), 'custom' (use rotor_step_deg directly)."
        ),
    )
    rotor_sweep_range_deg: float = Field(
        default=60, ge=1, le=360, description="Rotor sweep range in electrical degrees"
    )
    rotor_step_deg: float = Field(
        default=2.5, ge=0.5, le=30, description="Rotor step size in electrical degrees (used when solve_quality='custom')"
    )
    mesh_density: Literal["coarse", "normal", "fine", "very_fine"] = Field(
        default="normal",
        description=(
            "Mesh refinement level. 'very_fine' is intended for h-convergence "
            "studies with cogging spectral convergence and is significantly "
            "slower than 'fine'."
        ),
    )
    mesh_source: Literal["native"] = Field(
        default="native",
        description="Gmsh-native Magneto2D mesh source.",
    )
    mesher: Literal["gmsh"] = Field(
        default="gmsh",
        description="Gmsh is the supported mesh generator.",
    )
    corner_refinement: bool = Field(
        default=False,
        description=(
            "Enable adaptive Gmsh refinement near magnet corners and slot openings."
        ),
    )
    slot_sidewall_refinement: bool = Field(
        default=False,
        description=(
            "Deprecated legacy Spade-only slot-mouth/slot-sidewall refinement "
            "toggle. Retained as a no-op so older saved projects can be read, "
            "but new native solves use Gmsh."
        ),
    )
    current_amplitude_A: float = Field(
        ..., ge=0.0, le=1000, description="Phase current magnitude in Amperes (0 allowed for no-load or cogging studies)"
    )
    current_amplitude_convention: Literal["peak", "rms", "plateau"] = Field(
        default="peak",
        description=(
            "Interpret current_amplitude_A as sine peak, sine RMS, or the "
            "conducting-phase plateau used by ideal six-step excitation"
        ),
    )
    current_angle_deg: float = Field(
        default=0,
        ge=-180,
        le=180,
        description=(
            "Current angle gamma in electrical degrees from the q-axis; "
            "positive advances toward flux weakening"
        ),
    )
    excitation_mode: Literal["sinusoidal", "ideal_six_step_120"] = Field(
        default="sinusoidal",
        description=(
            "Stator excitation profile. The absent/default value preserves "
            "the historical sinusoidal current synthesis."
        ),
    )
    commutation_advance_deg: float = Field(
        default=0.0,
        ge=-180.0,
        le=180.0,
        description=(
            "Ideal six-step commutation advance in public electrical degrees; "
            "positive advance moves transitions to smaller public rotor angles"
        ),
    )
    phase_connection: Literal["wye"] = Field(
        default="wye",
        description="Phase connection. BLDC MVP supports wye only.",
    )
    excitation_rotation_convention: Literal[
        "counterclockwise_positive_solver",
        "clockwise_positive_ui",
    ] = Field(
        default="counterclockwise_positive_solver",
        exclude=True,
        description=(
            "Internal adapter provenance for excitation angle mapping. Public "
            "projects use the default and the launch adapter sets the UI frame "
            "only on its solve copy."
        ),
    )
    rated_speed_rpm: int = Field(
        default=3000,
        ge=0,
        le=30000,
        description=(
            "Rated operating speed in RPM for back-EMF voltage scaling; "
            "0 selects a static locked-rotor torque solve"
        ),
    )
    magnet_temperature_C: Optional[float] = Field(
        default=None,
        ge=-50.0,
        le=300.0,
        description=(
            "Manual magnet temperature [C] for demagnetization Br(T)/Hc(T) "
            "derating. Omit to use the room-temperature catalog properties. "
            "This field is a manual input, not a solved thermal state."
        ),
    )
    motor_input_dc_bus_V: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=2000.0,
        description=(
            "Optional motor inverter DC-link voltage used for voltage-headroom "
            "reporting. This is the DC bus feeding the inverter, not phase RMS."
        ),
    )
    max_nonlinear_iterations: Optional[int] = Field(
        default=None,
        ge=1,
        le=200,
        description="Optional native FEM nonlinear iteration cap override",
    )
    nonlinear_solver: Literal["picard", "newton"] = Field(
        default="picard",
        description=(
            "Native FEM nonlinear solve method. 'picard' is the production "
            "fallback/default. 'newton' enables the experimental damped "
            "Newton branch for hard imported-mesh saturation diagnostics."
        ),
    )
    linear_solver_preconditioner: Literal["direct", "ic0", "jacobi"] = Field(
        default="direct",
        description=(
            "Native FEM linear solver. 'direct' (default) uses the faer "
            "sparse direct Cholesky with per-mesh cached symbolic "
            "factorization — benchmarked 8.3x over 'jacobi' and 5x over "
            "'ic0' on the 8p12s fine Gmsh sweep at exact-solver parity, "
            "with IC(0) PCG as transparent fallback. 'ic0' and 'jacobi' "
            "select the iterative PCG path with the respective "
            "preconditioner, kept for parity comparisons."
        ),
    )
    linear_steel_mu_rel: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=10000.0,
        description=(
            "Diagnostic override: use fixed relative permeability for stator "
            "and rotor steel instead of nonlinear B-H iteration."
        ),
    )
    magneto2d_workers: Optional[int] = Field(
        default=None,
        ge=1,
        le=64,
        description=(
            "Native FEM rayon worker thread count for the rotor sweep. None "
            "(default) lets rayon pick the host's logical core count. Setting "
            "to 1 forces serial execution (matches the legacy --serial CLI "
            "flag) for A/B benchmarking. Setting to N pins the per-position "
            "parallel iterator to exactly N threads — useful when sharing the "
            "machine with FEMM workers or when isolating native-vs-FEMM wall-"
            "clock contributions in parity runs. Plumbed to the magneto2d "
            "subprocess via the COILEM_MAGNETO2D_WORKERS env var; per-position "
            "numerical output is invariant across pool sizes."
        ),
    )
    stream_noload_field_lines: Optional[bool] = Field(
        default=None,
        description=(
            "Optional live-preview/debug flag. When true, Native FEM includes "
            "no-load field-line frames in the solve stream for Back-EMF runs. "
            "Default/false keeps the SSE payload compact."
        ),
    )
    field_composition_source: Literal["resultant", "armature"] = Field(
        default="resultant",
        description=(
            "Source selection for an explicit field-composition solve. "
            "'resultant' uses permanent magnets and stator current; "
            "'armature' keeps magnet permeability and geometry but sets "
            "permanent-magnet remanence to zero."
        ),
    )
    rotor_rotation_model: Literal["fixed_mesh", "remesh_per_step"] = Field(
        default="fixed_mesh",
        description=(
            "How the magneto2d rotor rotates between sweep positions. "
            "'fixed_mesh' (default, back-compat) keeps a single mesh and "
            "re-tags magnet regions per step — fast but quantizes the "
            "rotor angle to element boundaries, producing staircase "
            "artifacts on 8p+ topologies. 'remesh_per_step' regenerates "
            "the mesh with the rotor baked at each angle — slower but "
            "continuous in θ; needed for accurate high-pole-count parity."
        ),
    )
    torque_method: Literal[
        "arkkio",
        "contour",
        "mst",
        "energy_fd",
        "coenergy_fd",
        "weighted_stress",
        "weighted_stress_centered",
    ] = Field(
        default="weighted_stress",
        description=(
            "Native FEM torque extractor for app-facing torque waveforms. "
            "The default weighted_stress method matches the frontend default and is "
            "mesh-density stable where contour under-reads on coarse meshes. "
            "QA no-load full-period sweeps use weighted_stress_centered; "
            "'weighted_stress_centered' otherwise falls back to Arkkio."
        ),
    )

    def effective_step_deg(self) -> float:
        """Return the rotor step in electrical degrees based on solve_quality preset.

        Native (magneto2d) step presets. These pair with
        :meth:`effective_native_loaded_sweep_range_deg`: quick and fine keep
        the 2× nested relationship with FEMM, while standard uses a shorter
        180° span to keep live solves interactive.

        Position counts per tier (range / step):
        - quick:    60° /  3.75° → 17 positions  (≈2× FEMM quick @ 9)
        - standard: 180° / 7.5°  → 25 positions  (interactive balanced tier)
        - fine:     360° / 3.75° → 96 positions  (full-cycle signoff tier)
        - custom:   honor rotor_step_deg directly
        """
        preset_steps = {
            "quick": 3.75,
            "standard": 7.5,
            "fine": 3.75,
        }
        return preset_steps.get(self.solve_quality, self.rotor_step_deg)

    def effective_native_loaded_sweep_range_deg(self) -> float:
        """Return the native-FEM sweep range in electrical degrees.

        Uses app-facing tiers for interactive Native FEM work before
        analysis-specific promotion. Native keeps the 2× dense step at each
        tier, but the balanced ``standard`` tier starts at 180° so torque-only
        live solves stay usable. The Magneto2D adapter promotes standard
        Back-EMF and THD runs to 360° when a full waveform is required.

        Policy:
        - quick: 60° partial sweep (fast UX iteration; matches FEMM quick)
        - standard: 180° half-cycle sweep (balanced UX iteration)
        - fine: full 360° cycle (trustworthy FFT bins / signoff)
        - custom: honor the explicit configured range
        """
        if self.solve_quality == "quick":
            return min(self.rotor_sweep_range_deg, 60.0)
        if self.solve_quality == "standard":
            return 360.0 if self.excitation_mode == "ideal_six_step_120" else 180.0
        if self.solve_quality == "fine":
            return 360.0
        return self.rotor_sweep_range_deg



    def estimate_positions(self, pole_pairs: int) -> int:
        """Estimate the number of torque sweep positions for a given motor.

        Mirrors the Native adapter's sweep planner
        (``_resolve_magneto2d_sweep_plan``):

        - Full-cycle sweeps (fine, span == 360°) drop the terminal
          sample so the FFT sees clean ``[0°, 360°)`` periodic support
          (``n_steps = round(span / step)``).
        - Partial sweeps (quick/standard) include both endpoints
          (``n_steps + 1``).

        Uses :meth:`effective_native_loaded_sweep_range_deg` so /solve/validate
        stays consistent with what the Native solver actually runs — otherwise
        ``standard`` (now 180°/7.5°) would report fewer positions than
        ``quick`` (60°/3.75°) because the old implementation always used the
        raw ``rotor_sweep_range_deg``.
        """
        step = self.effective_step_deg()
        sweep_range = self.effective_native_loaded_sweep_range_deg()
        n_steps = int(round(sweep_range / step))
        if sweep_range >= 360.0 - 1e-9:
            return max(2, n_steps)
        return max(2, n_steps + 1)

    def estimate_solve_time_s(
        self,
        pole_pairs: int,
        per_position_s: float = 3.0,
        *,
        include_no_load: bool = True,
    ) -> float:
        """Estimate total solve time in seconds.

        Args:
            pole_pairs: Number of pole pairs for the motor.
            per_position_s: Estimated seconds per FEMM position solve.
                Default 3.0s is a conservative estimate for a typical laptop.
            include_no_load: Whether the run includes the no-load Back-EMF/THD
                companion solve at each position. Interactive torque-only
                native runs skip it.
        """
        n_torque = self.estimate_positions(pole_pairs)
        # Back-EMF/no-load companion fields are the largest selectable cost.
        # Flux extraction/post-processing keeps a small overhead even when the
        # no-load leg is off.
        overhead_factor = 1.4 if include_no_load else 1.1
        return n_torque * per_position_s * overhead_factor


class SolveOptionsConfig(BaseModel):
    """Selective solve phase flags — controls which analyses to run."""

    torque_sweep: bool = Field(default=True, description="Run loaded torque sweep")
    back_emf: bool = Field(default=True, description="Run no-load back-EMF sweep")
    flux_density: bool = Field(default=True, description="Extract flux density map")
    cogging_torque: bool = Field(default=False, description="Run zero-current cogging torque sweep")
    torque_speed_envelope: bool = Field(default=False, description="Run solver-derived torque-speed sweep")
    thd_analysis: bool = Field(
        default=False,
        description=(
            "Compute versioned Back-EMF harmonics from a periodic no-load "
            "flux-linkage DFT (requires at least 48 positions)"
        ),
    )




class MotorConfig(BaseModel):
    """Complete motor configuration."""

    schema_version: str = Field(default="1.0", description="Schema version")
    topology: Literal["IPM", "SPM"] = Field(default="IPM", description="Motor topology")
    stator: StatorConfig = Field(..., description="Stator configuration")
    rotor: RotorConfig = Field(..., description="Rotor configuration")
    winding: WindingConfig = Field(..., description="Winding configuration")
    materials: MaterialsConfig = Field(..., description="Materials selection")
    solve_params: Optional[SolveParams] = Field(
        default=None, description="Solve parameters (required for /solve, optional for /preview)"
    )
    solve_options: Optional[SolveOptionsConfig] = Field(
        default=None, description="Selective solve phase flags (default: all enabled except cogging)"
    )

    @field_validator("schema_version")
    @classmethod
    def schema_version_must_be_1_0(cls, v):
        """Schema version must be 1.0."""
        if v != "1.0":
            raise ValueError("schema_version must be '1.0'")
        return v

    @field_validator("rotor")
    @classmethod
    def rotor_must_fit_in_stator(cls, v, info):
        """Rotor OD must be less than stator ID."""
        if info.data and "stator" in info.data and v.OD_mm >= info.data["stator"].ID_mm:
            raise ValueError(
                f"Rotor OD ({v.OD_mm}mm) must be less than stator ID "
                f"({info.data['stator'].ID_mm}mm)"
            )
        return v

    @model_validator(mode="after")
    def magnet_width_must_match_topology(self):
        """Keep SPM surface magnets at the legacy floor while allowing narrow IPM slabs."""
        if self.topology == "SPM" and self.rotor.magnet_width_mm < MIN_SPM_MAGNET_WIDTH_MM:
            raise ValueError(
                "rotor.magnet_width_mm must be at least "
                f"{MIN_SPM_MAGNET_WIDTH_MM:g} mm for SPM surface magnets"
            )
        return self

    @model_validator(mode="after")
    def excitation_contract_must_be_supported(self):
        """Reject ambiguous current meanings and unsupported six-step lanes."""
        sp = self.solve_params
        if sp is None:
            return self
        if sp.excitation_mode == "ideal_six_step_120":
            if self.topology != "SPM":
                raise ValueError(
                    "ideal_six_step_120 excitation is supported only for inner-rotor SPM in the MVP"
                )
            if sp.current_amplitude_convention != "plateau":
                raise ValueError(
                    "ideal_six_step_120 requires current_amplitude_convention='plateau'; "
                    "RMS and sine-peak inputs are not accepted"
                )
        elif sp.current_amplitude_convention == "plateau":
            raise ValueError(
                "current_amplitude_convention='plateau' requires "
                "excitation_mode='ideal_six_step_120'"
            )
        return self

    @model_validator(mode="after")
    def magnet_temperature_requires_coefficients(self):
        if self.solve_params is not None and self.solve_params.magnet_temperature_C is not None:
            raise ValueError("Magnet temperature is not supported by this preview.")
        return self
