"""Cylindrical and linear Halbach-array application adapters.

The package owns Halbach configuration, geometry, meshing, material
resolution, postprocessing, and exports.  It deliberately calls the generic
``magnetostatic_problem`` interface instead of adding application policy to
the Magneto2D field core.
"""

from .geometry import (
    AXIAL_END_EFFECTS_NOTICE,
    PlanarEmGeometryArtifact,
    build_planar_geometry,
)
from .linear_geometry import (
    LINEAR_MODEL_NOTICE,
    LinearPlanarGeometryArtifact,
    build_linear_planar_geometry,
)
from .linear_gmsh_adapter import (
    build_linear_magnetostatic_problem,
    generate_linear_halbach_mesh,
)
from .linear_models import (
    LinearHalbachArrayConfig,
    canonical_linear_halbach_config,
)
from .linear_solver import (
    LINEAR_HALBACH_REPORT_SCHEMA,
    LINEAR_HALBACH_SCHEMA_REGISTRY,
    LinearHalbachSolveArtifacts,
    solve_linear_halbach,
)
from .models import HalbachArrayConfig
from .solver import HalbachSolveArtifacts, solve_halbach

__all__ = [
    "AXIAL_END_EFFECTS_NOTICE",
    "HalbachArrayConfig",
    "HalbachSolveArtifacts",
    "LINEAR_MODEL_NOTICE",
    "LINEAR_HALBACH_REPORT_SCHEMA",
    "LINEAR_HALBACH_SCHEMA_REGISTRY",
    "LinearHalbachArrayConfig",
    "LinearHalbachSolveArtifacts",
    "LinearPlanarGeometryArtifact",
    "PlanarEmGeometryArtifact",
    "build_linear_magnetostatic_problem",
    "build_linear_planar_geometry",
    "build_planar_geometry",
    "canonical_linear_halbach_config",
    "generate_linear_halbach_mesh",
    "solve_halbach",
    "solve_linear_halbach",
]
