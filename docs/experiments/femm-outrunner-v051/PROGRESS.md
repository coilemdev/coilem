# Local workstream checkpoint

Updated 2026-11-05. Branch `codex/femm-outrunner-v051`, worktree `C:/bench/coilem-outrunner-v051-20261105`, exact release base `cf6e8a90e4a33c34dc7ff81886e353b9950961d5`. User authorized independent work and as many useful **local** commits as needed. Do not push, open a PR, merge, publish, change a release, or modify the original dirty checkout.

## Verified

- Architecture review and proposed comparison matrix committed as `a048b52`.
- Three unchanged FEMM files reproduce the published torque magnitudes. Full-model outer-body WST is **-0.05542741539565078 N·m CCW**; full sliding-gap raw torque is **+0.0554301864846747 N·m**. The sign difference is real body selection, not an error to hide with absolute values.
- Exact source conversion to geometry IR: 29 physical regions, a bore hole, 14 magnets, 12 winding regions, both A=0 circles, and the 0.14 mm magnet/back-iron clearance. Analytic coverage = **611.3605277331471 mm²**.
- Native Gmsh mesh policy v2 at 0.05 mm gap size target: **87,530 nodes, 174,508 triangles**, all 29 regions classified by physical surface. The target applies throughout both air clearances and bounds tangential spacing at their interfaces. Mesh area differs from analytic CAD area by the expected P1 boundary chords. Earlier policy v1 meshes are retained separately.
- New translation tests cover source facts, physical coverage, rotor-only geometry/magnet-vector motion, exact ampere-turn conservation, no-load isolation, gauge-invariant linkage, winding reciprocity, field units/orientation, and analytic contour/body-stress torque.
- Magneto2D rebuilt locally from the unchanged v0.5.1 native solver source. Binary SHA-256: `8bdad4dc6c2e97a8a489588ec68a17cd6abfcc475979c7a8c582bbc5cda9998f`.
- Same FEMM mesh field diagnostic converges: Az relative L2 **0.1390%**, phase-linkage functional errors **-0.1318%, +0.0482%, +0.1739%**.
- Native Gmsh/Magneto2D source-point diagnostic with mesh policy v2 converges: linkage functional errors **-0.2747%, +0.3841%, +0.5333%**.
- Body-selected P1 WST on the retained fields: FEMM nodal field **-0.05529899646 N·m**, same-mesh Magneto2D **-0.05518126812 N·m**, latest native Gmsh/Magneto2D **-0.05540927594 N·m**. Latest native differs from FEMM's own original WST by about **0.033%** at this point. This is diagnostic only; convergence and material-law parity remain pending. The separate P1 reprocessing of FEMM's nodal field does not exactly reproduce FEMM's internal postprocessor, so retain both references.
- Focused fixture and existing Halbach mesh regression tests: **24 passed**. Latest native artifacts are in `output/femm-outrunner-review/native-v2-g050/`.

## Material and postprocessing qualifications still needed

The initial explicit material translation uses the source's raw B-H points, piecewise-linear H(B), and in-plane lamination homogenization. FEMM spline-law parity has not been established. Its named material curves are not replaced by catalog approximations.

The plain centroid-filtered Arkkio estimate and individual raw P1 contours vary noticeably with mesh. The body-selected WST integrates the full connected source air domain with weights 1 on the actual rotating interfaces and 0 on actual stationary interfaces. Its auxiliary scalar weighting solve is in the Python adapter; magnetic fields still come solely from Magneto2D. The analytic harmonic-field test checks its sign and units.

FEMM's active-circuit `mo_getcircuitproperties` linkage differs slightly from the area-weighted Az functional (about 1.5849e-7 Wb in B/C at the source current). Preserve both. Do not silently calibrate the winding weights or claim that offset has been explained. No-load tests will distinguish this from PM linkage.

The first overly strict linear/nonlinear solve attempts failed and remain in `same-mesh-v1`/`v2`. The converged experimental settings are linear 1e-8, nonlinear Newton 1e-5, max 300 iterations; achieved residuals were 7.25e-7 (same mesh) and 3.67e-6 (latest native). The raw histories are retained. A tolerance study is still required.

## Files and commands

- Frozen numeric source asset: `backend/experimental/data/femm_lrk_12s14p_v1.json`.
- Fixture physics/answer parsing: `backend/experimental/femm_outrunner.py`.
- Exact curve/face/IR/native mesh path: `backend/experimental/outrunner_geometry.py`.
- Body-aware WST adapter: `backend/experimental/outrunner_stress.py`.
- Comparison CLI: `tools/experimental/compare_femm_outrunner.py`.
- Tests: `tests/test_experimental_outrunner.py`.
- Raw source/reproduction/field artifacts: `output/femm-outrunner-review/` (do not add large output files to commits).

Use the original checkout's existing runtime environment explicitly:

```powershell
& 'C:\Users\14845\Documents\GitHub\coilem-launch\.venv\Scripts\python.exe' -m pytest tests/test_experimental_outrunner.py -q
& 'C:\Users\14845\Documents\GitHub\coilem-launch\.venv\Scripts\python.exe' -m tools.experimental.compare_femm_outrunner --answer output/femm-outrunner-review/published-point/WholeMotor.ans --binary solvers/magneto2d/target/release/magneto2d.exe --mesh native --out output/femm-outrunner-review/native-g025-v1 --gap-size-mm 0.025
```

