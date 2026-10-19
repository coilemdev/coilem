# Targeted Windows nonlinear convergence measurements

This is the original before/after measurement record. The [review follow-up](NONLINEAR_CONVERGENCE_REVIEW_WINDOWS.md)
adds exact registered benchmark checks, High accuracy/Custom coverage, iteration-cap diagnostics,
the Newton residual floor, and the latest validation results.

These Standard/normal-mesh diagnostics are not a qualification rerun. All cases use 48 loaded and 48 no-load positions over one electrical cycle. Back-EMF is the phase-to-neutral RMS fundamental. Iteration max/median exclude reused positions.

## Original stopping policy and tighter diagnostic

The unchanged v0.4.0 source is `cf4b68c0c1f29a2aa634edd52c4d796ca9018489`. The tighter diagnostic explicitly sets the generic tolerance to `1e-5`, Newton's RHS-scaled tolerance to `8e-6`, and the cap to 400 per stage. It does not change geometry, current, speed, mesh settings, or grids. Exploratory timing samples partly overlapped and are not the performance comparison. The initial SPM used Python 3.11.0b4; all other runs used Python 3.12.14.

| Case / method | Policy | Iterations max / median | Wall s | Mean torque N m | Back-EMF V |
| --- | --- | ---: | ---: | ---: | ---: |
| spm-8p12s / picard | v0.4.0 default | 54 / 54 | 23.91 | 10.669117 | 31.195204 |
| spm-8p12s / picard | Tighter diagnostic | 138 / 129 | 99.78 | 10.670719 | 31.193599 |
| ipm-10p-vshape / picard | v0.4.0 default | 64 / 63 | 29.39 | 2.762415 | 8.590419 |
| ipm-10p-vshape / picard | Tighter diagnostic | 190 / 173 | 103.09 | 2.756356 | 8.571668 |
| ipm-14p-flat / picard | v0.4.0 default | 90 / 80.5 | 48.95 | 46.515836 | 39.043484 |
| ipm-14p-flat / picard | Tighter diagnostic | 181 / 167 | 84.80 | 46.519429 | 39.042087 |
| wide-angle-original / newton | v0.4.0 default | 18 / 15 | 346.64 | 0.153963 | 0.130619 |
| wide-angle-original / newton | Tighter diagnostic | 24 / 22 | 274.16 | 0.171112 | 0.229245 |

## Reporting-only verification and stopping fix

The implementation starts from current main `2ede4e802f30af45b57e3cc2bb0d9063e544a3bf`, as requested after the initial baseline. Its only change since v0.4.0 is the process-pool shutdown fix. All 11 checked torque, flux-linkage and back-EMF waveform arrays are bit-for-bit equal between v0.4.0 and the reporting-only solver for every case.

These are serial single-pass before/after samples on Windows with Python 3.12.14. They measure the same public backend solve path and requests. The stopping fix was measured at `13a32cac7100fce4a57f1223eab6074687628ab6`; the later physics-identity change adds tolerance-default hash coverage and does not change numerical execution. Exact requests, runtime overrides, source/binary identities, position grids, iterations and convergence records are in [the data file](NONLINEAR_CONVERGENCE_WINDOWS.json).

| Case / method | Policy | Iterations max / median | Wall s | Mean torque N m | Back-EMF V |
| --- | --- | ---: | ---: | ---: | ---: |
| spm-8p12s / picard | Before | 54 / 54 | 23.80 | 10.669117 | 31.195204 |
| spm-8p12s / picard | After | 83 / 83 | 21.77 | 10.670707 | 31.193576 |
| ipm-10p-vshape / picard | Before | 64 / 63 | 29.06 | 2.762415 | 8.590419 |
| ipm-10p-vshape / picard | After | 117 / 113.5 | 33.28 | 2.756363 | 8.571685 |
| ipm-14p-flat / picard | Before | 90 / 80.5 | 48.36 | 46.515836 | 39.043484 |
| ipm-14p-flat / picard | After | 125 / 121 | 51.70 | 46.519324 | 39.042080 |
| wide-angle-original / newton | Before | 18 / 15 | 271.62 | 0.153963 | 0.130619 |
| wide-angle-original / newton | After | 25 / 23 | 270.86 | 0.171112 | 0.228964 |

| Case | Wall-time change | Torque change | Back-EMF change |
| --- | ---: | ---: | ---: |
| spm-8p12s | -8.5% | +0.015% | -0.005% |
| ipm-10p-vshape | +14.5% | -0.219% | -0.218% |
| ipm-14p-flat | +6.9% | +0.007% | -0.004% |
| wide-angle-original | -0.3% | +11.138% | +75.292% |

A slowdown above about 20% needs an owner decision. Options include qualifying adaptive Picard relaxation, evaluating a phase-flux/energy stability criterion for strong-output designs, or qualifying Newton for more presets. Keep the unrelaxed or physical stopping test when measuring those options; do not loosen tolerances solely to recover time.

The original wide-angle fixture has unusually weak winding flux; its small voltage is not a target for the bundled examples. The deep-apex reference limitation remains as documented in [the diagnosis](IPM_BENCHMARK_DIAGNOSIS.md). No solver settings were tuned to FEMM, and no full release matrix was run.

Open owner decisions: accept or revise the candidate per-preset tolerances in [the convergence contract](NONLINEAR_CONVERGENCE.md), and accept the measured runtime cost or request a separately qualified acceleration. Results display and dedicated PDF/CSV presentation remain the documented handoff.

## Validation and limits

- Rust: **263 passed**, using the requested locked Cargo test command, including
  serialization and stopping-policy regression tests.
- Full `python -m pytest -q tests`: **1,212 passed, 3 skipped, 16 expected
  qualification failures**, with no unexpected failures. This completed on
  Python 3.13.9 with a fresh environment using `requirements.lock`. The skips
  cover SIGPIPE, Windows whole-message pipe behavior, and POSIX process-group
  cleanup. The exact expected failures and skip reasons are in the data file.
- Focused backend convergence, preset and environment checks: **27 passed**.
  The earlier supplemental selection had **845 passed, 1 skipped, 16 expected
  failures**; the complete run above supersedes its restricted coverage.
- Frontend: fresh `npm ci` and `npm run build` **passed**, including public
  boundary/UI checks, typechecking and bundle audit, on Node 24.19.0 and npm
  11.17.0 using the committed lockfile.

Use a short temporary root on Windows. A first locked full run using the long
workspace temporary path hit a 260-character filename limit in an export test
and one access-denied temporary-file replacement in a benchmark artifact test.
Both affected files then passed all 68 tests with the shorter temporary root;
the entire suite was rerun there with the results above. Application and test
sources were not changed to bypass those filesystem failures.

The **16 expected failures** are:

- 10 instances of
  `tests/test_qualification.py::test_report_measured_the_current_physics_sources`:
  the five changed Python physics sources (including the newly guarded
  tolerance-defaults file) and five changed Rust solve sources.
- Five physics-identity checks in `tests/test_benchmark_command.py`, including
  the two platform record-rebuild checks, historical macOS guard, checkout guard
  and installed-package stamped-hash check.
- `tests/test_pyleecan_reference_fixture.py::test_published_app_evidence_keeps_complete_actual_grids_and_its_measured_sources`.

Their exact node IDs are in the data file. Archived evidence and qualification
hashes remain unchanged. Clean `git archive` exports are checked separately
with `python tools/verify_snapshot.py --publication`; publication contents do
not establish numerical qualification. The full release matrix remains deferred
to the 0.5.0 freeze.
