"""The owner's 0.5.0 decisions name the reference bundle the runtime registers."""

from __future__ import annotations

import json
from pathlib import Path

from backend import resources
from backend.benchmark_suite.contract import sha
from backend.benchmark_suite.references import load_bundle, load_suite

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "benchmarks/v0.5.0/owner-decisions.json"


def test_owner_accepted_the_registered_reference_bundle():
    decisions = {item["id"]: item for item in json.loads(DECISIONS.read_text(encoding="utf-8"))["decisions"]}
    accepted = decisions["protocol16_references"]["reviewed_bundle"]
    bundle = ROOT / resources.BENCHMARK_REFERENCE_BUNDLE_DIR
    # A changed bundle needs the owner's acceptance again.
    assert accepted["path"] == resources.BENCHMARK_REFERENCE_BUNDLE_DIR
    assert accepted["manifest_sha256"] == sha(bundle / "manifest.json")
    assert accepted["review_sha256"] == sha(bundle / "review.json")
    _, _, identity = load_bundle(bundle, load_suite(ROOT / resources.BENCHMARK_SUITE_FILE))
    assert accepted["bundle_sha256"] == identity


def test_every_decision_is_dated_and_stated():
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))["decisions"]
    assert {item["id"] for item in decisions} >= {
        "protocol16_references", "v_shape", "dq_and_magnet_temperature", "inductances", "loss_benchmark",
    }
    assert all(item["date"] and item["decision"].isascii() for item in decisions)