The default `python` is Conda and has pyFEMM, win32com, NumPy, and Matplotlib. The `.venv` has the application's pinned dependencies and pytest/ruff but no pyFEMM or Matplotlib. The isolated COM producer prototype is `output/femm-outrunner-review/reference_probe.py`; promote it to a reproducible development tool before using it for a sweep. Its COM `DispatchEx` avoids attaching to a user's session. Initial Lua attempt/correction records remain alongside the successful `.ans` files.

The CLI accepts `--reuse-solve-dir` for postprocessing only after checking identical complete field input and binary hash. Use a new output directory for every attempt. Later outputs include `fixture_mesh.json`, raw generic field input/report, binary/report/input hashes, currents, and convergence. Earlier diagnostic field outputs can be repostprocessed after exact-input verification.

## Next independent work

### Active sweep continuation (2026-11-05)

User explicitly requested other operating points, torque and BEMF curves, followed by a `.coilem` example that opens in the UI and reproduces them once cross-angle matching is sound. This extends the original local workstream; preserve both requirements.

- Mesh policy v2 at 0.025 mm completed: 212,890 nodes / 425,228 elements, WST **-0.05531150903 N·m**, linkage errors **-0.2760%, +0.3866%, +0.5386%**. Versus v2 0.05 mm: torque changes about 0.18%, phase linkages change less than 0.006%. Raw evidence: `native-v2-g025`.
- New resumable tools: `produce_femm_outrunner`, `produce_magneto_outrunner`, `analyze_outrunner_sweep`. Shared explicit cases/derivatives: `backend.experimental.outrunner_sweep`. No app dependency changes.
- Initial sweep: 48 unique angles plus an independently solved electrical endpoint, both loaded [0,4,-4] and no-load; six signed-angle/motion controls, five current controls, no-load full-turn closure. This is a staged diagnostic; it does NOT fulfill the preregistered 192/384 grids.
- FEMM uses the full sliding model's OUTER angle (property 11). Reference outer torque = **minus** raw gap integral, fixed before the sweep and checked against physical group-2 rotation. Both results are retained. Off-zero source-mesh WST/sliding differences can exceed source-zero agreement; assess reference discretization uncertainty explicitly.
- Initial native sweep uses independent Gmsh mesh policy v2, gap 0.05 mm, explicit original source-point steel law. Material spline parity remains unverified.
- BEMF: zero-current phase linkage, `e=-omega_mechanical*d(lambda)/d(theta_mechanical)`, positive CCW, 1000 rpm normalization. Full spectral derivative (no harmonic truncation) and fourth-order periodic difference sensitivity. Preserve phase order and report line-to-line separately; do not infer terminal connection/Kv.
- Each completed case has immutable hashed raw fields compressed losslessly, its exact request, convergence and linkage/torque. Resume verifies request/asset/binary identities and evidence hashes. Interrupted directories are renamed and retained. Failed cases require a fresh output directory.
- The desktop app crashed during initial foreground tools. Two completed FEMM cases survived; processes ended. Sweeps were restarted as hidden detached workers so they can outlive the app: FEMM Python PID **25268**, native Python PID **2276** (verify PID/command before control; they may already have exited). FEMM producer owns one DispatchEx COM server and only cleans its exact PID/creation identity and solver children.
- Worker logs: `output/femm-outrunner-review/sweep48-femm.log`, `sweep48-femm-error.log`, `sweep48-native.log`, `sweep48-native-error.log`. Case roots: `sweep48-femm`, `sweep48-native`. Inspect logs/results before starting another worker; never run duplicate writers.
- Resume FEMM with Conda `python -m tools.experimental.produce_femm_outrunner --source-dir output/femm-outrunner-review/source --out output/femm-outrunner-review/sweep48-femm --samples 48`. Resume native with app Python `-m tools.experimental.produce_magneto_outrunner --manifest output/femm-outrunner-review/sweep48-femm/manifest.json --binary solvers/magneto2d/target/release/magneto2d.exe --out output/femm-outrunner-review/sweep48-native --gap-size-mm 0.05`.
- Planned UI uses a distinct frozen-reference design envelope, never fake inner-rotor dimensions. Public `.coilem` parser currently accepts MotorConfig and one Prius reference only; app paths must explicitly recognize the experimental fixture before ordinary parsing. Gate local UI/backend support behind an opt-in flag; preserve ordinary models and expose exact named analyses/save/reopen.

1. Finish and run focused tests/lint; commit the verified frozen fixture, geometry, diagnostics, and this checkpoint locally.
2. Run 0.025/0.0125 mm native mesh controls and a solve-tolerance control. Keep body-selected WST, raw contours, and field/linkage evidence distinct.
3. Promote the FEMM producer; capture +/-outer-motion probes, no-load fields, a current perturbation, and a small initial angle grid. Freeze exact requests and retain failures.
4. Add a strictly typed frozen-fixture request and local experimental solve/report adapter using the shared Magneto2D field core; keep ordinary MotorConfig and release behavior unchanged. Record this implementation choice in the design review.
5. Add a local opt-in coilEM example/view with geometry, actual field, signed winding/current case, and torque/linkage output, then verify save/reopen/export behavior and normal-model regressions.
6. Expand to the preregistered torque/BEMF/cogging grids only after source/current/material/sign checks and initial convergence are sound. Do not describe diagnostic point agreement as full qualification or hardware accuracy.
