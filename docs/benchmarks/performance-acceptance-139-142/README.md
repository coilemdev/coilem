# Standard-map timing and Performance view acceptance

## Recorded results (2026-11-04)

Measured application source: `064993b52af6a7aaab99d5826eb3c9b2aba9d4a7`.
The timed source tree was clean. Later UI/export rechecks use `42cb14b` on
macOS and `3ce46ed` on Windows, with the exact measured maps. Their before/after
map hashes match and the browser observed no new grid solves. Only
rehearsal/workflow/documentation files changed between those sources.

| Platform and example | Map phase | Request through save | Point status | UI and exports |
| --- | ---: | ---: | --- | --- |
| macOS, starter SPM 8p/12s | 1149.0 s (19m 9s) | 1155.3 s | 70/70 successful | Passed; 5246 CSV comparisons; 4 PDF pages |
| Windows, starter SPM 8p/12s | 2667.8 s (44m 28s) | 2684.9 s | 70/70 successful | Passed; 5246 CSV comparisons; 4 PDF pages |
| Windows, SPM 6p/36s | 2482.0 s (41m 22s) | 2504.9 s | 70/70 successful | Passed; 3263 CSV comparisons; 4 PDF pages |
| Windows, IPM 10p V-shape | 3650.4 s (60m 50s) | 3670.6 s | 70/70 successful | Passed; 4697 CSV comparisons; 4 PDF pages |
| Windows, IPM 14p flat buried | 3743.2 s (62m 23s) | 3767.3 s | 70/70 successful | Passed; 4208 CSV comparisons; 5 PDF pages |
| Windows, SPM 24p | 4431.7 s (73m 52s) | 4457.5 s | 70/70 successful | Passed; 5396 CSV comparisons; 4 PDF pages |

Mac hardware: Apple M4, 10 logical CPUs, 16 GiB RAM; Darwin 24.6.0/arm64,
Python 3.12.13, Node 25.2.1, Chromium 148.0.7778.96. This is one observation
on an interactive desktop with the explicit worker budget below, rather than
a statistical comparison or an automatic-worker estimate.

Windows runners expose four logical CPUs and about 16 GiB RAM, OS release
10.0.26100/x64, Python 3.11.9, Node 24.22.2 and the same Chromium version.
Starter SPM, SPM 24p and flat IPM ran on AMD EPYC 7763 hosts; distributed SPM and
V-shape IPM ran on Intel Xeon Platinum 8573C hosts. Each environment receipt
records its own CPU and native binary hash; these are different machines,
not a controlled macOS-versus-Windows speed comparison.

The archived JSON retains the request, full map/derived analysis, machine
details, all 62 progress events, timings, browser assertions and export hashes.
The PDF and torque/efficiency screenshot are retained alongside it. The CSV
checker verified all curve and efficiency samples, and all four PDF pages were
rendered and visually inspected.

Two earlier local attempts encountered low disk space and are excluded: a
starter SPM map had one unsolved point, and the flat IPM attempt was stopped
after the same early missing-point pattern was found. The successful SPM run completed without gaps. Its archived environment
receipt predates the free-disk field; the exact starting free space is not
retained and cannot be verified from this bundle.

