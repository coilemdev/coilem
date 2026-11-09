# Benchmark reports and protocols

[Protocol 1.10.0](abcd-v1.10/README.md) is the default A–D suite from v0.5.7. It is protocol 1.9.0 without `ornl_prius_2004_ipm`, the unsupported ORNL Prius placeholder that never solved and never had a FEMM record. The other 46 cases, their requests, gates and reviewed FEMM records are unchanged. Earlier protocols and their records keep the placeholder and its UNSUPPORTED outcome. v0.5.7 needs a two-platform requalification with the new suite.

[Protocol 1.9.0](abcd-v1.9/README.md) was the default A–D suite for v0.5.6. It is protocol 1.6.0 with Newton, the new default nonlinear method, for the 28 Phase A and D requests that used Picard. Nothing else changes. It reuses the reviewed protocol 1.6.0 FEMM bundle through a hash-bound solve-option bridge, because FEMM never reads coilEM's nonlinear method. v0.5.6 needs a two-platform requalification with this suite.

The [v0.5.1 release qualification](v0.5.1/release-qualification.json) now passes with source-matched Windows/macOS A-D and complete Prius software evidence. The [owner decisions](qualification-a4f9f4dccf2b/owner-decisions.json) accept unchanged reviewed references, one recorded near-zero macOS Prius observation difference and an experimental cogging scope. Measured fields retain `a4f9f4d`; all 64 guarded physics hashes match the versioned release code. Phase E remains unregistered and both YELLOW cases remain disclosed.

The [Windows v0.5.1 integration-merge evidence](windows-v051-20261105-a4f9f4d/README.md) measures `a4f9f4d`: **46 A–D PASS plus the planned unsupported Prius**, and **10 cogging PASS / 2 YELLOW** against the selected fresh FEMM references. All 425 cogging fields, original reference self-check failures and five mesh controls are retained. The optional extra A–D reference repeat was stopped; its artifacts remain preserved. A separately authorized overnight run then completed all 46 fresh FEMM cases: **46 PASS, 336/336 gates PASS and all 46 waveforms exactly matching the reviewed references**. This packet retains its original Windows development identity; accepted cross-platform/Prius qualification and subsequent owner review are recorded separately above.

The [v0.5.0 evidence index](v0.5.0/README.md) now includes the
[physical Windows protocol 1.6 collection](windows-v050-20261102-88aae101/README.md)
at `88aae101`: **52 supported jobs complete, 46 PASS, one planned unsupported
row, and 336/336 gates PASS** against 46 fresh reference records. The exact
[adapter provenance](reference-adapters/windows-femm42-v3-20261102/README.md)
and v0.4.0 comparison are retained. The [subsequent review and candidate qualification](candidate-qualification-20261103/README.md)
accepts the unchanged references for registered parity and registers the Windows
comparison. The published Mac comparison retains its historical pins; fresh
same-candidate Mac evidence remains pending before release. The complete
[Windows Prius candidate audit](candidate-qualification-20261103/prius/README.md)
passes all 10 software checks across 17 jobs and 568 field reports.

The earlier [Windows validation of the v0.5.0 stack](windows-v050-20261029-bb3d8af/README.md) measures `bb3d8af`: all 35 supported native jobs completed, **29 PASS and one planned unsupported row**, with **42/42 BLDC gates** against frozen FEMM v3 references. The separate reconstructed-reference diagnostic has **28 PASS, 1 YELLOW and 1 UNSUPPORTED**. This remains historical evidence with its original reference identity.

The [macOS A/B/C/D at the 0.5.0 stack top](macos-native-20261022-5b7cad8/README.md) is development evidence at `5b7cad8`: 29 PASS and the planned unsupported Prius against the frozen FEMM v3 bundle, compared with the v0.4.0 Windows baseline.

[Protocol 1.6.0](abcd-v1.6/README.md) registers the 0.5.0 reference gates. It is the 1.4.0 matrix plus the shoed example, magnet temperature at 60 °C and 100 °C, and loaded λd/λq points for one SPM and one flat IPM. Its reviewed 46-record bundle is now the runtime default; final Mac candidate qualification remains pending.

[Protocol 1.5.0](abcd-v1.5/README.md) is a separate extension until the 0.5.0
freeze. It adds the app's shoed 8p12s example to the 1.4.0 matrix, which has
no tooth-shoe case, and awaits its FEMM record.

