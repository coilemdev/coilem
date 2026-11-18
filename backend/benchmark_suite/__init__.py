"""Public native A-G benchmark harness; reference solvers are not dependencies."""

HARNESS_VERSION = "1.13.0"
# Protocol 1.10.0 composes the registered A-D, normal/refined E and two F source cohorts.
PROTOCOL_VERSION = "1.12.0"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {"1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.6.0", "1.7.0", "1.7.1", "1.8.0", "1.9.0", "1.10.0", "1.11.0", "1.12.0"}
)
# Protocol 1.11.0 solves the protocol 1.10.0 cases as one repeating sector, against the same references.
SECTOR_PROTOCOL_VERSION = "1.11.0"
PHASE_LABELS = {"A": "SPM", "B": "IPM", "C": "Distributed Winding", "D": "BLDC", "E": "Cogging", "F": "Outrunner", "G": "Stator / DC losses"}
# Historical E/F suites remain replayable. Phase F retains Phase A's gates.
COMMAND_PHASES = ("A", "B", "C", "D", "E", "F", "G")
CONVENTION = "public-clockwise-v2"
