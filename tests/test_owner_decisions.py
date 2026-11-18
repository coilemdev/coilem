"""The owner's 0.5.0 decisions name the reference bundle the runtime registers."""

from __future__ import annotations

import json
from pathlib import Path

from backend import resources
from backend.benchmark_suite.contract import sha
from backend.benchmark_suite.references import load_bundle, load_suite

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "benchmarks/v0.5.0/owner-decisions.json"


def _component(suite_path: Path, component_id: str) -> dict | None:
    """The component with this id in a suite or, depth first, in the suites it is composed of."""

    for component in load_suite(suite_path).get("components", []):
        if component["id"] == component_id:
            return component
        found = _component(ROOT / component["suite"], component_id) if component.get("suite") else None
        if found is not None:
            return found
    return None


def test_owner_accepted_the_registered_reference_bundle():
    decisions = {item["id"]: item for item in json.loads(DECISIONS.read_text(encoding="utf-8"))["decisions"]}
    accepted = decisions["protocol16_references"]["reviewed_bundle"]
    # The A-D references sit inside the registered suite: since Phase G the A-G
    # suite holds the A-F suite, which holds them.
    component = _component(ROOT / resources.BENCHMARK_SUITE_FILE, "abcd")
    assert component is not None
    bundle = ROOT / component["reference_bundle"]
    # A changed bundle needs the owner's acceptance again.
    assert accepted["path"] == component["reference_bundle"]
    assert accepted["manifest_sha256"] == sha(bundle / "manifest.json")
    assert accepted["review_sha256"] == sha(bundle / "review.json")
    _, _, identity = load_bundle(bundle, load_suite(ROOT / component["suite"]))
    assert accepted["bundle_sha256"] == identity


def test_every_decision_is_dated_and_stated():
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))["decisions"]
    assert {item["id"] for item in decisions} >= {
        "protocol16_references", "v_shape", "dq_and_magnet_temperature", "inductances", "loss_benchmark",
    }
    assert all(item["date"] and item["decision"].isascii() for item in decisions)
