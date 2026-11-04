# Standard-map timing and Performance view acceptance

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

The existing `ci.yml` workflow also accepts the boolean dispatch input
`performance_acceptance_only`. When true, it runs the five regular bundled
motor examples in separate Windows jobs and uploads their evidence. Routine
push/PR checks keep their existing behavior.

## Measurement and checks

- Standard map: 7 currents × 10 current angles, 70 recorded points and 61
  distinct solves, with 24 rotor positions over half an electrical cycle at
  each point. The zero-current solution supplies all ten zero-current rows.
- Standard accuracy plan: normal (Medium) mesh, two native workers per point.
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
- The export checker compares all torque/power curve samples and efficiency
  cells in the performance CSV against the saved analysis, then checks PDF
  headings and rounded headline values. Screenshots and PDF visual review
  supplement those numeric checks.

`frontend/test-results/performance-evidence/<example>/` contains the request,
compact analysis, environment, map progress, timing, screenshots, downloaded
exports and their checksums. Large field caches and private run directories
are excluded from the uploaded artifact.

These are individual timing observations and platform/UI acceptance checks,
not a release numerical qualification or a general performance guarantee.
The analysis keeps its existing experimental status.
