# coilEM v0.4.0 release plan

Original planning baseline: October 18, 2026, public main
`0417736249ae2926e05612ac58926cdc76cc8868`. The development evidence below
adds the subsequent Pyleecan implementation and its regression run. Preparation
on October 19 starts from merged main `3b67492be295cf2a04645d2de17b6fbda55ef37a`.
The source application is now 0.4.0 and Magneto2D remains 0.3.3.
It does not mark v0.4.0 as released or replace measured source identities.

The [benchmark evidence report](../benchmarks/v0.4.0/README.md) combines the
completed Windows native requalifications, fresh FEMM repeat and Pyleecan
software benchmark. The
[0.4.0 milestone](https://github.com/coilemdev/coilem/milestone/2) has
only #126 still open, for the final-candidate Prius collection. Passing the
existing development A/B/C/D matrix does not complete the final release gates.

## Current evidence

| Item | Recorded result | Remaining work |
| --- | --- | --- |
| Prius-branch Windows A/B/C/D regression | [35 supported jobs / 28 PASS / 1 YELLOW](../benchmarks/windows-prius-requal-20261018/README.md) at `5b6cb61`; every recorded gate, verdict and value equals the preceding Windows report | Development evidence; repeat on the frozen final candidate |
| Earlier Windows native A/B/C/D baseline, Precise mesh | 35 supported jobs complete at `f390b25`; 28 PASS, 1 YELLOW, planned unsupported Prius; 41m54.5s | Run the final release candidate and retain its own identity |
| Fresh FEMM 4.2 repeat | 29/29 physical payloads and flux/source audits exactly match both the October 16 repeat and frozen v3; 1h49m05s, 1.65% faster | Keep reference v3/protocol 1.3.0; new physical requests need separate matched reference evidence |
| Pyleecan Prius development evidence | [17 jobs / 568 fields / 10 software checks pass](benchmarks/pyleecan-prius-v1/app-results.md) at `d993d76`; both fixed workspace cases and full curve/controls retained | Repeat on the frozen final candidate; #126 remains open for that gate |
| UI integration CI | [All eight checks passed](https://github.com/coilemdev/coilem/actions/runs/39201577202) at `5ae948b`, merged as `3b67492` with the identical tree | Require success again on the versioned final candidate |
| Wheel rehearsals | [Successful earlier PR rehearsal](https://github.com/coilemdev/coilem/actions/runs/39049745989) | Rehearse the exact final candidate on all four wheel targets |
| macOS numerical evidence | Historical record at `738d951`; the current source guard reports NOT_COMPARABLE for the changed mesh and reference-dispatch sources | Collect and review a current full native record before claiming current macOS numerical parity |
| Python 3.15 numerical evidence | Different locked NumPy/Pydantic pins; CI coverage exists, a full benchmark is not recorded | Measure it for any numerical claim, or explicitly retain the coverage limitation |

The existing V-shape baseline's YELLOW result and all reference scientific
limitations remain visible. Fast mesh remains experimental; the Windows run
measured Precise. FEMM agreement is not a hardware-validation claim.

## 1. Resolve release scope before freezing the candidate

- [x] Select the 0.4.0 feature scope: merged stack, exact Prius examples, Layout
  and Phases. Hardware #69/#82 moves to 0.5.0; #126 remains open for final
  candidate measurement rather than additional feature work.
- [ ] [#126: Pyleecan Prius software-model/workflow reproduction](https://github.com/coilemdev/coilem/issues/126):
  ship the pinned example with its actual geometry, winding, materials,
  temperature, current and angle conventions; verify design-file save/reopen
  and normal Design/Solve execution. Publish the no-load 20 C case and loaded
  60 C case, refinement controls, full tested curves, matching-input FEMM
  comparisons, discrepancies and reproducible source/runtime identities.
  The [fixed examples and complete development report](benchmarks/pyleecan-prius-v1/README.md)
  now supply this foundation, including Design/Solve and save/reopen checks.
  Keep this item open for the final-candidate rerun in section 3.
- [x] Defer [#69: ORNL hardware correlation](https://github.com/coilemdev/coilem/issues/69)
  and [#82: measured Prius benchmark](https://github.com/coilemdev/coilem/issues/82)
  to **v0.5.0**, following the release scope decision. They are not v0.4.0
  blockers. Preserve the existing hardware discrepancies and legacy unsupported
  row; the Pyleecan software reference does not establish hardware accuracy.
- [x] Review the existing Honda Accord evidence. The
  [real-winding comparison](hardware-validation/honda-accord-2005/real-winding-comparison/README.md)
  retains `738d951`/`50fe405`, the blind N35 assumption and simplified rotor.
  Mean back-EMF error is +0.6%; mean peak-torque error is −3.6%, with residual
  ranges retained in the report. There is no hardware pass/fail. A fitted
  variant was planned but is not claimed as completed evidence.
- [x] Include [Layout #133](https://github.com/coilemdev/coilem/pull/133) and
  [Phases #134](https://github.com/coilemdev/coilem/pull/134), now merged on main.
  Their combined production build, 202 focused Python tests and both exact-Prius
  browser workflows pass. Actual slot coordinates, Pyleecan d-axis Phi0 currents,
  zero-current behavior and shifted-frame wheel zoom have regression coverage.
- [x] Keep license-dependent CREATOR [#90](https://github.com/coilemdev/coilem/issues/90)
  and named presets [#127](https://github.com/coilemdev/coilem/issues/127) outside
  the current 0.4.0 milestone. Neither is a prerequisite for this candidate.

The merged stack supplies the winding/flux-linkage corrections, benchmark
execution and reproduction tools, mesh-build controls and release hardening.
Their presence does not resolve an open issue's remaining acceptance criteria.

## 2. Prepare the version and release documentation

- [x] Bump `backend/__init__.py`, `frontend/package.json`, both root versions in
  `frontend/package-lock.json`, and the design-file writer's application version
  to **0.4.0** together. Bundled example creation versions and old reports retain
  their original identities.
- [x] Keep Magneto2D at **0.3.3**, with the existing locked solver sources.
- [x] Rewrite `RELEASE_NOTES.md` around the selected behavior, measured baseline,
  installation, saved-file migration and known limitations. Earlier release
  notes remain in Git history.
- [x] Align README, `PUBLICATION_STATUS.md`, `docs/VALIDATION.md`, evidence indexes
  and the snapshot manifest. Preserve measured qualification-record identities,
  the YELLOW/unsupported rows and platform/runtime gaps.
- [x] Check version/tag agreement with
  `python -m tools.release.version --tag v0.4.0`: prints `0.4.0`.

Version preparation does not complete final qualification. The candidate SHA
is recorded only after preparation checks and integration, before field collection.

## 3. Freeze and measure the final candidate

- [ ] Freeze the code, version, dependency locks, numerical requests, material
  definitions, angle/current conventions, gates and release documentation at
  one clean candidate commit. Record that commit before collection.
- [ ] Run the full registered native A/B/C/D suite on Windows with the release
  solver and Precise mesh, using the frozen reference bundle. Preserve all
  35 supported jobs, the complete 30-row selection and every gate outcome.
- [ ] Collect a current full macOS native record and review source/runtime
  compatibility. Identify any Linux or Python-runtime numerical coverage that
  is still unmeasured rather than treating hosted smoke tests as full parity.
- [ ] Finish the release-candidate Prius/reference/refinement runs required by
  #126. Hardware correlation in #69/#82 is deferred to v0.5.0. Give each physical model and reference
  stable identifiers; retain the existing v3 suite/reference history.
- [ ] Publish complete tables, waveforms, residuals, mesh and angular controls,
  fixture inputs, source/binary/dependency identities, hashes, timing context,
  reproduction commands and limitations. Include HTML, numerical JSON/CSV
  and the full plot PDF with working fixture links.
- [ ] Review every change from the saved record; do not relax numerical limits
  or relabel an experimental result to obtain a green release report.

Standard native reproduction, after the documented environment and release
solver build:

```sh
python -m tools.run_benchmarks --phases A B C D --out-dir ../benchmark-output/v0.4.0-candidate --pdf
```

For macOS, dispatch [release-benchmarks.yml](../.github/workflows/release-benchmarks.yml)
at the same frozen candidate ref, selecting `macos-15` and Python `3.12`.
It runs the full A/B/C/D selection with the release Rust toolchain and locked
runtime, and retains reports, fixtures and registered measurements for 90 days.
Download and review those artifacts before they expire; a successful dispatch
or build alone is not a completed numerical record. Windows/Linux and Python
3.15 are explicit alternative selections, not implied parity claims.

The separate complete Prius collection uses the same clean candidate:

```sh
python -m tools.benchmark_prius --out ../benchmark-output/v0.4.0-prius --curve --refinement
python -m tools.report_prius_benchmark ../benchmark-output/v0.4.0-prius --out ../benchmark-output/v0.4.0-prius-report
```

Keep the freeze identity, workflow/run links, benchmark output hashes and
acceptance decisions in the external release evidence. Do not modify the
measured source merely to insert its own commit hash or generated reports.

The current fresh FEMM repeat establishes unchanged reference results; it
does not rerun the native fields on a future release commit. Keep the final
candidate unchanged through tagging. Reports produced after the freeze can
be retained as release assets so committing evidence does not create a
self-referential measured-commit claim. Any change to the candidate requires
rechecking its identity and the affected release gates.

## 4. Validate the packaged release

- [ ] Pass snapshot/publication checks, Python and Rust tests, lint, dependency
  audits, the frontend build and the public-browser workflows on the final
  candidate. Preserve the workflow links and exact tested commits.
- [ ] Run the release-wheel workflow with `publish=none` at that candidate.
  All four targets (Windows x64, macOS arm64/x86_64, Linux x86_64), supported
  Python versions 3.11-3.15 and the bare-Linux acceptance job must pass.
- [ ] Record installed-wheel walkthroughs: install/launch, example load,
  geometry/winding settings, sine and six-step solves, cancellation, save and
  reopen, compare, PDF/CSV/replay exports, benchmark self-check, and the new
  Prius workflow if it is in the release scope. Verify build/version identity.
- [ ] Check existing saved designs/runs remain readable; document any behavior
  change caused by corrected winding or current conventions.
- [ ] If selected, complete a TestPyPI rehearsal and its install acceptance.
  Keep that development upload distinct from the final package version.

The repository's [wheel workflow](../.github/workflows/release-wheels.yml)
already implements build, acceptance, rehearsal and protected publication.
Ordinary CI success is not a substitute for its exact-candidate checks.

## 5. Release decision and publication

- [ ] Owner accepts the final scope, benchmark discrepancies, supported
  platform/runtime claims, installation walkthrough and release notes.
- [ ] Confirm the clean, measured, accepted commit and package version; create
  the matching `v0.4.0` tag only after that decision.
- [ ] Let the protected PyPI workflow complete, then verify its published-wheel
  installation checks and the draft GitHub release's notes, wheels, hashes
  and complete benchmark assets before making the release public.
- [ ] Run a post-publication install check and retain the final evidence links.

The feature scope and version preparation are complete. The release decision
remains **pending** final-candidate measurements, package acceptance and owner
review. Preserve the existing Windows/FEMM/Prius runs as baseline evidence.