The [v0.4.0 candidate baseline report](v0.4.0/README.md) brings together the full
64-page Windows native PDF and the fresh October 18 FEMM repeat on main:
**29/29 exact physical results and extraction audits**, collected in
**1h49m05s** (1.65% faster than October 16). It retains measured source pins,
the native **28 PASS / 1 YELLOW / planned unsupported Prius** outcomes, and
the [remaining release gates](../docs/RELEASE_0_4_0.md).

The separate [Pyleecan Prius software benchmark](../docs/benchmarks/pyleecan-prius-v1/README.md)
ships two fixed workspace cases and records 17 development jobs / 568 field
reports, with all 10 software checks passing. It retains the complete torque
curve, tutorial waveform, source hashes and refinement controls. This does not
resolve the legacy ORNL hardware fixture or the final v0.4.0 candidate gate.

The [Windows regression after Prius support](windows-prius-requal-20261018/README.md)
is the active development qualification evidence at `5b6cb61`. It measures the
shared mesh, excitation and linkage paths with the Precise default.
All 35 supported jobs completed against the frozen FEMM v3 reference, with
**28 PASS, 1 YELLOW and one planned unsupported Prius**. Every recorded verdict,
gate and numerical value is identical to the preceding `f390b25` report and
the Windows v3 record at `738d951`. The [earlier Precise requalification](windows-native-20261018-f390b25/README.md) remains retained.
The new [Windows record](records/windows-x86_64.json) carries the measured
physics hashes; Fast mesh remains experimental. The historical macOS record
has not been remeasured for this source change.

The [2026-10-16 matched Windows repeat](performance-112/native-20261016/README.md)
includes the full 64-page PDF, HTML, CSV and numerical JSON against the fresh
29-case FEMM 4.2 collection. Native collection took **43m40s**; all 35 native job
summaries and waveforms and every evaluation value match the saved Windows v3
report exactly. Its 28 PASS, 1 YELLOW and planned unsupported Prius outcomes
remain. This repeat preserves the registered reference and qualification policy.

