"""Public native A/B/C/D benchmark harness; reference solvers are not dependencies."""

HARNESS_VERSION = "1.7.0"
PROTOCOL_VERSION = "1.4.0"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0"})
PHASE_LABELS = {"A": "SPM", "B": "IPM", "C": "Distributed Winding", "D": "BLDC"}
CONVENTION = "public-clockwise-v2"
