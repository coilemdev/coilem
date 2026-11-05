# FEMM LRK outrunner: architecture review and comparison plan

Status: local experimental workstream; source review and fresh FEMM source-point reproduction complete. Native outrunner support and qualification are in progress.

Reviewed on 2026-11-05. Base: `release/v0.5.1` at `cf6e8a90e4a33c34dc7ff81886e353b9950961d5` (PR #196). Local branch: `codex/femm-outrunner-v051`. Worktree: `C:/bench/coilem-outrunner-v051-20261105`. The existing dirty `coilem-launch` checkout was not switched or modified. No push, PR, merge, release edit, or benchmark registration is part of this workstream.

## Decision

Build one immutable published-reference fixture, `femm_lrk_12s14p_v1`, from the exact **full-circle** FEMM source. Resolve it into coilEM's geometry IR, explicit material/source definitions, native Gmsh mesh, and Magneto2D solve. Add the example to the local experimental application after that path passes its numerical checks.

Use three comparison lanes, in order:

1. **FEMM source reproduction:** solve the original full model, then its full sliding-band companion, to establish the reference and torque-body conventions.
2. **Same-mesh diagnostic:** feed an audited export of the full FEMM mesh and its physical assignments to Magneto2D. This isolates material, source, field assembly, and postprocessing differences from geometry/meshing differences.
3. **Independent native comparison:** build the same geometry with coilEM IR/Gmsh and compare Magneto2D with the frozen, independently generated FEMM reference.

The same-mesh lane is development tooling, not the native application path. The half-model is an additional FEMM reference self-check; Magneto2D anti-periodic sectors and a new sliding-band implementation are not prerequisites for the full-circle fixture.

The first implementation should support static torque, no-load phase linkage/BEMF, and explicitly defined current sensitivities. Losses, efficiency, thermal behavior, ESC/PWM behavior, and arbitrary editable outrunner designs remain outside this fixture's scope. This numerical example is distinct from the purchased FEICHAO hardware motor.

## 1. Source identity and audited facts

Primary source: [FEMM Sliding Band Benchmark](https://www.femm.info/wiki/SlidingBandBenchmark). The three linked `.fem` files were downloaded without alteration to `output/femm-outrunner-review/source/`. The read-only audit and complete numeric records are in `output/femm-outrunner-review/audit_sources.py` and `source-audit.json`.

| File | SHA-256 | Points / lines / arcs / labels |
| --- | --- | --- |
| `WholeMotor.fem` | `e69cce40a56f0c9840892a122cda86e5b3fa69d0b0c6ccc718d4d430b059253e` | 158 / 112 / 58 / 29 |
| `WholeMotorSlidingBand.fem` | `62dc72be4e4de0161dc1538bd35f921480a5169647238f8b4057ec88762105ee` | 162 / 112 / 62 / 30 |
| `HalfMotorSlidingBand.fem` | `2fae75121f569d9ce6e1960270d88e978b6d4cadd04f23860a7a73b8b3f2265b` | 89 / 64 / 33 / 17 |

Source retrieval URLs use `https://www.femm.info/doku/lib/exe/fetch.php?media=upload%3Aslidingbandbenchmark%3A` followed by the lower-case filename. A later upstream change requires a new fixture identity and review. Keep the original bytes and conversion hash separate. Source redistribution terms should be recorded before any future publication; this review and its downloads stay local.

### Geometry and boundaries

The files specify a planar magnetostatic problem in millimeters, 10 mm depth, precision `1e-8`, smart meshing on, and a 30 degree minimum element angle. The full model has 14 magnets, 12 copper regions, one stator-steel region, one rotor-steel region, and one connected air region.

| Physical feature | Source dimension |
| --- | ---: |
| Inner circular bore boundary | radius 6.5 mm |
| Stator slot/yoke root arcs | radius 8.25 mm |
| Stator tooth-tip arcs | radius 12.8 mm |
| Magnet inner face | radius 13.0 mm |
| Magnet outer face | radius 14.0 mm |
| Rotor back-iron inner face | radius 14.14 mm |
| Rotor back-iron outer face / outer problem boundary | radius 15.39 mm |
| Physical tooth-tip-to-magnet air gap | 0.2 mm |
| Magnet arc span | 20 degrees per magnet |
| Magnet-to-back-iron radial air clearance | 0.14 mm |

Preserve the 0.14 mm clearance and inter-magnet air; do not attach the magnets directly to the steel. Preserve the actual tooth-tip/slot-mouth curves, not just these radii. The **inner bore and outer back-iron circles both carry `A=0`**. The bore interior is a hole, not a modeled magnetic shaft; there is no added exterior air domain beyond the source's outer circle.

The full non-sliding source defines a `myGap` property but does not use it on its edges. A declared property is not an applied boundary condition. The sliding files add interfaces at radii 12.87 and 12.93 mm and an unmeshed band. The full sliding model uses a periodic air-gap condition; the half sliding model uses an anti-periodic gap and anti-periodic cut pairs. Keep those numerical motion devices out of the canonical physical geometry.

### Materials

| Role | Exact source properties to preserve |
| --- | --- |
| Stator | `M-19 Steel`, 13 B-H points, `LamType=0`, `LamFill=0.95`, 0.3556 mm lamination thickness |
| Rotor back iron | `1018 Steel`, its separate 13-point B-H curve, fill 1 |
| Magnets | `NdFeB 40 MGOe`, relative permeability 1.049, coercivity 979000 A/m |
| Copper | `AWG22`, relative permeability 1, conductivity 58 MS/m, stranded-winding source definition |
| Air | relative permeability 1 |

For the isotropic linear recoil law, the magnet inputs imply `Br = mu0 * mu_r * Hc = 1.2905298196199053 T`. Store the original Hc/permeability and the derived Br with units. Do not replace the magnet with coilEM's N42 catalog value or either steel with M350-50A. The file also contains an unused `Iron` material definition; the material list alone does not establish region use.

Raw B-H points are necessary but insufficient for parity. Audit FEMM's interpolation, high-field extrapolation, and lamination homogenization against Magneto2D's resolved material law. Do not implement lamination fill by multiplying final torque or stack length. Preserve raw and resolved curves, transformation version, and hashes. Use material coupons before interpreting a motor discrepancy as a field-solver error.

### Winding and source operating point

There are three **series** FEMM circuits: A = 0 A, B = +4 A, C = -4 A. Each copper region has signed turns `+15` or `-15`. This is six wound teeth, two 15-turn coils per phase, with two coil sides per coil. Do not synthesize a different winding from only the 12-slot/14-pole counts.

Approximate region-center directions below are identifiers for review; actual boundary curves and block seeds remain the geometry authority.

| Copper region around the circle, CCW | Circuit | Signed turns |
| ---: | --- | ---: |
| near 15 degrees | A | -15 |
| near 45 degrees | B | -15 |
| near 75 degrees | B | +15 |
| near 105 degrees | C | +15 |
| near 135 degrees | C | -15 |
| near 165 degrees | A | -15 |
| near 195 degrees | A | +15 |
| near 225 degrees | B | +15 |
| near 255 degrees | B | -15 |
| near 285 degrees | C | -15 |
| near 315 degrees | C | +15 |
| near 345 degrees | A | +15 |

The source prescribes circuit currents; it does not establish a physical terminal wye/delta connection. The first fixture therefore uses explicit circuit currents and phase linkage without claiming an inferred terminal connection or manufacturer Kv.

### Published values versus fresh measurements

The source page reports 55.4274 mN·m for whole-model WST, 55.4302 mN·m for whole-model sliding-gap torque, and 55.3843 mN·m for the half-model sliding-gap torque. These are **published reproduction targets**, not fresh measurements on this checkout and not Magneto2D results. The half-model WST integral needs explicit full-machine scaling; gap-integral scaling is different and must be recorded rather than applied twice.

FEMM 4.2 is installed locally at `C:/femm42/bin/femm.exe`, SHA-256 `5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21`. The first Lua attempt used a MATLAB-wrapper command name and failed. The corrected Lua attempt completed its numerical rows while its process cleanup was being investigated; an early timeout note incorrectly marked it unmeasured. An independent, isolated COM run reproduced all three rows. Both the earlier attempt records and the correcting evidence are retained in `output/femm-outrunner-review/published-point/`.

Fresh full-model outer-rotor WST is **-0.05542741539565078 N·m CCW**. Full sliding-gap torque is **+0.0554301864846747 N·m**, while WST on that sliding model's outer rotor is **-0.0554058786814183 N·m**. Half-model raw outer-rotor WST is **-0.02765096800453747 N·m** and its gap integral is **+0.05538425758169933 N·m**. Thus the gap-integral sign is opposite to selected outer-body WST and its half-model scaling is already applied. The source-page magnitudes are reproduced, but signs must be normalized by body. No Magneto2D comparison is claimed by this source-point reproduction.

## 2. Findings in the v0.5.1 architecture

| Area | Finding at the pinned base | Required response |
| --- | --- | --- |
| Request model | `backend/models/config.py`: minimum stator OD 30 mm, ID 20 mm, magnet thickness 2 mm, SPM magnet width 5 mm; rotor must fit inside the stator bore. | This fixture is physically outside that request's domain. Do not invent inner-rotor dimensions to pass validation. |
| Existing reference dispatch | `geometry_reference` and `reference_case` admit only Prius cases; several callers import Prius helpers directly. | Introduce explicit fixture dispatch without giving the new fixture Prius current, temperature, or geometry behavior. |
| Geometry | `geometry_drawer.compute_geometry`, normal `geometry_ir` builders, and `preview.py` assume an inner rotor and inward-facing teeth. | Use a pinned source-derived IR builder; preview and solve consume the same curves and region identities. |
| Gmsh lowering | `gmsh_solver.py` derives gap radii from rotor OD plus magnet thickness and stator ID, and assigns outer Dirichlet nodes at stator OD. | Resolve physical gap radii and every prescribed boundary from the model definition, independent of radial layout. |
| Imported physics | Artifacts already carry region IDs, motion groups, element current density, magnetization, and winding metadata. | Reuse this seam; require a complete explicit contract for the fixture even though its electromagnetic topology is SPM. The current SPM compatibility path is too permissive. |
| Native model | `solve/model/spm.rs` has an inner-rotor magnet band; `MachineModel` has SPM/IPM branches and a fallback for unknown topology strings. | Keep topology `SPM`; describe radial layout separately. Fail closed on unsupported combinations. No unknown `OUTRUNNER` topology that silently falls into IPM. |
| Torque | `mesh.rs` has explicit inner/outer gap radii, but WST fallback boundary placement, slot-domain bounds, and localization still conflate inner/outer with rotor/stator. Contour/Arkkio integrate the enclosed body's torque. | Make the selected body and boundary roles explicit. Audit all torque estimators, their diagnostics, and one-time public sign conversion. |
| Winding extraction | The Prius reference already overrides generic polar winding extraction using actual region labels and nodal Az. | Extract a shared region-winding functional; retain Prius equivalence tests. Explicit source and linkage must use the same signed winding weights. |
| Source orchestration | Generic q-axis/six-step synthesis, clockwise mirroring, current rebaking, and slot-pitch cache reuse have reference special cases. | Prescribed source currents must survive fresh, cached, no-load, and playback paths unchanged. Disable congruence reuse for the first fixture. |
| Materials | Project-scoped custom steel curves already exist; the normal public catalog and magnet payload do not express the full source magnet/lamination semantics. | Reuse embedded steel identities where possible and add a typed fixture material resolution step, with behavior checks and hashes. |
| Persistence/UI | `designFile.ts` and frontend types recognize only the current reference. Geometry controls and some summaries assume ordinary MotorConfig dimensions. | Use a versioned frozen-reference document and a read-only resolved display model. Do not quietly coerce a saved reference into an editable inner-rotor design. |
| Evidence | Existing external reference runner has isolated, resumable, hashed producer jobs; v0.5.1 keeps historical cogging replay separate from live records. | Reuse those mechanisms in a separate experimental suite. Preserve existing protocol 1.7 records, thresholds, and historical fixtures. |

Most field assembly can be reused. The high-risk work is in geometry/physics translation, material equivalence, source identity, and body-specific postprocessing rather than a new PDE solver.

## 3. Proposed design

### 3.1 Input and resolved model

Add a narrow, discriminated `PublishedMotorRequest` alongside the existing parametric `MotorConfig`. Proposed identity: `schema_kind="published_motor_request"`, version 1, `fixture_id="femm_lrk_12s14p_v1"`, an allowlisted `case_id`, and bounded mesh/solver/output choices. The source geometry, winding, materials, and angle-zero definition are immutable; a case may prescribe different current vectors or a no-load sweep. Reject arbitrary geometry/material edits and unsupported analyses.

Keep the existing parametric model's limits and defaults unchanged. This avoids lowering every product constraint just to admit a reference motor. Resolve both input kinds through an incremental shared model interface; adapt the existing MotorConfig path without changing its behavior. A future generic outer-rotor editor can supply that interface after this fixture is verified.

The resolved model must expose: geometry IR; radial layout; stack length; pole/slot counts; exact region-to-material and region-to-winding tables; physical air-gap bounds; Dirichlet boundary loops; rotating body region IDs; a phase-current function; coordinate convention; and source/conversion/material-law hashes. Centralize dispatch in `backend/reference_models/` rather than copying Prius-specific conditionals into another dozen call sites. Preserve the legacy Prius request format through its existing adapter.

For the first development slice, expose this through an experimental tool/API path with the experimental switch required. It is not a new release-supported topology. The local UI example and saved-document union come after the backend contract is verified.

### 3.2 Exact geometry lowering

Use a small, audited **fixture-specific** converter for the frozen FEMM format subset. Preserve source nodes, line/arc endpoints, arc sweeps, block seeds, applied boundary assignments, holes, magnetization directions, and group membership. Reconstruct closed region loops and stable IDs. Unsupported format features fail closed. Do not build a general-purpose FEMM importer in this workstream.

`WholeMotor.fem` defines the physical model. Its sliding companions validate reference motion methods; their unmeshed band is not physical missing air in Gmsh. Keep the entire annular domain from 6.5 to 15.39 mm, including winding cavities, the main gap, magnet gaps, and the back-iron clearance. Geometry IR may split connected air into numerical subregions to identify the clean 12.8–13.0 mm torque band, provided their material and continuity stay unchanged.

Assign `stationary` to stator/copper and `rotor` to all 14 magnets and the steel ring. Rotate only rotor curves and magnetization by the same native CCW angle. The circular bore and outer circle remain exact Dirichlet loops. Start with remeshing each position and no sector reduction, relabel rotation, or slot-pitch mesh reuse.

### 3.3 Sources and flux linkage

For winding region k, with signed turns `n_k`, meshed area `A_k` in m², and circuit current `I_phase`, use `J_k = n_k * I_phase / A_k`. Verify the integrated ampere-turns after every fresh mesh and cache rebake. Do not divide by parallel paths a second time or apply conductor fill to the total ampere-turns.

Extract phase linkage from the same winding functional: `lambda_phase = L * sum_k(n_k * mean_region(Az))`. Preserve all 12 sides and use actual meshed areas. The signed turns per phase sum to zero, so adding a constant gauge offset to Az must leave phase linkage unchanged. Check `sum(lambda_phase * I_phase) = L * integral(Az * Jz dA)` as a translation identity, not a complete electromagnetic-energy validation.

A named `fixed_bc_4A` case means exactly `[0,+4,-4] A` at every angle. No q-axis gamma or commutation rule is inferred. A no-load case uses exactly zero currents everywhere. Report the actual current vector and source rule, not unused generic sine settings.

### 3.4 Material contract

Create two separately hashed resolved steel laws and one explicit recoil-law magnet definition. Scope them to the fixture; do not overwrite global M19/1018/N42 catalog entries. Record raw FEMM properties, raw B-H points, homogenization/interpolation implementation, resolved curves, permeability caps, and extrapolation policy. Coupon comparisons cover 0–2.5 T, including the end of each tabulated curve.

If a source law cannot yet be matched, retain that as an unresolved constitutive difference. A deliberately simplified material variant may diagnose assembly but gets a separate case ID/hash and cannot stand in for the original nonlinear fixture. No magnet-strength scaling to make torque match.

### 3.5 Torque and conventions

Use the source drawing as native angle zero and native CCW-positive geometry. Preserve raw FEMM WST selection and gap-integral outputs with their body conventions. Establish the sliding companion's **outer** motion angle at +delta/-delta; do not reuse the inner-rotor boundary-angle command without checking it.

The requested reported torque is on the **outer rotating assembly**, not the stator enclosed by an ordinary gap contour. WST weights must be 1 on the selected moving body's interfaces and 0 on stationary interfaces; radial fallbacks must follow those roles. Contour/MST/Arkkio need an explicit body-orientation treatment and an action/reaction check. Make this a solver result contract, not a minus sign added only in the graph.

Apply the application's clockwise display conversion once: `theta_CW=-theta_CCW` and `T_CW=-T_CCW`, with the actual phase-current and winding definitions preserved. Compare raw CCW values before testing UI normalization. No best-fit angular shift, phase permutation, scale fit, or absolute-value correction is allowed in qualification metrics.

### 3.6 Cache, provenance, UI, and packaging

Cache identity includes fixture/source/converter hashes, radial layout, material laws, winding map, body selection, boundary policy, mesh profile, native angle, and solver build. Current-independent meshes may be reused only through the explicit fixture current rebaker. Bump the signature when semantics change; test stale-cache rejection and fresh/cached equivalence.

The local example displays its frozen source, real dimensions, materials, and available cases. It uses shared IR preview contours and a read-only resolved display model, including outward-facing teeth and the rotating bell. Save/reopen must retain fixture identity and hashes; missing/mismatched assets produce an actionable error. Winding/field playback, CSV, PDF, and replay exports must retain actual source and torque conventions. Disable efficiency and unrelated motor-map outputs for this fixture.

Add fixture assets to package data only when the local example is ready, with an asset-completeness check. FEMM and its diagnostic adapter remain separately installed development tools; they do not enter the public runtime or wheel dependencies.

## 4. Comparison protocol

The proposed machine-readable plan is [comparison-plan.json](comparison-plan.json). It is a draft experimental protocol, not a registered benchmark or a measured result. Freeze its exact request, grids, thresholds, and conventions before generating qualifying candidate/reference data. Later changes require new identities and retained earlier attempts.

### Stage A: input and reference preflight

1. Fix the isolated FEMM producer startup; log each operation, propagate Lua errors, enforce a timeout, retain failure artifacts, and close only producer-owned processes.
2. Hash FEMM, its mesher/solver executables, producer code, source files, and any copied/modified case files. Record FEMM build/version, settings, OS, and application base/candidate commits.
3. Solve the three original files unchanged. Save `.fem`, `.ans`, raw currents/linkages, raw WST selection, raw gap torque, and element counts. Compare the source-page values as reproduction checks, with an initial 1% warning threshold. Diagnose differences rather than tuning toward rounded published numbers.
4. On the full sliding model, prove +delta/-delta outer motion and torque body sign. Verify the full/half distinction using correctly scaled WST and gap results. Target <=0.5% agreement after each reference's mesh check; this is a reference-quality condition, not an application pass.
5. Complete material coupons, geometry-area/boundary audits, and winding ampere-turn checks before motor qualification.

### Stage B: same-mesh diagnostic

Export the full non-sliding FEMM mesh, node coordinates, triangle connectivity, per-element **block-label/material identity**, winding assignments, magnetization, and prescribed boundary nodes. Group numbers alone are insufficient: group 2 contains both steel and magnets, and group 1 contains all winding sides. Use the saved answer/input data to retain exact region identities rather than generic polar classification.

Create a separately marked diagnostic SolveMeshArtifact. Verify units, triangle orientation, complete region coverage, zero currents outside copper, each coil-side ampere-turn integral, and both Dirichlet circles. Require original source hash and converter identity. Run Magneto2D on this mesh before introducing native Gmsh meshes.

Compare gauge-consistent nodal Az, region-interior B samples, phase linkage, selected-body torque, and nonlinear convergence. Exclude interface sampling points from B comparisons; FEMM smoothed B is not identical to raw P1 element B. Keep raw element-B, smoothing, and extraction rules in the evidence. This lane localizes a discrepancy; it does not establish native-mesh accuracy.

### Stage C: independent Gmsh/Magneto2D comparison

| Case family | Source and grid | Outputs |
| --- | --- | --- |
| Published point | native theta=0, currents `[0,+4,-4] A` | Rotor torque, A/B/C linkage, source/material audit, field samples |
| Orientation probes | theta=-1/7, 0, +1/7 degrees mechanical; same fixed currents | Raw/native and UI signs, outer motion, phase identity |
| Current sensitivity | theta=0; `[0,I,-I]`, I=-6,-4,-2,-1,0,1,2,4,6 A | Static T(I), linkage, saturation trend; no generic Kt inferred from one torque/current ratio |
| Fixed-current torque sweep | one electrical period, 0–360/7 degrees mechanical; 192 unique samples plus independently solved endpoint | Mean, peak-to-peak, waveform and harmonics; refine to 384 unique samples |
| No-load linkage/BEMF | same 192+endpoint grid, exact zero current; normalization at 1000 rpm | A/B/C and line-line linkage/BEMF, fundamental amplitude/phase, winding symmetry; refine to 384 |
| Cogging | 0–30/7 degrees mechanical = 30 degrees electrical; 96 unique samples plus endpoint, then 192 | Peak-to-peak, first cogging harmonic, mean and closure |

The pole-pair count is 7. The geometric cogging period is `360/lcm(12,14)=30/7` degrees mechanical. Use rational grids to avoid accumulated endpoint drift. Exclude the repeated endpoint from means, RMS, and DFT; solve it separately for closure. Add a full mechanical-revolution closure and periodicity audit before relying on reduced sweep periods.

Compute BEMF from the periodic linkage derivative and mechanical speed in rad/s; do not multiply by pole pairs twice when differentiating an electrical-angle grid. Freeze circuit voltage polarity and whether the reported quantity is induced EMF or opposing motor back-EMF. Record phase/line-line and peak/RMS conventions. The 1000 rpm value is a normalization point, not a rated operating point of a physical motor.

Static torque sensitivity is `dT_rotor/dI` for the stated B/C current vector and angle. If incremental inductance is added later, define the loop quantity `d(lambda_B-lambda_C)/dI`, its bias, perturbation, and fixed angle. Do not infer resistance, losses, efficiency, terminal Kv, or arbitrary dq constants from these fields alone.

### Stage D: independent convergence and diagnostic cross-checks

Converge FEMM and Gmsh separately; matching element counts is not a convergence test. Preserve the original FEMM mesh/arc constraints for source reproduction. For controlled studies, propose main-gap size targets 0.05, 0.025, and 0.0125 mm; measure the resulting gap resolution rather than treating a target as a guaranteed layer count. Refine tooth tips, slot mouths, magnet ends, and the 0.14 mm clearance as well. Record actual element/node counts, size statistics, curve approximation, and quality.

Perform spatial refinement on the source point and representative no-load/cogging positions. Perform angular refinement on all waveforms. Require consecutive-level changes below 0.5% for loaded torque and linkage fundamentals, and below 2% for cogging peak-to-peak/fundamental, subject to the fixed absolute floors below. Tighten nonlinear/linear tolerances independently and show that changes are smaller than the comparison budget. Settings named normal/fine are not evidence by themselves.

Cross-check WST against multiple fully covered gap contours and Arkkio with body signs normalized. Use coenergy derivatives only with a verified PM/nonlinear coenergy definition and a delta-size study. The low-current torque/linkage identity is a useful additional check; do not assume a linear PM torque formula remains exact under nonlinear saturation.

### Proposed acceptance gates

These are fixture-specific draft gates. They do not change existing coilEM protocols. A missing result is UNMEASURED; a failed reference self-check is REFERENCE_INVALID, not candidate PASS/YELLOW. Retain failures and attempts.

| Metric | Proposed PASS condition |
| --- | --- |
| Input/source/assignment identity | Exact hashes, no unclassified elements, exact requested currents and complete prescribed boundaries |
| Coil-side source conservation | Ampere-turn error <= max(1e-9 A-turn, 1e-10 relative) |
| Static loaded torque | Absolute difference <= max(2% of reference magnitude, 5e-5 N·m) |
| Loaded waveform | NRMSE <=2% of reference peak magnitude; same fixed angle grid and sign |
| Phase linkage waveform | Relative L2 error <=1% per phase; no phase fitting |
| BEMF fundamental | Amplitude error <=2%, phase error <=1 degree electrical per phase |
| Current sensitivity | Slope difference <=3%, with converged finite differences and stated angle/bias |
| Cogging peak-to-peak and fundamental | Each difference <= max(10% of reference magnitude, 5e-6 N·m) |
| Cogging reference mean and endpoint closure | Each <= max(1% of reference peak-to-peak, 5e-6 N·m) |
| Periodic linkage closure | <= max(0.1% of linkage peak magnitude, 1e-9 Wb) per phase |

For near-zero quantities use the stated absolute bound rather than dividing by zero. NRMSE/phase metrics are not applicable below their recorded signal floor; report that status explicitly. No post-result threshold relaxation or selective angle omission. The same-mesh diagnostic may initially expose a material-law mismatch; qualification waits for its documented resolution rather than silently fitting a correction.

## 5. Evidence and implementation slices

Every comparison row should retain: case/request hash; source and converter hashes; raw and resolved material hashes; winding map; native/display angle conventions; requested and integrated current vectors; selected torque body and estimator; solver binary/source pins; mesh/profile/hash; tolerance/iteration/convergence data; raw fields or answer files; raw and normalized metrics; timing; and status/failure history. Reference and native evidence live in separate folders bound by a comparison manifest.

Use `tools/run_reference_benchmark.py`'s producer interface for FEMM, with an experimental adapter outside the shipping runtime. Keep this suite under a new experimental fixture identity; do not append rows to historical ABCD or cogging reports. A later registration/publication decision requires its own explicit task.

| Slice | Deliverable | Exit check |
| --- | --- | --- |
| 0. Source and design review | This review, source audit, proposed matrix, exact release base | Complete; sources remain unchanged, no numerical verdict |
| 1. Reference producer | Logged isolated FEMM startup; three source-point answers and +/-angle probes | Fresh reference reproduces source within explained uncertainty; processes close cleanly |
| 2. Typed fixture and material laws | Frozen source-derived region model, winding table, two steel laws and recoil magnet | Geometry/holes/boundaries, coupon behavior, and source conservation verified |
| 3. Magneto2D translation | Explicit fixture input/artifact, same-mesh static solve, body-aware torque and winding extraction | No unsupported analytic fallback; field/linkage/torque discrepancy understood |
| 4. Native model | Exact IR/Gmsh builder, explicit boundaries and rotor motion, source-current rebaker | Full native source point and +/-motion pass; stale-cache and current-leakage checks pass |
| 5. Matrix and convergence | Loaded, no-load, current sensitivity, cogging, independent mesh/angular studies | Frozen gates evaluated with reference self-checks; failures visible |
| 6. Local coilEM example | Frozen experimental example, actual geometry/field view, save/reopen and exports | Backend/UI/CSV/replay values agree; ordinary models and Prius regressions pass |

Focused automated checks should cover actual failure modes: exact source reconstruction, correct holes and boundaries, magnet-vector rotation once, all-region current conservation, gauge-invariant linkage, body-aware torque sign, independent period closure, fresh/cached source equivalence, zero-current no-load after a loaded run, stale material/geometry cache rejection, fail-closed unknown fixtures, save/reopen identity, and existing inner-rotor/Prius behavior. Do not substitute replay-only tests for fresh external/native measurements.

Planning estimate after the producer smoke test: approximately 2–4 focused engineering weeks for a narrow, reviewed local fixture and comparison, depending on material-law and postprocessing discrepancies. The first source-point native milestone should precede UI polish and full sweeps. No delivery date or accuracy claim is established by this estimate.

## 6. Immediate next action

Implement slice 1 first: repair and verify the isolated reference producer, capture the three unchanged source-point solutions and torque-body orientation probes, and freeze the resolved physical contract. Then implement the typed fixture/source lowering and same-mesh Magneto2D comparison. Do not begin by drawing an approximate outer rotor in the existing inner-rotor editor.
