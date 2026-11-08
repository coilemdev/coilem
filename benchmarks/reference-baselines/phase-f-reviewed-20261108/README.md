# Reviewed Windows Phase F references

This data-only protocol 1.8.0 bundle is accepted for **Windows x86-64 engineering
parity**. Its ten normal records produced 60 passing Magneto2D/FEMM comparison
gates. Both air-gap mesh controls and all 30 reference self-checks pass.

The reference identity is the SHA-256 dataset identifier in `manifest.json`.
It is not a Git commit. Schema `coilem.frozen_reference_bundle/v2` records two
actual source cohorts: `original` and `hub_bulk_mesh_variant`. Each cohort is
bound to a retained evidence capsule by a SHA-256 digest. Private field-generator
identities and machine paths are excluded from this public projection.

The original one-producer-commit requirement is **not claimed satisfied**.
The versioned, Windows-only review explicitly accepts the two-cohort collection
and the hub's 0.5 mm bulk-mesh exception. Air-gap and magnet mesh settings remain
documented in the numeric records and source review. The two spot controls are
not a full-sweep mesh-convergence study.

The LRK check remains **9 PASS / 2 FAIL** under its unchanged tolerances.
`lrk-sensitivity-review.json` preserves both failed values, their original
limits and measured sensitivity context. The project owner accepts this
numerical sensitivity for the present Windows engineering evidence. The
deterministic controls do not establish a statistical noise floor, confidence
interval or candidate uncertainty bound.

`review.json` binds every record, the complete manifest payload, both cohort
capsules, the self-checks and the owner's private decision receipt digest. The
original measurements and gate results are retained without reclassification.

This review does not qualify macOS, Linux, cogging, loaded d/q, inductance,
temperature derating, losses or efficiency. The current A–D default protocol
and its reviewed bundle remain independent.

Recheck the public numeric projection without running a field solver:

```sh
python -m tools.verify_phase_f_windows_packet
```
