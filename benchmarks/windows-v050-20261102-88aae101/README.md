# Windows protocol 1.6 evidence for coilEM 0.5.0

Measured native candidate: **`88aae101fd487795e7fe5300737679f4133790fd`**
(coilEM 0.5.0, Magneto2D 0.4.0, [PR #179](https://github.com/coilemdev/coilem/pull/179)).
Collected on the physical Windows 11 x86_64 host on November 2, 2026.
This publication adds evidence after the measured commit. It executes no
field solves and does not restamp the collection or promote qualification.

## Registered results

All **52 supported native jobs completed**, with zero registered execution
errors. The protocol **1.6.0** comparison has **46 PASS**, **one planned
UNSUPPORTED** row and **336/336 gates PASS**. The unsupported legacy
`ornl_prius_2004_ipm` entry is separate from the Pyleecan Prius benchmark.

| Phase | PASS | UNSUPPORTED |
| --- | ---: | ---: |
| A: SPM | 19 | 0 |
| B: IPM | 20 | 0 |
| C: distributed winding | 4 | 1 |
| D: ideal six-step | 3 | 0 |

The 17 additions comprise one shoed example, four magnet-temperature cases
and 12 loaded d/q points. All pass their registered gates. Across the d/q
points, maximum lambda_d and lambda_q errors are **0.56285%** and
**0.18767%** of the reference flux-vector magnitude, against the unchanged
3% green limit. The reference torque self-check's maximum error is
**1.14247%**, against its unchanged 2% green limit. These outcomes do not
qualify apparent inductances, a flux map or a torque-speed envelope.

- [HTML report with plots](comparison/report/coilem_benchmark_report.html)
- [Full numerical report](comparison/report/benchmark_summary.json)
- [CSV](comparison/report/benchmark_results.csv) and
  [Markdown report](comparison/report/benchmark_report.md)
- [Native collection manifest](native/run_manifest.json), with the original
  request/result files and hashes under `native/jobs/`
- [Compact Windows record](windows-x86_64.json), retained beside this evidence;
  it does **not** replace the active historical record in `benchmarks/records`
- [Publication receipt](publication.json), identifying every byte-preserved
  copied artifact, and [package checksums](artifact_manifest.json)

The original renderer's checksum manifest predates the development-scope
banners in the HTML and Markdown views. It is preserved as
`comparison/report/artifact_manifest.original.json`; the adjacent
`artifact_manifest.json` now hashes the actual rendered files. The publication
receipt records this presentation-only correction. All copied measurements,
native/reference identities, numerical evaluations and report banners remain
unchanged.

## Reference identity and review

The 46 fresh FEMM records use the sealed protocol 1.6 bridge at private adapter
commit **`faced858937e93740ddf7f6f3583a3ad5ec35646`**. The recovered v3
adapter/runtime sources and FEMM executables are preserved in a separate local
archive; [public provenance](../reference-adapters/windows-femm42-v3-20261102/README.md)
records its hashes and the executable/COM identity. Private source, binaries,
model files and field files are not included here.

| Identity | SHA-256 |
| --- | --- |
| Registered protocol 1.6 suite | `60fb1c5353c8678ef210c997cf39ddcf20ce4bf81ebd8e419c962fc6d5c6fb37` |
| Original native manifest | `22b6b58b66906d9f11f4d4014b1e713b1cb9b8cc465f1271fc1bd3eef04ef1f5` |
| Measured Magneto2D binary | `01218ee2422510660d7afad37bcb8d97605e4c54ecdbd87ed94b7e17c00a090f` |
| Reference manifest file | `71afbb5d50551c1ac22f9e502e61f96e2f726bb3331286fc53edec012e416da1` |
| Loader's canonical reference-bundle identity | `c96b5e7948aea74bcf7943d584db85b874a2d4e887e0637c84e59e98c8dfd31a` |

The manifest-file hash and canonical bundle identity serve different purposes;
`load_bundle()` and compact records use the latter. The
[reference manifest](reference-bundle/manifest.json) and all record files are
byte-for-byte copies. Their status remains **REVIEW_REQUIRED**.

Legacy cases preserve the recovered v3 current-density and slot-flux methods.
The shoed and d/q cases use predeclared explicit phase circuits; temperature
cases use their registered remanence. The two repeated physical inputs expose
small density/circuit differences rather than selecting a preferred result.
See [source-method observations](reference-bundle/source-method-review.json)
and the [remaining reference review](REFERENCE_REVIEW.md).

The original native collection used `--no-reference`. The subsequent
[comparison manifest](comparison/comparison_manifest.json) binds that immutable
manifest and its request/result hashes to the new reference bundle. The join
executed zero field solves. Its report banner preserves the development scope.
Non-user host paths in the original audit files are retained to preserve their
hashes; they are not portable reproduction instructions. Logs and process locks
are omitted.

## Published Mac comparison

The [paired results](macos-comparison.txt) and
[machine-readable comparison](macos-comparison.json) use the published Mac data:
35 jobs from the [full report at `5b7cad8`](../macos-native-20261022-5b7cad8/README.md)
and the rounded table for 17 additions at `f6c9fbb` in
[FEMM-REQUEST.md](../abcd-v1.6/FEMM-REQUEST.md). All 52 jobs have comparisons;
no available torque/EMF metrics exceed the existing platform tolerances.
Near-zero torque uses the absolute tolerance floor. D/q flux-vector differences
are diagnostic; no platform tolerance for those values is registered.

These are **historical comparisons across different source commits**. Full raw
Mac results for the 17 additions are unavailable here. This publication retains
that limitation and does not create or repin a same-candidate Mac record.
Different hardware and overlapping native/FEMM work prevent a controlled speed
comparison.

## v0.4.0 comparison and V-shape

The [direct version comparison](../reference-adapters/windows-femm42-v3-20261102/version-comparison.txt)
compares the v0.4.0 report at `5b6cb61` with this run. All 29 shared supported
cases reproduce their checked legacy reference data exactly; the A/B/C
evaluator and its 8% torque / 10% EMF green limits are unchanged.

The V-shape baseline changes from YELLOW to PASS as peak-EMF error falls from
14.7787% to 9.0128%. Torque error increases from 5.8454% to 7.0224% and
fundamental-EMF error from 2.0563% to 8.2864%. Across six V-shape fixtures,
mean fundamental error increases from 2.3866% to 6.5029%. **V-shape remains
experimental.** Corrected nonlinear stopping does not establish improved
reference or hardware agreement.

The separate [V-shape control](vshape-convergence-control.txt) passes all six
comparison gates against a tighter-precision reference with finer rotor
segments/arcs. It preserves the registered matrix. It uses a different mesh
recipe and reference basis from the earlier VM diagnostic, and is not a
spatial-convergence proof. No VM replay is required for this publication.

## Rebuild the compact record without collecting fields

From the repository root:

```sh
python -m tools.build_benchmark_record \
  benchmarks/windows-v050-20261102-88aae101/comparison/report \
  --suite benchmarks/abcd-v1.6/benchmark_spec.json \
  --reference-bundle benchmarks/windows-v050-20261102-88aae101/reference-bundle \
  --out /path/outside/checkout/windows-x86_64.json
```

The explicit paths do not change the runtime's default suite or active
qualification basis. The [v0.5.0 evidence index](../v0.5.0/README.md) records
what still prevents release qualification.