For saved-run timing analysis and bounded external reference collection, see
[benchmark execution performance](../docs/BENCHMARK_PERFORMANCE.md).
The [#112 full FEMM performance run](performance-112/full-suite.md) collected all
29 cases in **1h52m02s**, versus the archived same-host serial span of **9h08m46s**
(**79.58% less time**), with exact physical outputs and extraction audits. This is
one development-host observation; native collection is a separate stage.

The [Windows Magneto2D versus FEMM v3 report](windows-v3-20261015-738d951/README.md) includes the [64-page plot PDF](windows-v3-20261015-738d951/coilem_benchmark_report.pdf), HTML plots, complete results and provenance at measured pin `738d951`. All A/B/C/D data is complete. The post hoc protocol 1.3.0 angle-contract evaluation records **28 PASS, 1 YELLOW, 1 planned unsupported Prius**; historical fixed-axis FAILs remain in the JSON. The [default protocol 1.3.0 commands](abcd-v1.3/README.md) document the correction and unchanged limits. This is scientific-review evidence, not release qualification.

The [PR #100 v3 handoff](pr100-v3-handoff/README.md) pins parallel Magneto2D A/B/C/D collection to `738d951`, matching the Windows FEMM v3 run. It includes native-only commands, hash contracts and a report-only join for the later reference bundle; historical six-step gates and failures remain intact.

The [macOS native collection](macos-native-20261015-738d951/README.md) is that handoff's native half at `738d951`: all 35 supported jobs complete, A/B/C `NOT_COMPARED` until FEMM v3 arrives, and the two tooth-coil six-step fixtures keep their fixed-axis golden-sequence FAILs.

The [Windows full-turn comparison](windows-flux-credit-20261014-1ea9e40/README.md) and [64-page plot PDF](windows-flux-credit-20261014-1ea9e40/coilem_benchmark_report.pdf) measure the #80 fixed pin `1ea9e40` against fresh FEMM v2: 28 PASS, 1 angular-ripple FAIL and one planned unsupported Prius case. Separate refinement/current-control diagnostics retain that original failure.

For the 0.3.x history, see [report v1.7](macos-rc-20261013-1fac3a1/README.md), which measures the
frozen coilEM 0.3.0 commit `1fac3a1` on macOS, and the
[historical protocol 1.1.0 commands](abcd-v1.1/README.md). [Protocol 1.2.0](abcd-v1.2/README.md) remains the separate experimental ORNL Prius extension awaiting its FEMM reference bundle. That historical matrix has
29 PASS and one planned coverage item (numerical status UNSUPPORTED), with
42/42 BLDC gates. Every numerical value matches the previous pin's
[macOS report v1.5](macos-rc-20261013-04f87a5/README.md) exactly. Every verdict and gate status matches the
[historical Windows report v1.4](windows-process-pools-20261012-02fa24b/README.md); values differ only at
the mesh-noise level from per-platform Gmsh meshes. All runs use frozen FEMM data; no
reference solves were executed. The generated PDF is included in each evidence package.

| Record | Role | Matrix / measured candidate |
| --- | --- | --- |
| [macOS report v1.7](macos-rc-20261013-1fac3a1/README.md) | Historical complete run; the frozen 0.3.0 commit after the QA fixes; every numerical value identical to v1.5 across 35 native jobs | Protocol 1.1.0; fresh native fields at `1fac3a1` on macOS, frozen FEMM references |
| [macOS report v1.5](macos-rc-20261013-04f87a5/README.md) | Previous pin `04f87a5`, kept as history; all 30 verdicts and 42 BLDC gates retained across 35 native jobs | Protocol 1.1.0; fresh native fields at `04f87a5` on macOS, frozen FEMM references |
| [Windows report v1.4](windows-process-pools-20261012-02fa24b/README.md) | Historical Windows run; all 30 verdicts and 42 BLDC gates retained, with exact native waveforms across 35 jobs | Protocol 1.1.0; fresh native fields at `02fa24b`, frozen FEMM references |
| [Windows report v1.3](main-20261012-0b463b3-rerun/README.md) | Previous complete run; baseline before later performance changes | Protocol 1.1.0; fresh native fields at `0b463b3`, frozen FEMM references |
| [Baseline v1.2](release-baseline-20261011-v1.2/README.md) | Archived compilation defining the current fixture selection | Protocol 1.1.0; compiled measurements at `45e0a5c` and `af56962` |
| [Higher-output IPM qualification](ipm-high-output-20261011-af56962/README.md) | Source evidence for the two replacement designs | Two cases at `af56962`, with fresh matched FEMM |
| [October 10 macOS rerun](main-20261010-45e0a5c-rerun/README.md) | Archived protocol 1.0.0 run; source evidence for unchanged v1.2 rows | `45e0a5c`; original two FAILs retained |
| [Snapshot report v1.1](main-20261009-bad71d9/README.md) | Archived fresh-reference run and 0.2.0 preview qualification record | `bad71d9`; original two FAILs retained |
| [Protocol 1.0.0](abcd-v1/README.md) | Explicitly selectable historical suite | Original low-output IPM fixtures and saved references |

V1.2 defines the **default benchmark selection**. V1.3 and V1.4 rerun that same
selection at clean candidates on Windows, preserving the inputs, references and
gates. V1.5 reruns it on macOS at the pinned 0.3.0 release candidate, with every
verdict and gate status unchanged. V1.7 reruns it on the same Mac at the frozen 0.3.0
commit after the QA fixes, with every numerical value identical to v1.5. V1.4 records 44.66 minutes of native execution, compared with 176.62 minutes
in V1.3. All physical summary values match exactly except steel RMS accumulation
rounding below 6e-14 T. These runs retain the existing numerical metrics without
broadening application qualification. Later commits require their own measured run.
Concurrent workloads during v1.3 limit direct performance comparisons; see its
[timing record and caveat](main-20261012-0b463b3-rerun/execution-timings.json).

## Why the archive folders remain

The default protocol still reads unchanged input fixtures, BLDC protocols and
golden vectors from `main-20261009-bad71d9`. The compiled v1.2 report links
unchanged measured rows and fixtures in `main-20261010-45e0a5c-rerun`. Tests
also replay the original failed cases. These folders are dependencies and
traceable historical records, not incompatible copies of the current report.
Deleting or moving them would break registered paths, source hashes and links.

The original low-output deep-apex and wide-angle cases are excluded from the
default suite. Reproduce them with the explicit historical suite and bundle
in the [protocol 1.0.0 commands](abcd-v1/README.md).

See the [IPM diagnosis and issue status](../docs/IPM_BENCHMARK_DIAGNOSIS.md)
for the causes found, the replacement results and the remaining solver work.
