# #306: 0.5.9 landing readiness and remaining implementation

**2026-11-16 implementation checkpoint:** the opt-in public stage now
reproduces the internal one-motor native pilot exactly; saved replay, maps,
accounting and exports are integrated. Both solvers' 96/192/384 angular
checks and independent native/FEMM spatial refinement pass. The loaded-SPM
pilot is complete: default-native total 64.563 mW versus finest-FEMM 64.317 mW,
a 0.384% difference. The owner approved the reduced matrix below. See the
[public-path rehearsal](benchmarks/rotor-public-integration-306-20261116.md).
The original readiness notes below describe the earlier checkpoint; they do
not override these newer results or mark the PR ready for release.

Reviewed 2026-11-16 against `release/v0.5.9` at
`f2142dba722140e04f9158a34d6183e62216c621`, the merge of PR #242.

**Approved scope: full-motor rotor iron loss for 0.5.9.** Sector rotor-loss
support is deferred to [#319](https://github.com/coilemdev/coilem/issues/319)
for a later release. The limited sector functionality already merged by #242
remains in 0.5.9. Full-versus-sector rotor-loss parity is not a 0.5.9 gate.

The sampling/loss foundation, analytical tests, public integration and bounded
full-circle SPM pilot are implemented. Remaining fixture and platform
qualification keeps #318 draft and #306 open.

## Approved reduced qualification matrix (2026-11-16)

Evaluate SPM 8p/12s concentrated at 0/20 A peak and flat-IPM 8p/12s FSAE at 0/50 A
peak, each at 1500/3000 rpm, public gamma 0, full motor, sinusoidal excitation,
matched M350-50A/N42 and fixed temperature assumptions. Preserve the completed
loaded-SPM pilot and reprocess its immutable fields at both speeds. The
magnetostatic model permits speed reuse at fixed geometry/materials/current;
record collection speed and loss-evaluation speed separately and check H∝rpm,
classical lamination E∝rpm² independently.

Four new field histories per solver: SPM no-load on the established pilot
mesh; flat-IPM loaded on working/finer meshes; flat-IPM no-load on its working
mesh. The flat-IPM loaded pair receives one independent spatial check in each
solver, max(5% of finer, 0.001 W) for hysteresis/lamination eddy/total. The
completed SPM three-mesh study is retained. This explicitly narrows the
original requirement for two successive mesh refinements at every condition;
no independent spatial-convergence claim is made for each no-load point.
Failed checks require investigation/refinement before acceptance.

Retain 96→192→384 angular subset checks at both speeds for every history, with
two successive component-wise max(5%, 0.001 W) steps. Collect 384 half-open poses
plus a fresh endpoint on one fixed material mesh; closure maximum ≤1e-6 T and
RMS ≤1e-7 T. Native/FEMM comparison remains max(10% FEMM, 0.001 W) per component.
Reference fields use a separate direct-DFT calculation and physical integration
weights, without mass normalization. Execute with at most two FEMM workers.

The external campaign registration and resumable supervisor retain exact mesh
controls, source snapshots, raw model/field hashes and each stage's verdict.
The existing A-F torque/back-EMF qualification does not qualify rotor loss.

## Release boundary and the deferred sector note

[PR #242's release plan](https://github.com/coilemdev/coilem/pull/242#issuecomment-6907488611)
originally required loss work to follow rotor elements with the rotor-side equivalent of
the repeating stator mesh: pole-pitch pieces, matching copies, a stable rotor
mesh frame, and a full-motor versus sector comparison. The sector feature is
now merged into 0.5.9. Its stator fix does not stabilize rotor material meshes.
The owner subsequently chose full-motor loss first for 0.5.9; the rotor-side
sector work below belongs to #319 rather than blocking #306.

Full-motor means a complete physical domain, not automatic support for every
rotor topology or material. The completed numerical pilot covers inner SPM;
the public stage also accepts supported flat-IPM, whose qualification and
unsupported-status rules remain required. Existing sector stator/copper estimates retain their documented
scope. New sector rotor-loss results must be explicitly unavailable, never
silently zero or presented as a complete full-motor loss calculation.

The current code confirms the distinction:

- `backend/sector_geometry.py` records `stator_iron_units` and splits stator
  steel into slot-pitch pieces; rotor regions are still clipped/meshed freely.
- `backend/gmsh_solver.py` uses `_copy_stator_iron_pitches` and
  `_sector_in_mesh_frame` to keep the stator mesh stable. There is no equivalent
  rotor material mesh contract yet.
- `backend/rotor_motion_mesh.py` preserves a full-circle inner-SPM material
  template and reconnects its air gap. It explicitly rejects sectors, IPM and
  outer rotors. It is internal and not enabled on the public solve path.
- `backend/rotor_iron_loss.py` implements rotor-frame sampling and the empirical
  harmonic calculation. Public solver results and `operating_point_losses`
  do not consume it; current public iron-loss/efficiency totals remain stator-only.

## Direct mesh diagnostic on the merged sector code

A fresh, mesh-only check uses the same SPM 8p/12s fixture, `symmetry: auto`,
Gmsh and coarse mesh at four positions. Preview tiles the solved sector to the
full motor; rotor corners are transformed back into rotor coordinates before
comparison. Each zero-pose centroid is located in the later mesh and its
triangle corners are compared. The same-mesh threshold is 1e-4 mm.

| Native angle | Tiled rotor iron cells | Rotor same mesh | Tiled stator iron cells | Stator maximum corner difference |
|---:|---:|---|---:|---:|
| 0 degrees | 3,224 | Yes | 7,596 | 0 mm |
| -15 degrees | 3,176 | No | 7,596 | 5.14e-6 mm |
| -30 degrees | 3,348 | No | 7,596 | 5.14e-6 mm |
| -39 degrees | 3,212 | No | 7,596 | 0 mm |

This demonstrates remeshing of rotor material, not a measured loss error.
There are no magnetic solves or loss estimates in this four-pose check.
Mesh counts alone are not the stability test; the recorded corner comparisons
also fail for the rotor and pass for the stator.

## Next full-motor qualification slice

### Qualification order before merging to 0.5.9

Keep #318 on its current base while completing and qualifying the full-motor
loss feature. Run the supported loss fixtures and full-mode regression controls
on this branch before merge. Compare existing electromagnetic/stator outputs
with the frozen `f2142dba` release baseline using identical full-motor requests.
The branch already contains #242's code; `symmetry: full` isolates the exercised
path, rather than pretending the sector code is absent from its ancestry.

Validate [#317](https://github.com/coilemdev/coilem/pull/317) independently. It
changes V-shape corner meshes and states that SPM, flat-IPM and Prius-style
meshes are unchanged. The initial #306 fixture coverage is SPM and flat IPM;
do not mix the V-shape change into its frozen validation baseline. Verify the
claimed unaffected paths when assembling the release.

After independently accepted changes land, run final qualification on the
assembled `release/v0.5.9` candidate on both platforms, covering full-motor
loss and the existing limited-sector functionality. Branch qualification
does not qualify an untested merged tree. Retain FEMM reference field histories
when geometry, materials, excitation and extraction remain identical and the
reference convergence gates pass; verify those identities explicitly instead
of recollecting FEMM merely because the native Git revision changed.

Current internal collector measurements are numerical development evidence,
not yet the complete qualification of the integrated public solve/API path.

### Bounded numerical and integration work

1. Finish the matched reference's registered 192/384-sample insertions on the
   same fixed FEMM mesh, checking component agreement, source/excitation
   identity, independent endpoint closure and both successive angular steps.
2. Independently refine the native and matched FEMM spatial meshes, keeping
   every material mesh fixed through its complete turn. Check hysteresis,
   lamination eddy and total separately at two successive refinements.
3. Review this same-motor proof before expanding the full-motor SPM/flat-IPM,
   no-load/loaded, two-speed coverage required by #306. A complete mechanical
   turn is required; a single electrical period is not silently reconstructed.
4. Integrate only supported, validated full-motor histories into public results,
   totals, efficiency/maps, API/CLI, saved results and exports, with exact-once
   accounting, provenance and explicit unavailable states.

The registered reference collection uses the frozen checkout at `205db73c`.
This preserves all source hashes while development proceeds on #306; resumed
histories must use the same frozen sources and inputs. Integration must also
be checked against the qualified fields rather than assuming the internal
pilot proves the public solve path.

## Deferred sector implementation: #319, after 0.5.9

1. **Rotor material mesh contract.** Extend the sector geometry/meshing
   machinery to identify rotor steel and magnet pieces by pole pitch and
   material identity. Build a master material mesh in canonical rotor axes,
   copy compatible pitches and preserve it across the requested poses. Keep
   the existing stator canonical frame and stator slot-pitch copies intact.
   Periodic geometry copies must not change per-pole magnetization directions.
   Make reuse identity include geometry, material layout and mesh controls.
2. **Motion and interface.** Assemble those material meshes at each signed
   pose and preserve conforming air-gap connections, exact sector/anti-periodic
   constraints and cut-edge pairing. Explicitly resolve the close-cut/snap
   behavior without remeshing the loss-bearing material. Merely changing the
   whole mesher to a rotor frame would destabilize the stator again. Cases
   without a proven stable material mesh must remain explicitly unsupported
   for rotor loss rather than silently using the free-remeshing history.
3. **Bounded proof on this motor.** Start with the current SPM fixture in
   full and half-sector modes. Check material-cell identity in rotor axes
   through ordinary, stepped-cut and close-cut positions, watertight joins,
   positive cells, phase currents and magnet directions. Replay the prescribed
   spatial DC field: zero temporal rotor loss within the declared 0.001 W
   absolute floor. Independently calculated sinusoidal/multiharmonic controls
   must stay within the issue's 1% analytical gate in both rotation directions.
4. **Real loss parity.** Solve matched full-motor and sector histories on a
   complete mechanical turn. Compare hysteresis, lamination eddy and total
   separately, with physical integration weights and no mass normalization.
   First use a copied-sector/full-circle identical-mesh control to check ties
   and whole-motor scaling to numerical precision. Then use independently
   meshed full/sector histories with the predeclared max(5%, 0.001 W) component
   comparison target and separately establish their angular/spatial convergence.
   Report the bounded result before expanding the fixture matrix.

The pole-pitch material identity should be usable by future component-loss
work, but magnet/component eddy-current physics remains #307, outside #306.

## Full-motor 0.5.9 acceptance gates

- **Corrected FEMM reference:** the loaded-SPM384 pilot, both angular steps,
  and two independent native/FEMM spatial refinements have passed. Remaining
  conditions follow the approved reduced mesh plan above, retaining angular,
  source/excitation/closure and separate component-agreement gates.
- **Supported fixtures:** satisfy #306's SPM and flat-IPM, no-load/loaded,
  two-speed matrix on full-motor solves. Sector rotor-loss parity is deferred. Do not
  infer subharmonics from a single electrical period; the current rotor
  sampling contract requires a full mechanical turn.
- **Product integration:** capture rotor fields with the complete sampling
  contract, attach material/method/status provenance, and expose separate
  rotor hysteresis, lamination eddy and total. Include rotor loss exactly once
  in operating-point totals, shaft power/torque, efficiency maps, API/CLI,
  saved results and exports. Unsupported geometry/material/sampling must give
  an explicit unavailable result, including sector rotor loss, and older saved
  runs retain their method. Existing sector stator/copper estimates must retain
  their documented scope without implying the missing rotor term is zero.
- **Integration verification:** exact-once accounting and energy balance,
  unavailable propagation, zero-loss/backward-compatible saved records,
  full-domain integration, sector-unavailable behavior, exports and maps. Add tests at these boundaries rather
  than only repeating the loss kernel's equations.
- **Release:** run existing limited-sector regression and new full-motor loss qualification on both
  platforms on the assembled release branch. Follow #242's plan to bump
  Magneto2D once before final qualification. Current evidence does not replace
  release qualification or validate the empirical coefficients against motors.
  Rotor-loss sector mesh stability and full/sector loss parity are future #319
  gates, not conditions for shipping qualified full-motor loss in 0.5.9.

## Branch and verification

The working branch remains `codex/306-rotor-iron-loss-pilot`. Its nine commits
were rebased onto the actual merged 0.5.9 head. The before-rebase branch is
`codex/306-before-release59-20261116`. The rebased tree was byte-identical to
the previous pilot tree, so hashed collection sources and raw datasets remain
unchanged. Historical reports retain their original measurement commit IDs.

Fresh post-rebase verification: **267 rotor/loss/reference/sector tests pass**
in 66.89 s, using the existing source-matched native binary. Native and Rust
sources did not change; this check does not claim a new Rust qualification.
The [readiness record](benchmarks/rotor-59-landing-306-20261116.json) binds the
diagnostic, its script, test receipts, merged base and collected
native/reference source identities by SHA-256.

The [matched 96-sample reference result](benchmarks/rotor-matched-femm-306-20261116.md)
and [fixed-material native pilot](benchmarks/rotor-fixed-material-306-20261116.md)
remain the current numerical evidence. The old 47.707 mW reference is not a
same-operating-point target. Keep the PR draft and reference #306 without
closing it until the remaining implementation and acceptance criteria pass.
