"""Public native benchmark suites; reference solvers are not dependencies."""

HARNESS_VERSION = "1.11.0"
PROTOCOL_VERSION = "1.6.0"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.6.0", "1.7.0", "1.8.0"})
PHASE_LABELS = {"A": "SPM", "B": "IPM", "C": "Distributed Winding", "D": "BLDC", "E": "Cogging", "F": "Outrunner"}
# The public command composes three independently bound suites. The low-level
# default protocol remains 1.6; Phase E is experimental and Phase F has its own
# reviewed Windows engineering scope.
COMMAND_PHASES = ("A", "B", "C", "D", "E", "F")
CONVENTION = "public-clockwise-v2"
