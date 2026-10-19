# Windows Precise mesh requalification (October 18, 2026)

The native A/B/C/D suite measured clean, detached commit
**`f390b252d8c7dddc3b7ff9f2c1c4f6cbf1d10d4c`** on October 18, 2026.
All **35 supported jobs** completed; the planned Prius case is unsupported.
The run used the default **Precise** mesh build and default process-pool policy,
with the release solver built in that checkout using `cargo build --release --locked`.
No solver binary or pool overrides were set.

| Phase | Outcomes |
| --- | --- |
| A: SPM | 10 PASS |
| B: IPM | 11 PASS, 1 YELLOW |
| C: distributed winding | 4 PASS, 1 planned unsupported Prius |
| D: BLDC | 3 PASS |

The manifest is **COMPLETE**, exit code **0**, with no resume or rerun.
Every verdict, gate and recorded numerical value is **exactly identical** to
the [previous Windows v3 record](../windows-v3-20261015-738d951/README.md).
The self-check applied no numerical tolerances and ran no additional fields.
Its [complete diff](self-check-differences.json) records only provenance,
runtime and source-hash changes, including the changed `backend/gmsh_solver.py`.

## Measured and reference identities

This run measured harness **1.5.0 / protocol 1.3.0**, including the winding-axis
six-step checks, directly at `f390b25`. It joined the unchanged frozen
[`ipm-high-output-v3`](../reference-baselines/ipm-high-output-v3/manifest.json)
reference measured at `738d951`; **no FEMM solves ran**. The reference bundle
digest remains `95450ffcb909ed20caf514548f741c15611087a3482657c87add4255b308ba63`.

The qualified combinations and registered gates are unchanged; see
[qualification status](../../docs/VALIDATION.md#qualification-status).
The V-shape baseline remains YELLOW and the Prius remains unsupported.
**Fast mesh remains experimental** because this run measured Precise only.
The FEMM bundle's `REVIEW_REQUIRED` scientific limitations remain in force.
The historical macOS record has not been remeasured for this source change.

## Environment and timings

Windows 11 Home 25H2, build **26200.9711**, x86_64; AMD Ryzen 7 7700,
8 physical / 16 logical cores, 64 GB RAM; Python **3.12.14** with locked
requirements; rustc and cargo **1.95.0**.
The solver SHA-256, unchanged before and after the run, is
`1039dc66cd6f75573dcf24c6e91efe7bf86bc94a124f1c87f5c3edd9aef28662`.

The run spanned **19:00:30.911-19:42:25.396 UTC**, or
**2514.4927782 s (41m 54.5s)** including harness startup and report generation.
The jobs' recorded wall times sum to **2503.503176 s (41m 43.5s)**.
These are observed timings from one run, not a controlled performance study.
A separate Elmer job finished before timing began; other solves were paused.
No competing field, mesh or build workload was detected in 47 monitoring samples.
Desktop/background processes and free disk observations are recorded in
[environment.json](environment.json).

## Evidence and verification

[Full 64-page PDF](coilem_benchmark_report.pdf),
[Markdown gate report](benchmark_report.md), [HTML plots](coilem_benchmark_report.html),
[complete measurements](benchmark_summary.json), [results CSV](benchmark_results.csv),
[fixture configurations](fixtures/), [run manifest](run_manifest.json),
[console output](console.txt), [original self-check record](self-check-windows-x86_64.json).

The original hand-back is evidence commit
[`45b1935b42afef88f436ec260094b39e20deb022`](https://github.com/coilemdev/coilem/commit/45b1935b42afef88f436ec260094b39e20deb022)
and [the PR #119 comment](https://github.com/coilemdev/coilem/pull/119#issuecomment-6254311048).
The console file is preserved as `console.txt` for the repository publication
policy. Local output and checkout roots were replaced with `<native-out>` and
`<checkout>`; measurements and verdicts were preserved.

[artifact_manifest.json](artifact_manifest.json) hashes the published copies.
[raw-report-hashes.json](raw-report-hashes.json) preserves the harness's original
report manifest, including the unpublished local PDF's hash. All 71 registered
raw request/result hashes were verified before publication. The original 64-page PDF is now included byte-for-byte, with all 36 relative
fixture links verified. [PDF publication provenance](pdf-publication.json)
records its original hash and read-only rendering review. Raw per-job files
and solver caches remain locally retained and are not included here.

The active [Windows benchmark record](../records/windows-x86_64.json) is rebuilt
from this folder with `tools.build_benchmark_record`, using zero field solves.
Its source names this evidence folder; the original self-check record retains
the source label `report` used before publication. Original measurements are
unchanged in both.
