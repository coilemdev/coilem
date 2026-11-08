"""Pin the three public benchmark suites without changing requests or gates."""

from backend.benchmark_suite.collection import COLLECTION_FILE, COLLECTION_SCHEMA, PUBLIC_PHASES
from backend.benchmark_suite.command import QUICK_PHASE_CASES
from backend.benchmark_suite.contract import DATA_ROOT, sha, write
from backend.benchmark_suite.references import load_bundle, load_suite


def descriptor(root=DATA_ROOT):
    groups = [
        ("abcd", list("ABCD"), "benchmarks/abcd-v1.6/benchmark_spec.json",
         "benchmarks/reference-baselines/protocol16-reviewed-20261103",
         {platform: f"benchmarks/records/{platform}.json" for platform in ("windows-x86_64", "macos-arm64")}),
        ("phase-e", ["E"], "benchmarks/abcd-v1.7/benchmark_spec.json",
         "benchmarks/reference-baselines/phase-e-experimental-20261108", {}),
        ("phase-f", ["F"], "benchmarks/abcd-v1.8/benchmark_spec.json",
         "benchmarks/reference-baselines/phase-f-reviewed-20261108",
         {"windows-x86_64": "benchmarks/records/phase-f/windows-x86_64.json"}),
    ]
    components = []
    for component_id, phases, suite, bundle, records in groups:
        _, _, identity = load_bundle(root / bundle, load_suite(root / suite))
        components.append({
            "id": component_id, "phases": phases, "experimental": phases == ["E"],
            "suite": {"file": suite, "sha256": sha(root / suite)},
            "reference_bundle": {"directory": bundle, "manifest_sha256": sha(root / bundle / "manifest.json"),
                                 "identity_sha256": identity},
            "quick_cases": {phase: QUICK_PHASE_CASES[phase] for phase in phases},
            "records": {platform: {"file": path, "sha256": sha(root / path)} for platform, path in records.items()},
        })
    return {"schema": COLLECTION_SCHEMA, "phases": list(PUBLIC_PHASES), "components": components}


if __name__ == "__main__":
    write(DATA_ROOT / COLLECTION_FILE, descriptor())
