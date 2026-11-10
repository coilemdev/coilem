"""Data contracts for motor field. """

from typing import Any, Optional

from pydantic import BaseModel, Field

from .mesh import MeshConfigSummary, MeshPlotInfo


class FieldLineContourLevel(BaseModel):
    """One contour level worth of line segments in millimeters."""

    level: float = Field(..., description="A_z contour level")
    segments_mm: list[list[float]] = Field(
        default_factory=list,
        description="Line segments as [x1, y1, x2, y2] in mm",
    )
    segment_b_mag_t: list[float] = Field(
        default_factory=list,
        description="Representative |B| in Tesla for each contour segment",
    )
    segment_bx_t: list[float] = Field(
        default_factory=list,
        description="Representative B_x in Tesla for each contour segment",
    )
    segment_by_t: list[float] = Field(
        default_factory=list,
        description="Representative B_y in Tesla for each contour segment",
    )


class FieldLinePlot(BaseModel):
    """Solved mesh plus field-line contour geometry for the results viewer."""

    config_summary: MeshConfigSummary = Field(..., description="Mesh plot config summary")
    mesh_info: MeshPlotInfo = Field(..., description="Mesh metadata")
    nodes_mm: list[list[float]] = Field(..., min_length=1, description="Mesh nodes [x, y] in mm")
    triangles: list[list[int]] = Field(..., min_length=1, description="Triangle node indices")
    regions: list[str] = Field(..., min_length=1, description="Region tag per triangle")
    element_b_mag_t: list[float] = Field(
        default_factory=list,
        description="Element-constant |B| in Tesla, aligned with triangles",
    )
    element_bx_t: list[float] = Field(
        default_factory=list,
        description="Element-constant B_x in Tesla, aligned with triangles",
    )
    element_by_t: list[float] = Field(
        default_factory=list,
        description="Element-constant B_y in Tesla, aligned with triangles",
    )
    contour_levels: list[FieldLineContourLevel] = Field(
        default_factory=list,
        description="Contour line segments grouped by A_z level",
    )
    az_min: float = Field(..., description="Minimum nodal A_z value")
    az_max: float = Field(..., description="Maximum nodal A_z value")
    n_pole_pitches: int = Field(..., ge=1, description="Number of pole pitches shown")
    total_span_deg: float = Field(..., gt=0, description="Total modeled span [deg]")


class AirgapFieldRecords(BaseModel):
    """Pre-computed airgap |B| records for one solved field snapshot.

    FEMM remeshes per rotor position and the per-frame mesh + element_b
    arrays are too large to persist (Aw-Snap OOM at 36+ positions).
    Instead, the solver pre-filters to airgap-only triangles and ships
    just the centroid coordinates + |B|, which is what the frontend's
    Compare airgap stats and trace chart actually need.

    Parallel arrays for compactness; index i maps across all three.
    """

    centroid_x_mm: list[float] = Field(
        default_factory=list,
        description="Triangle centroid x in mm for airgap-band triangles",
    )
    centroid_y_mm: list[float] = Field(
        default_factory=list,
        description="Triangle centroid y in mm for airgap-band triangles",
    )
    b_magnitude_t: list[float] = Field(
        default_factory=list,
        description="Element-constant |B| in Tesla for airgap-band triangles",
    )
    b_radial_t: list[float] = Field(
        default_factory=list,
        description=(
            "Element-constant radial-direction B (B_r) in Tesla for "
            "airgap-band triangles. Same index space as centroid_x_mm. "
            "Populated when the source frame had element_bx_t / element_by_t."
        ),
    )
    b_tangential_t: list[float] = Field(
        default_factory=list,
        description=(
            "Element-constant tangential-direction B (B_t) in Tesla for "
            "airgap-band triangles. Same index space as centroid_x_mm."
        ),
    )


class AirgapFieldStats(BaseModel):
    """Compact stats computed from the full airgap field artifact."""

    count: int = Field(default=0, ge=0, description="Number of full airgap records")
    mean_t: float = Field(default=0.0, description="Mean airgap |B| [T]")
    p95_t: float = Field(default=0.0, description="95th percentile airgap |B| [T]")
    max_t: float = Field(default=0.0, description="Maximum airgap |B| [T]")


class AirgapFieldArtifactRef(BaseModel):
    """Opaque reference to full airgap records stored outside the UI payload."""

    artifact_id: str = Field(..., description="Opaque id for /solve/artifacts/{artifact_id}")
    format: str = Field(default="json.gz", description="Artifact encoding")
    media_type: str = Field(default="application/json+gzip", description="Download media type")
    schema_version: str = Field(default="openem.airgap_field_records.v1")
    record_count: int = Field(default=0, ge=0)
    byte_count: Optional[int] = Field(default=None, ge=0)
    relative_path: Optional[str] = Field(default=None, description="Debug relative path under solve cache")


