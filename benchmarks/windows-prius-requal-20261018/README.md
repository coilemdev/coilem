# Windows A/B/C/D regression after the Pyleecan Prius changes

This fresh native collection measured clean **`5b6cb61e65a219ab92a742ac49c37433f53418fb`**.
It checks the shared meshing, excitation and flux-extraction changes used by the
separate [Pyleecan software benchmark](../../docs/benchmarks/pyleecan-prius-v1/README.md).
All **35 supported jobs** completed, with **28 PASS, 1 YELLOW and one planned
UNSUPPORTED legacy ORNL Prius**. Every verdict, gate and recorded numerical value
is **exactly identical** to the [preceding Windows report](../windows-native-20261018-f390b25/README.md).
No numerical limits or registered fixtures were changed.

The [full waveform comparison](full-waveform-comparison.json) also finds exact
equality across all 35 measured lanes: physical summaries and complete torque,
current and back-EMF arrays. It excludes runtime/provenance metadata and timing
fields, with the precise comparison policy retained in that file.

| Phase | Outcomes |
| --- | --- |
| A | 10 PASS |
| B | 11 PASS, 1 YELLOW |
| C | 1 UNSUPPORTED, 4 PASS |
| D | 3 PASS |

## Source and reference identities

The run uses harness **1.5.0**, protocol **1.3.0**, the default **Precise** mesh
and release Magneto2D. Its binary SHA-256 is
`5bc90b1c45b56eb12d472ff21082b8182ef909c8316294e873ddd71b0399de8d`. The source was clean and its identity was
verified before and after every supported worker. No solver override was set.
The [current Windows record](../records/windows-x86_64.json) was rebuilt from
this evidence; all **53** registered physics files match the checkout.
The historical macOS record remains unchanged and is NOT_COMPARABLE with the
changed source until remeasured.

The frozen [FEMM v3 reference](../reference-baselines/ipm-high-output-v3/manifest.json)
remains `95450ffcb909ed20caf514548f741c15611087a3482657c87add4255b308ba63`.
**No FEMM fields were rerun.** The separately published fresh FEMM repeat and
Pyleecan report retain their own identities. This is development regression
evidence; the final v0.4.0 candidate must still be frozen and measured.

## Environment and timings

Windows 11 Home build 26200, AMD Ryzen 7 7700 (8 physical / 16 logical cores),
64 GB RAM, Python **3.12.14**. Full dependency and executable
identities are in the [run manifest](run_manifest.json).

Registered collection span: **2026-10-19T01:31:02.847085+00:00** through **2026-10-19T02:13:05.810805+00:00**,
or **2522.964 s (42m 3.0s)**. This span
uses the harness timestamps; report/PDF generation follows completion of the
registered jobs. The previous run's 41m54.5s included report generation, so
these differently bounded numbers are not a controlled speed comparison.

No agent test, build or separate solve ran during collection. Process ancestry
checks observed no competing field solver in **10** periodic samples.
[Environment and samples](environment.json) retain the checks and their limits,
including one initial inconclusive ownership classification. Background desktop
activity and sampling gaps prevent a controlled performance claim.

## Complete artifacts and integrity

- [Original 64-page PDF](coilem_benchmark_report.pdf), [HTML plots](coilem_benchmark_report.html),
  [gate report](benchmark_report.md), [complete numerical JSON](benchmark_summary.json),
  [CSV](benchmark_results.csv), and [all 36 fixture inputs](fixtures/).
- [Exact comparison and separate tolerance check](comparison-to-prior.json),
  [rebuilt self-check record](self-check-windows-x86_64.json), [console](console.txt),
  [publication provenance](publication.json), and [PDF review](pdf-publication.json).
- [Original report hashes](raw-report-hashes.json) and
  [complete published-file hashes](artifact_manifest.json).

All **71** registered raw request/result hashes and every worker's before/after
identity were verified before publication. The PDF is copied **byte-for-byte**;
all 64 pages and 36 relative fixture links were reviewed. Text copies replace
only local checkout/output paths and normalize line endings. Numerical values,
waveforms and outcomes are retained. Raw per-job files and solver caches remain
locally retained. Rebuilding the record and publishing this folder ran zero fields.

The V-shape baseline's YELLOW result, the legacy unsupported case, frozen
reference REVIEW_REQUIRED status and all scientific limitations remain visible.
Fast mesh remains experimental. The Pyleecan cases retain separate software
model IDs and do not resolve ORNL hardware accuracy or qualify the final release.

Reproduce from a clean source and release solver build:

```sh
python -m tools.run_benchmarks --phases A B C D --out-dir ../benchmark-output/windows-prius-requal --pdf
```
