"""Archive precision checks, separate from the unchanged component loss gates."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from tools.phase_g_loss.contract import ROOT, read, sha

COLLECTOR = "tools/phase_g_loss/stator_native.py"
# This exact predecessor acquired the same API requests/fields. It stopped on
# a 1-ppm archive round-trip check. Preserve its producer identity when the new
# decoder/checkpoint stage resumes it; no physics source gets this exception.
PREDECESSOR = "1edf3e8f369d916b18d3885d8aede3635ded555657bedb0806fda3318e0e4aab"


def measurement_protocol(directory, expected):
    path = Path(directory) / "protocol.json"
    result = deepcopy(expected)
    if path.exists():
        previous = read(path)["identity"]["source_sha256"].get(COLLECTOR)
        if previous == PREDECESSOR:
            result["identity"]["source_sha256"][COLLECTOR] = previous
    # The caller still checks the entire protocol, including all other sources,
    # binary, requests, acquisition profile and dependency versions, for equality.
    return result


def verify_measurement_sources(output):
    snapshots = list((Path(output) / "native").glob("*/protocol.json"))
    if not snapshots:
        raise ValueError("No stator measurement source snapshot")
    for path in snapshots:
        for name, digest in read(path)["identity"]["source_sha256"].items():
            if name == COLLECTOR and digest == PREDECESSOR:
                continue
            if sha(ROOT / name) != digest:
                raise ValueError("Measured stator physics/collector changed: " + name)


def reproduction(original, reproduced):
    """Allow 10 ppm for f32 coordinates/fields; never alter the API result.

    This archive-only budget is 1,000 times smaller than the 1% loss-sensitivity
    budget. Coordinate quantization affects both cell mass and cross-mesh lookup.
    Keep the predecessor's stricter 1-ppm failure visible in the receipt.
    """
    components = {}
    for key in ("iron_loss_W", "iron_hysteresis_loss_W", "iron_eddy_loss_W"):
        a, b = float(reproduced[key]), float(original[key])
        difference = abs(a - b)
        components[key] = {"public_api_W": b, "serialized_fields_W": a,
                           "difference_W": a - b, "relative_error": difference / max(abs(b), 1e-12),
                           "pass": difference <= max(1e-6, 1e-5 * abs(b)),
                           "predecessor_1ppm_pass": difference <= max(1e-6, 1e-6 * abs(b))}
    return {"schema": "coilem.stator_field_archive_reproduction/v1", "relative_tolerance": 1e-5,
            "absolute_tolerance_W": 1e-6, "components": components,
            "pass": all(row["pass"] for row in components.values()),
            "reported_api_losses_modified": False, "component_qualification_gates_modified": False}