class FieldLineFrameArtifactRef(BaseModel):
    """Opaque reference to one solved field-line frame stored outside the UI payload."""

    artifact_id: str = Field(..., description="Opaque id for /solve/artifacts/{artifact_id}")
    format: str = Field(default="json.gz", description="Artifact encoding")
    media_type: str = Field(default="application/json+gzip", description="Download media type")
    schema_version: str = Field(default="openem.field_line_frame.v1")
    record_count: int = Field(default=0, ge=0)
    byte_count: Optional[int] = Field(default=None, ge=0)
    relative_path: Optional[str] = Field(default=None, description="Debug relative path under solve cache")


class FieldMovieValueRange(BaseModel):
    """Global scalar range baked into a packaged field visualization movie.

    The ``*_t`` field names are retained for API compatibility. They carry
    Tesla for B-field heatmaps and A_z units for scalar field-line grids.
    """

    min_t: float = Field(..., description="Global minimum |B| across the movie [T]")
    max_t: float = Field(..., description="Global maximum |B| across the movie [T]")
    p95_t: float = Field(..., description="95th percentile |B| (informational) [T]")


class FieldMovieViewBounds(BaseModel):
    """Motor-space rectangle the rasterized frames cover, so the frontend can place them."""

    x_mm: float = Field(..., description="Left edge in motor mm coordinates")
    y_mm: float = Field(..., description="Top edge in motor mm coordinates")
    width_mm: float = Field(..., gt=0, description="Width in mm")
    height_mm: float = Field(..., gt=0, description="Height in mm")


class FieldMovieFrameRef(BaseModel):
    """Opaque reference to one rasterized field-movie frame stored under the solve cache."""

    index: int = Field(..., ge=0, description="Frame index in playback order")
    artifact_id: str = Field(..., description="Opaque id for /solve/artifacts/{artifact_id}")
    electrical_angle_deg: float = Field(..., description="Electrical angle [deg] for this frame")
    mechanical_angle_deg: Optional[float] = Field(
        default=None, description="Mechanical angle [deg], when pole-pair count is known"
    )
    format: str = Field(default="webp", description="Image encoding (webp or png)")
    media_type: str = Field(default="image/webp", description="Download media type")
    byte_count: Optional[int] = Field(default=None, ge=0)
    relative_path: Optional[str] = Field(default=None, description="Debug relative path under solve cache")


class FieldMovieManifest(BaseModel):
    """Backend-packaged field visualization movie."""

    schema_version: str = Field(default="openem.field_movie.v1")
    mode: str = Field(
        default="full_field_b_magnitude",
        description="Visualization mode this movie was rendered for",
    )
    fps: int = Field(default=24, ge=1, le=120, description="Suggested playback frame rate")
    frame_count: int = Field(..., ge=1, description="Number of frames in the movie")
    source_solved_positions: int = Field(
        ..., ge=1, description="Number of solved rotor positions the movie was built from"
    )
    width_px: int = Field(..., ge=64, description="Pixel width of each frame")
    height_px: int = Field(..., ge=64, description="Pixel height of each frame")
    value_range: FieldMovieValueRange = Field(..., description="Global |B| range baked into the movie")
    view_bounds: FieldMovieViewBounds = Field(..., description="Motor-space rectangle covered by each frame")
    manifest_artifact_id: Optional[str] = Field(
        default=None, description="Opaque id pointing at the manifest.json on disk"
    )
    frames: list[FieldMovieFrameRef] = Field(
        default_factory=list, description="Ordered frame artifact references"
    )