Windows native measurements came from [Actions run 41855229814](https://github.com/coilemdev/coilem/actions/runs/41855229814).
The initial browser tests passed their map, curve, efficiency-cell and Ld/Lq
assertions, then failed on an incorrect accessible name for the Export button
in the harness. The button is named `Export`; its arrow is hidden from assistive
technology. Corrected UI/export rechecks use the exact completed native maps.
All five Windows Standard maps completed with 70 successful points, and all
five corrected Windows UI/export rechecks passed. Together with macOS, the
export checker performed 28056 CSV value comparisons. Every retained PDF was
rendered and all 25 pages visually inspected. This completes the remaining
recorded acceptance for #139 and #142; it does not qualify the physics for a
release or replace the independent benchmark gates.

During collection, GitHub reported delayed rechecks and job states during its
[Actions incident](https://www.githubstatus.com/incidents/xr3myzj7ms51), reported
from 16:05 UTC. The successful rechecks are
[41866681070](https://github.com/coilemdev/coilem/actions/runs/41866681070)
(starter SPM, distributed SPM and V-shape IPM) and
[41867162698](https://github.com/coilemdev/coilem/actions/runs/41867162698)
(flat IPM). The successful SPM 24p recheck is
[41869040523](https://github.com/coilemdev/coilem/actions/runs/41869040523).

This opt-in rehearsal records the remaining acceptance evidence for #139 and
#142. It exercises the built production UI with Chromium, the local API, Gmsh
and the bundled Magneto2D binary. It does not intercept solve responses.

## Reproduce

Install the documented Python environment and Rust toolchain, then run from
the repository root:

```sh
cargo build --release --locked --manifest-path solvers/magneto2d/Cargo.toml
cd frontend
npm ci
npm run build
npx playwright install chromium
COILEM_ACCEPTANCE_CASES=spm-8p12s,ipm-14p-flat npx playwright test --config playwright.performance.config.ts
cd ..
python -m tools.check_performance_acceptance frontend/test-results/performance-evidence/spm-8p12s frontend/test-results/performance-evidence/ipm-14p-flat
```

On PowerShell set `$env:COILEM_ACCEPTANCE_CASES` before running Playwright.
`COILEM_TEST_PYTHON` may name the Python executable. Commit tracked changes
before measuring; the harness rejects a dirty tracked source tree.
For a setup-only preflight, set `COILEM_ACCEPTANCE_SETUP_ONLY=1`; it runs no
solve and produces no passing browser/export acceptance record.
Cold rehearsals require at least 3.5 GiB free, or 6 GiB for the large flat IPM,
before starting. The native sweep's temporary field files can exceed the
between-solve cache limit.

The existing `ci.yml` workflow also accepts the boolean dispatch input
`performance_acceptance_only`. When true, it runs the five regular bundled
motor examples in separate Windows jobs and uploads their evidence. Routine
push/PR checks keep their existing behavior.

To recheck charts and downloads after a harness correction, set
`COILEM_ACCEPTANCE_RECHECK_DIR` to a prior evidence directory. Only a complete
70-point native map is accepted. It is loaded through the app's normal map
store; the returned map must equal it and the browser must observe no new
grid solves. The original environment, request, progress and timing files are
copied unchanged, with a separate recheck source identity and map checksum.
Rechecks do not count as fresh timing samples. In Windows CI the optional
`performance_recheck_run` dispatch input downloads the per-example artifacts
of that cold run and performs these UI/export checks in new Windows jobs.
The hardened harness checks map identity before submission and checks the UI's
actual request before forwarding it. A mismatch stops before a solve starts.
After physics changes, collect a new cold map at the frozen candidate; use the
pinned recovery procedure below to inspect historical exports without solving.

## Measurement and checks

- Standard map: 7 currents × 10 current angles, 70 recorded points and 61
  distinct solves, with 24 rotor positions over half an electrical cycle at
  each point. The zero-current solution supplies all ten zero-current rows.
- Standard accuracy plan: normal (Medium) mesh. The server environment pins one
  Gmsh producer, two concurrent angle solves (one native worker each), and one
  field-preview worker; no design-file override of the worker count is needed.
  Geometry, materials, winding and operating-point values come from the
  bundled designs. Map drive limits use the UI defaults and MTPA control.
- A fresh isolated user-data root starts each invocation. The harness confirms
  that each design's map scope was absent before solving; no warm map reuse.
- Map-phase duration is the difference between the server's first and last
  `torque_speed_map` progress timestamps (0.1 s resolution). Browser request
  wall time also includes the initial field preview, packaging and saving.
- Browser checks require 70 successful points, both torque and power curves,
  nonempty efficiency cells, matching headline values, experimental status,
  apparent Ld/Lq rows and four actual downloads: PDF, performance CSV, id/iq
  CSV and raw map CSV. Browser errors fail the check.
- The hardened export checker compares all performance CSV rows and units,
  raw map cells, and interpolated id/iq table cells, then checks PDF headings
  and rounded headline values. It also verifies receipt hashes, grid coverage,
  progress counts, request hashes, and recheck map/no-regrid claims. Its report
  adapter uses the saved curves/cells and shared auxiliary interpolation; this
  is export validation, not an independent physics oracle. Screenshots and PDF visual review
  supplement those numeric checks.

`frontend/test-results/performance-evidence/<example>/` contains the request,
compact analysis, environment, map progress, timing, screenshots, downloaded
exports and their checksums. Large field caches and private run directories
are excluded from the uploaded artifact.

These are individual timing observations and platform/UI acceptance checks,
not a release numerical qualification or a general performance guarantee.
The analysis keeps its existing experimental status.

The acceptance work also corrects the performance CSV's swapped `unit`/`value`
header labels. Its data columns retain their existing order and precision.
A regression reads the export by column name, the way external CSV consumers
do, and checks both units and numeric samples.
The loss-report PDF assertion changed separately in #188 to follow the
three-decimal cap (`0.047 mH`, instead of the former four-decimal display).


## Tooling hardening after the recorded measurements

These changes do not update the timing table, numerical gates or historical
receipts. Routine CI now tests corrupted exports and checks the opt-in
Playwright TypeScript. Manual cold and recheck dispatches have distinct
concurrency groups, so neither cancels regular CI or another acceptance run.
The test budget is 120 minutes (110 minutes for the response), inside a
180-minute hosted job budget for install/build and artifact upload headroom.

Each attempt writes its phase before waiting for the solve. A reporter writes
status, elapsed time, errors and a 30-second heartbeat, including failed and
timed-out attempts. Abrupt runner termination can prevent finalization; the
last heartbeat and request-start receipt remain diagnostics, not a passing
timing result. Artifacts include these receipts. Screenshots expand clipping
containers only during capture so the whole panel, including axes, is visible.

Automatically created runtimes are removed after a successful browser run,
once its server stops; exported evidence stays in `test-results`. Failed runs
retain their runtimes for diagnosis. A supplied `COILEM_ACCEPTANCE_RUNTIME`
is never removed automatically. Evidence directories must be new for each
attempt: move previous evidence elsewhere before rerunning the same example,
rather than combining stale downloads with a new attempt.

The checker runs identically under `python -O`. New evidence captures the
actual report request and recheck progress. Existing `export-check.json`
receipts are compared, never overwritten. Missing hashed files are errors;
the checker needs the complete artifact bundle to verify every original file.

## Recover omitted CSVs with zero solves

The repository retains analysis JSON, PDFs, one screenshot per case, and the
original receipts. Three CSVs and the setup/power/map-details screenshots were
omitted from Git. Hosted artifacts expire; the CSVs remain reproducible from
the saved maps at each **export/recheck** source, without rerunning Gmsh or
Magneto2D. Do not regenerate at the timed source or current HEAD and restamp
its hashes.

Read the full `source_commit` from the case's `recheck-environment.json`.
Create a separate clean worktree at that exact SHA and install its locked
frontend dependencies (Node 24; use the documented Python environment):

```sh
git worktree add --detach ../coilem-export-pin <full-source-commit>
npm ci --prefix ../coilem-export-pin/frontend
python -m tools.regenerate_performance_csvs --source ../coilem-export-pin \
  --evidence docs/benchmarks/performance-acceptance-139-142/windows/spm-8p12s \
  --output /tmp/coilem-recovered-spm-8p12s
```

Run the command from this checkout, with a fresh output path outside the
archive. Repeat with the source SHA and path of each case. It copies the
retained files unchanged, runs the pinned backend CSV writers and frontend
`mapCsv`, then compares **all three CSV byte counts and SHA-256 hashes** with
the original receipt. Any difference fails and retains the output for diagnosis.
No native executable is required. This recovers CSV bytes only; omitted PNGs
cannot be reconstructed with their original hashes. Full artifact validation
requires those original files; newly captured images are separate evidence.

The recovery command was exercised against all six archived cases during
tooling hardening: all 18 CSV byte counts and SHA-256 hashes matched. That
check recomputes derived report tables at the pinned export source and runs
zero native field solves; it does not add a cold timing sample.
