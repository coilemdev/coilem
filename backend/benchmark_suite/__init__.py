"""Public native A/B/C/D benchmark harness; reference solvers are not dependencies."""

HARNESS_VERSION = "1.10.0"
PROTOCOL_VERSION = "1.6.0"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.6.0", "1.7.0", "1.8.0"})
PHASE_LABELS = {"A": "SPM", "B": "IPM", "C": "Distributed Winding", "D": "BLDC", "E": "Cogging", "F": "Outrunner"}
# `coilem benchmark` runs the default protocol, which has no Phase E or F: cogging and outer rotors are their own
# suites (protocols 1.7.0 and 1.8.0). Phase F is graded with Phase A's gates.
COMMAND_PHASES = ("A", "B", "C", "D")
CONVENTION = "public-clockwise-v2"
