# v0.5.0 candidate review and qualification

Measured field source: **`88aae101fd487795e7fe5300737679f4133790fd`**
(coilEM 0.5.0, Magneto2D 0.4.0). Collection started November 2, 2026, on
the physical Windows host. This folder uses the UTC date of the qualification
follow-up. Evidence publication does not change the measured commit.

| Evidence | Outcome |
| --- | --- |
| [Reviewed FEMM bundle](../reference-baselines/protocol16-reviewed-20261103/README.md) | All 46 records accepted for registered parity; original record bytes retained |
| [Windows report](windows/report/coilem_benchmark_report.html), [numerical report](windows/report/benchmark_summary.json) | 46 PASS, one planned UNSUPPORTED; 336/336 gates PASS |
| [Saved FEMM material audit](reference-material-audit.json) | All 4,409 nonempty saved models match registered units, depth, solver settings, magnet inputs and the complete M350-50A curve |
| [Declared-current audit](reference-current-audit.json) | All 46 cases match their declared current magnitude and convention; maximum error below 4.3e-14 A |
| Exact-candidate Mac A–D | Collection pending; the older published Mac comparison keeps its historical pins |
| Exact-candidate Windows Prius | Full 17-job / 568-field-report collection in progress; no partial run is qualified |

The reference reviewer is **Codex assistant**, which also prepared the earlier
evidence. This is a documented code and data review, not an independent human
or laboratory sign-off. Its scope and exclusions are in the hash-bound
[review receipt](../reference-baselines/protocol16-reviewed-20261103/review.json).
Private adapter sources, FEMM model files and field files remain in the retained
local archive; public records contain data and provenance only.

The reviewed bundle has canonical SHA-256
`756ddf1e23417e502c6720e11010199bbf25692bc348b019b1b78c620ec1d4d8`.
It derives from the immutable original bundle
`c96b5e7948aea74bcf7943d584db85b874a2d4e887e0637c84e59e98c8dfd31a`;
only the manifest and review receipt are new. Its 46 numerical records are
byte-identical to the original collection.

## How the comparison is reproduced

`tools.qualify_benchmark_candidate` verifies the clean full-grid native run,
all request and result hashes, exact registered inputs, the measured source
and the reviewed reference receipt before evaluating any row. It executes
**zero field solves** and leaves the original manifest and artifacts unchanged.
The [Windows comparison manifest](windows/comparison_manifest.json) binds the
original native artifact hashes and the reviewed reference identity.

The active physics guard now covers **63 sources**. Nine previously omitted
d/q, temperature, configuration, policy, material and resistance/loss sources
were already hashed in the candidate's full identity before collection.
Their current bytes match those original hashes. The original 54-source record
and all historical reports remain intact; no changed physics is repinned.

The historical v0.4 records are retained byte-for-byte in
[`records-historical/v040`](../records-historical/v040/).
The active Windows compact record is rebuilt from the reviewed comparison.
The Mac record will change only after a complete matching collection exists.

## Scope and remaining gates

Registered field parity covers 19 SPM single-layer concentrated operating
points, 14 flat-IPM cases, four distributed-winding cases and three six-step
fixtures (42 gates). V-shape passes all six registered cases but remains
experimental: its fundamental-EMF discrepancy increased from v0.4.0, and a
single reference-mesh sensitivity control does not establish spatial convergence.
The legacy ORNL Prius case is planned unsupported; it is separate from the
Pyleecan Prius software benchmark.

Loaded d/q and temperature comparisons pass at the registered points. The
application still labels its new performance outputs experimental, except
phase resistance and copper loss with a declared wire. This review does not
qualify apparent inductances, maps, losses, hardware correlation, catalogue
temperature coefficients or arbitrary operating ranges.

The release gate remains blocked until complete same-candidate Mac and Prius
evidence is registered. Check it with:

```sh
python -m tools.release.qualification --candidate 88aae101fd487795e7fe5300737679f4133790fd
```

Wheel/TestPyPI acceptance, final installed-package checks, owner release
acceptance and publication remain separate release work. No release tag or
publication is created by this qualification update.
