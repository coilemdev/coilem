# A/B/C/D benchmark protocol 1.0.0

Run from a Coilem source checkout with the normal Python dependencies and Rust toolchain installed:

```sh
python -m tools.run_benchmarks --phases A B C D --out-dir ../benchmark-output/my-run --pdf
```

This measures the current checkout's public Magneto2D solver and compares it with saved FEMM evidence. It does not install, import, discover or execute a reference solver. The native executable is built on demand. Keep output outside the checkout. A clean Git checkout is required by default; `--allow-dirty` explicitly registers uncommitted source hashes for local experiments.

| Phase | Coverage | Native jobs | Saved FEMM references |
|---|---|---:|---:|
| A – SPM | Ten operating points | 10 | 10 |
| B – IPM | Twelve flat/V-shaped fixtures | 12 | 12 |
| C – Distributed Winding | Four supported fixtures and one policy-rejected Prius fixture | 4 supported, 1 rejected | 4 |
| D – BLDC | Three fixtures, standard/fine/low-current native stages | 9 | 3 |

The public request policy is checked on every run. The rejected Prius fixture is retained and reported as UNSUPPORTED; if support changes later, it can be measured, but lacks a matched reference and cannot receive a parity PASS. Thermal analysis is outside this protocol.

## Running and resuming

```sh
python -m tools.run_benchmarks --version
python -m tools.run_benchmarks --list
python -m tools.run_benchmarks --phases A D --case spm_4p12s_simple__baseline --case spm_4p12s_small --smoke --out-dir ../benchmark-output/smoke
python -m tools.run_benchmarks --phases A B C D --out-dir ../benchmark-output/my-run --resume --pdf
python -m tools.run_benchmarks --phases A B C D --out-dir ../benchmark-output/my-run --report-only --pdf
python -m tools.run_benchmarks --phases D --no-reference --out-dir ../benchmark-output/native-only
```

`--smoke` uses a reduced coarse grid to exercise execution. Its outcome is NON_GATING_SMOKE; it never establishes numerical parity. `--no-reference` retains native BLDC current, golden sequence, convergence and power checks; the five reference-dependent gates are NOT_EVALUATED. Successful native-only cases are NOT_COMPARED, not parity PASS. Exit codes are 0 for completed available checks, 1 for numerical FAIL, and 2 for execution/integrity errors or incomplete evidence. Inspect the recorded outcome alongside the exit code.

Long runs are sequential. Each worker logs to `jobs/<fixture>/<stage>/worker.log`. The run manifest is updated before and after each solve. Completed native jobs are reused on resume only when their requests, outputs, solver binary, actual source hashes, dependency versions, harness/protocol versions and reference bundle agree. Kernel-owned run and worker locks prevent duplicate workers in the same output directory. If an orphaned worker is still running, wait for it to exit and resume again. ERROR jobs are retained; use a new run directory to retry them. Never combine measurements made before and after a source or binary change.

Reports are generated as HTML, Markdown, JSON and CSV, with optional PDF. They include A/B/C/D labels, fixture links, green PASS/red FAIL rows, solid orange native curves, dashed blue references, torque/Back-EMF residuals, BLDC currents, angular convergence and low-current power plots. The report records candidate and reference commits separately and says explicitly that no new reference solves were executed. The run and report artifact manifests retain SHA-256 identities. `--report-only` verifies recorded measurements without rebuilding or solving the current checkout.

Phase summaries appear in A/B/C/D order: green when all fixtures PASS, yellow for mixed results or missing coverage, red when more than 50% of recorded fixtures FAIL. Exactly 50% remains yellow. Individual fixture/gate verdicts and the overall numerical outcome are unchanged by this presentation rule. Reports retain their own copies of every stage's measured input JSON, so links keep pointing to the recorded inputs after the source checkout changes.

On macOS, use the same command with `.venv/bin/python` after installing the normal Python requirements and Rust/Cargo. Benchmark execution does not need Node, the UI server or any FEMM installation. The native executable is built for the Mac and its hash, platform and dependency provenance are recorded separately from the frozen reference commit. The grids, gates and report formats are the same; cross-platform floating-point results and runtimes may differ. A frozen-reference run is new native evidence against retained FEMM data, not a newly regenerated FEMM baseline.

## Reference reuse and replacement

The default data-only bundle is `benchmarks/reference-baselines/main-bad71d9`. It contains 29 reference records extracted from the published snapshot evidence. No reference backend, conversion adapter, executable, Python environment or runtime installation is included. Arrays are already normalized to the audited public clockwise convention; the runner never flips or fits them again.

Reuse depends on the entire registered request: geometry, winding, material selections, current and excitation, speed, angle grid and numerical options. Exact file hashes protect the registered fixtures/protocols/golden vectors, and canonical JSON hashes bind each reference to its public request. The steel curve hash and public magnet Br/permeability must match the bundle. A solver implementation change can use the same bundle. A changed physical request, material contract, reference convention or protocol requires a new registered bundle. A missing reference is shown as NOT_COMPARED, never PASS.

To register new externally produced references, copy the bundle structure to a new directory and supply it with `--reference-bundle`. Each record must contain the case id, phase, canonical public-request SHA-256, normalized result, convention, distinct reference commit and source-record provenance. BLDC records also bind the protocol hash. The bundle manifest lists each record's SHA-256, input hash, protocol version and material contract. Preserve the source evidence used to produce and audit the bundle. Reference production is a separate workflow; this runner does not provide an adapter or automatically regenerate references.

## Numerical policy and versions

Harness **1.0.0** identifies execution, evidence storage and reporting code. Protocol **1.0.0** identifies the registered fixtures, grids, materials, golden commutation vectors and numerical gates. Record both in every run, independently of the application version and measured Git commit. Bump the harness version when its behavior changes; bump the protocol version and register new baseline evidence when changing the measurement contract or gate definitions. Cosmetic report revisions can keep the protocol version.

A/B/C retain the historical torque gates (8% PASS / 15% YELLOW, or 0.01 / 0.02 N m for near-zero references), Back-EMF H1/peak gates (10% / 15%), native WST and exact grid checks. Signed waveform NRMSE/correlation remain diagnostics. The two recorded V-shaped IPM failures remain failures when historical evidence is replayed.

D retains fourteen historical gates per fixture: three native/reference checks, low-current power balance, two angular convergence checks, four current-property checks and four golden sequence checks. Excitation is ideal six-step 120-degree wye with the exact frozen current table. Fine means finer angular sampling on the same normal spatial mesh. The analytical stage is a low-current native field solve with Back-EMF, not a substitute analytical backend. No private numerical tolerance profile is applied. Public request-only defaults, native Gmsh and WST are used.

This protocol does not claim PWM, transient bus dynamics, commutation overlap, current ripple, startup, Hall electronics, delta windings, BLDC IPM or outrunner validation. The tests exercise historical numerical replay, invalid/corrupt evidence rejection, native-only semantics and resume integrity. A smoke solve is additional execution coverage, not a full new signoff benchmark.