class FieldLineFrameSnapshot(BaseModel):
    """Field-line renderer payload for one solved field snapshot.

    Live FEMM frames normally carry backend-processed contour and airgap profile
    data, not repeated per-position mesh arrays. Mesh metadata remains optional
    for cached native frames and explicit FEMM diagnostics.
    """

    config_summary: Optional[dict[str, Any]] = Field(
        default=None, description="Optional mesh plot config summary"
    )
    mesh_info: Optional[dict[str, Any]] = Field(
        default=None, description="Optional mesh metadata"
    )
    nodes_mm: list[list[float]] = Field(
        default_factory=list, description="Mesh nodes [x, y] in mm"
    )
    triangles: list[list[int]] = Field(
        default_factory=list, description="Triangle node indices"
    )
    regions: list[str] = Field(
        default_factory=list, description="Region tag per triangle"
    )
    element_b_mag_t: list[float] = Field(
        default_factory=list,
        description="Element-constant |B| in Tesla, aligned with triangles",
    )
    element_bx_t: list[float] = Field(
        default_factory=list,
        description="Element-constant B_x in Tesla, aligned with triangles",
    )
    element_by_t: list[float] = Field(
        default_factory=list,
        description="Element-constant B_y in Tesla, aligned with triangles",
    )
    airgap_brbt: Optional[dict[str, Any]] = Field(
        default=None,
        description="Compact binned airgap Br/Bt profile for live field charts",
    )
    contour_levels: list[FieldLineContourLevel] = Field(
        default_factory=list,
        description="Contour line segments grouped by A_z level",
    )
    az_min: Optional[float] = Field(default=None, description="Minimum nodal A_z value")
    az_max: Optional[float] = Field(default=None, description="Maximum nodal A_z value")
    n_pole_pitches: Optional[int] = Field(
        default=None, ge=0, description="Number of pole pitches shown"
    )
    total_span_deg: Optional[float] = Field(
        default=None, ge=0, description="Total modeled span [deg]"
    )
    airgap_b_records: Optional[AirgapFieldRecords] = Field(
        default=None,
        description=(
            "Display-sized airgap-band |B| records (centroids + magnitudes). "
            "Full records live in airgap_b_artifact; stats and trace bins are "
            "computed before sampling."
        ),
    )
    airgap_b_stats: Optional[AirgapFieldStats] = Field(
        default=None,
        description="Stats computed from the full, unsampled airgap field records.",
    )
    airgap_b_artifact: Optional[AirgapFieldArtifactRef] = Field(
        default=None,
        description="Reference to the full airgap field records artifact.",
    )
    field_frame_artifact: Optional[FieldLineFrameArtifactRef] = Field(
        default=None,
        description="Reference to this solved field-line frame artifact.",
    )
    full_field_frame_artifact: Optional[FieldLineFrameArtifactRef] = Field(
        default=None,
        description="Reference to this solved field frame with mesh and per-element field arrays.",
    )


class FieldLineFrame(FieldLineFrameSnapshot):
    """Per-angle field frame persisted for solver-vs-solver visual compare."""

    angle_deg: float = Field(..., description="Electrical angle for this field frame [deg]")
    noload_plot: Optional[FieldLineFrameSnapshot] = Field(
        default=None,
        description="Optional no-load field snapshot aligned to this loaded frame",
    )


class SlotExcitationContribution(BaseModel):
    """Per-slot ampere-turn injection and current-density evidence.

    Mirrors the native solver's slot contribution record so result views can
    compare phase, direction, area and current scaling at each modeled slot.
    """

    slot_index_modeled: int = Field(..., ge=0, description="Slot index within the modeled sector")
    slot_index_global: int = Field(..., ge=0, description="Slot index in the full motor (0..slot_count-1)")
    phase: str = Field(..., description="Phase label: A, B, or C")
    direction: str = Field(..., description="Coil direction: 'in' or 'out' (sign convention)")
    center_angle_mech_deg: float = Field(..., description="Slot centroid angle in mechanical degrees")
    slot_area_m2: float = Field(..., ge=0.0, description="Total slot area used for J integration, m²")
    effective_current_density_a_per_m2: float = Field(
        ..., description="Area-weighted current density actually applied, A/m² (signed)"
    )
    integrated_amp_turns_a: float = Field(
        ...,
        description="∫J·dA over the slot region — total ampere-turns injected (signed by direction)",
    )
    slot_current_a: float = Field(
        ..., description="Slot current = ampere-turns / turns_per_coil, signed"
    )
    phase_current_a: float = Field(..., description="Phase current at this electrical angle, signed")
    turns_per_coil: int = Field(..., ge=1, description="Coil turns count used in J = N·I/A")


class SlotExcitationFrame(BaseModel):
    """Per-angle slot excitation summary for sweep diagnostics."""

    angle_deg: float = Field(..., description="Rotor electrical angle for this field frame")
    source_current_angle_deg: Optional[float] = Field(
        default=None,
        description="Electrical source-current angle used to synthesize phase currents",
    )
    phase_current_a: Optional[list[float]] = Field(
        default=None,
        description="Instantaneous phase currents [Ia, Ib, Ic] in Amperes",
    )
    contributions: list[SlotExcitationContribution] = Field(
        default_factory=list,
        description="Per-slot ampere-turn breakdown at this electrical angle",
    )
