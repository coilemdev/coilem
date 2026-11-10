"""Pydantic models matching coilEM v1 schemas.

Sprint 27 Track 1C: split from a single 1514-line module into a package.
The public import surface is preserved — every name that used to live in
``backend/models`` is still importable from ``backend.models``.
"""

# Configuration inputs (Stator/Rotor/Winding/Materials/SolveParams/MotorConfig)
from .config import (
    DebugConfig,
    MaterialsConfig,
    MotorConfig,
    RotorConfig,
    SolveOptionsConfig,
    SolveParams,
    StatorConfig,
    WindingConfig,
)

# Diagnostic & analytical-crosscheck envelopes
from .diagnostics import (
    AnalyticalCrosscheck,
    DemagCheck,
    DiagnosticPeakBComparison,
    DiagnosticSeries,
    DiagnosticSeriesPoint,
    LoadedFieldDiagnostic,
    LossBreakdown,
    MultiRadiusSlottingDeltaSummary,
    SlotFillCheck,
    SlotlessContourComparison,
    SlotlessContourSamplePoint,
    SlotlessContourTorqueDiagnostic,
    SlotlessNoLoadDiagnostic,
    ThermalEstimate,
    TorqueSpeedEnvelope,
    WeightInertia,
)

# API error envelope
from .errors import ErrorResponse

# Field-line, airgap, slot-excitation snapshots
from .field import (
    AirgapFieldArtifactRef,
    AirgapFieldRecords,
    AirgapFieldStats,
    FieldLineContourLevel,
    FieldLineFrame,
    FieldLineFrameArtifactRef,
    FieldLineFrameSnapshot,
    FieldLinePlot,
    FieldMovieFrameRef,
    FieldMovieManifest,
    FieldMovieValueRange,
    FieldMovieViewBounds,
    SlotExcitationContribution,
    SlotExcitationFrame,
)

# Server-rendered geometry preview
from .geometry import GeometryPreview, GeometryRegion, WindingCoil, WindingSlot

# Mesh / flux-density geometry
from .mesh import (
    FemmMeshSummary,
    FluxDensityMap,
    MeshConfigSummary,
    MeshPlotInfo,
    Node,
)

# Top-level solve envelope
from .result import SolveMetadata, SolveResult, SolveSummary

# Waveforms
from .waveforms import (
    BackEMFHarmonicAnalysis,
    BackEMFHarmonicComponent,
    BackEMFWaveform,
    PhaseCurrentWaveform,
    TorqueWaveform,
)

# Resolve forward references that cross modules:
# GeometryPreview.validation_errors uses a forward "ErrorResponse" string.
GeometryPreview.model_rebuild()

__all__ = [
    # config
    "DebugConfig", "MaterialsConfig", "MotorConfig", "RotorConfig",
    "SolveOptionsConfig", "SolveParams", "StatorConfig", "WindingConfig",
    # waveforms
    "BackEMFHarmonicAnalysis", "BackEMFHarmonicComponent",
    "BackEMFWaveform", "PhaseCurrentWaveform", "TorqueWaveform",
    # mesh
    "FemmMeshSummary", "FluxDensityMap", "MeshConfigSummary", "MeshPlotInfo", "Node",
    # field
    "AirgapFieldArtifactRef", "AirgapFieldRecords", "AirgapFieldStats",
    "FieldLineContourLevel", "FieldLineFrame", "FieldLineFrameArtifactRef",
    "FieldLineFrameSnapshot", "FieldLinePlot",
    "FieldMovieFrameRef", "FieldMovieManifest",
    "FieldMovieValueRange", "FieldMovieViewBounds",
    "SlotExcitationContribution", "SlotExcitationFrame",
    # diagnostics
    "AnalyticalCrosscheck", "DemagCheck", "DiagnosticPeakBComparison",
    "DiagnosticSeries", "DiagnosticSeriesPoint", "LoadedFieldDiagnostic",
    "LossBreakdown", "MultiRadiusSlottingDeltaSummary", "SlotFillCheck",
    "SlotlessContourComparison", "SlotlessContourSamplePoint",
    "SlotlessContourTorqueDiagnostic", "SlotlessNoLoadDiagnostic",
    "ThermalEstimate", "TorqueSpeedEnvelope", "WeightInertia",
    # result
    "SolveMetadata", "SolveResult", "SolveSummary",
    # geometry
    "GeometryPreview", "GeometryRegion", "WindingCoil", "WindingSlot",
    # errors
    "ErrorResponse",
]
