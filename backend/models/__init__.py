"""Public data models used by the local Magneto2D boundary."""

from .config import (
    MaterialsConfig,
    MotorConfig,
    RotorConfig,
    SolveOptionsConfig,
    SolveParams,
    StatorConfig,
    WindingConfig,
)
from .errors import ErrorResponse
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
from .geometry import GeometryPreview, GeometryRegion, WindingCoil, WindingSlot
from .mesh import FluxDensityMap, MeshConfigSummary, MeshPlotInfo, Node
from .result import SolveMetadata, SolveResult, SolveSummary
from .waveforms import (
    BackEMFHarmonicAnalysis,
    BackEMFHarmonicComponent,
    BackEMFWaveform,
    PhaseCurrentWaveform,
    TorqueWaveform,
)

GeometryPreview.model_rebuild()

__all__ = [
    "AirgapFieldArtifactRef",
    "AirgapFieldRecords",
    "AirgapFieldStats",
    "BackEMFHarmonicAnalysis",
    "BackEMFHarmonicComponent",
    "BackEMFWaveform",
    "PhaseCurrentWaveform",
    "ErrorResponse",
    "FieldLineContourLevel",
    "FieldLineFrame",
    "FieldLineFrameArtifactRef",
    "FieldLineFrameSnapshot",
    "FieldLinePlot",
    "FieldMovieFrameRef",
    "FieldMovieManifest",
    "FieldMovieValueRange",
    "FieldMovieViewBounds",
    "FluxDensityMap",
    "GeometryPreview",
    "GeometryRegion",
    "MaterialsConfig",
    "MeshConfigSummary",
    "MeshPlotInfo",
    "MotorConfig",
    "Node",
    "RotorConfig",
    "SlotExcitationContribution",
    "SlotExcitationFrame",
    "SolveMetadata",
    "SolveOptionsConfig",
    "SolveParams",
    "SolveResult",
    "SolveSummary",
    "StatorConfig",
    "TorqueWaveform",
    "WindingCoil",
    "WindingConfig",
    "WindingSlot",
]
