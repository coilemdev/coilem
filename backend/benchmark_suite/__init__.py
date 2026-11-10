"""Public native A-F benchmark harness; reference solvers are not dependencies."""

HARNESS_VERSION = "1.12.0"
# Protocol 1.10.0 composes the registered A-D, normal/refined E and two F source cohorts.
PROTOCOL_VERSION = "1.10.0"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {"1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.6.0", "1.7.0", "1.7.1", "1.8.0", "1.9.0", "1.10.0"}
)
PHASE_LABELS = {"A": "SPM", "B": "IPM", "C": "Distributed Winding", "D": "BLDC", "E": "Cogging", "F": "Outrunner"}
# Historical E/F suites remain replayable. Phase F retains Phase A's gates.
COMMAND_PHASES = ("A", "B", "C", "D", "E", "F")
CONVENTION = "public-clockwise-v2"
