# Rotor iron loss: first slice of #306

Target: 0.5.9. Base: main `a3e70035`. This slice defines and exercises an
internal sampling contract. It does not change public loss/efficiency results,
map requests, field solves, saved results or release qualification claims.

## Contract

`backend/rotor_iron_loss.py` defines:

- `RotorSamplingPlan`: a uniform, half-open, full mechanical revolution. Poses
  are signed, unwrapped native CCW mechanical degrees. Negative direction is
  clockwise motion. The time base is `60 / speed_rpm`, independent of pole pairs.
  An independently solved endpoint is diagnostic and is excluded from the DFT.
- `sample_rotor_field`: adapts explicitly declared `global` or `rotor_material`
  mesh/vector coordinates into rotor axes. Already-material-frame exports are
  retained; global exports rotate both geometry and B. Only explicit
  `rotor_core`/`RotorCore` elements are accepted;
  shafts, magnets, pockets and generic steel tags do not imply laminations.
- `rotor_flux_history`: follows first-frame triangle centroids through reordered
  or independently remeshed rotor meshes. Integration areas stay attached to the
  reference material cells. Missing material points are errors, not extrapolated
  values. A full-machine field mesh is required in this first version.
- `RotorLossMaterial`: explicit steel identity, coefficient source, density and
  stacking factor. These inputs are independent of stator material selection.
- `harmonic_rotor_iron_loss`: applies the existing two-term harmonic kernel using
  the mechanical-history base frequency. DC and the unresolved Nyquist bin are
  excluded. There is no electrical pole-pair multiplier or half-wave extension.

The existing stator numerical kernel is unchanged. Its `StatorFluxHistory` type
is used only as an internal numerical adapter. Before public integration, the
shared kernel/types can be renamed with compatibility aliases.

The material law remains an empirical harmonic approximation: DC bias and minor
loops, rotating-flux corrections, excess loss and loss-field feedback are not
modelled. A successful FEMM comparison does not establish measured motor accuracy.

## Analytical checks

Tests cover CW/CCW motion and nonzero initial pose, a rigidly co-rotating field
with zero rotor-frame loss, prescribed vector sinusoids, multiple harmonics plus
DC bias, mechanical frequency, speed scaling, mass/stacking scaling, element
reordering, remeshing, missing material points and invalid inputs. Expected
watts are calculated separately from the production loss kernel (1% gate).

`tools/rotor_loss_reference.py` is a second oracle. It uses explicit cosine/sine
DFT projections and has no production-backend imports. It is tested against
prescribed analytical fields before being used on exported FEMM queries.

## Bounded FEMM pilot

One existing SPM 8p/12s geometry, sinusoidal 20 A peak, gamma 0 degrees, 3,000 rpm,
M350-50A, full machine, fixed nominal magnet properties. Normal mesh with smart
meshing and a 0.125 mm air-gap target. Collect 96 independent angular solutions
plus a separately solved closure endpoint. No angular symmetry is reconstructed.

The optional collector `tools/femm_reference/rotor_loss_pilot.py` uses the frozen
E geometry/excitation backend in its own process. E/F files and source seals
are unchanged. The reference backend must never be activated in the production
analysis process, because it has its own `backend` import namespace.

For every position retain `.fem`, `.ans`, raw rotor triangle vertices/B, and
separate FEMM B queries at the moving reference material centroids. Smoothing is
disabled. Group 10 identifies the laminated rotor core, including no shaft.
Models/answers/scripts/exports are hashed in the position checkpoint. Two owned
FEMM workers may collect disjoint shards after position zero establishes the
reference grid. Windows job objects close only their owned FEMM processes.

The report verifies all checkpoints, fixture identity and query coordinates.
Production geometric sampling and the independent direct-DFT oracle are then
compared using the same reference integration areas. This checks the new
sampling and loss evaluation against FEMM field queries; it is not a native
Magneto2D-versus-FEMM field comparison.

Predeclared gates: analytical 1%, reference agreement 10%, successive convergence
changes 5%, each with an absolute 0.001 W floor for near-zero machine losses.
The report evaluates 24/48/96-position histories by decimating the 96-position
collection. It keeps hysteresis, lamination eddy and total checks separate.
The Nyquist component is unresolved, not counted as a loss estimate. In
particular, 24 samples cannot resolve a mechanical order-12 slot harmonic.

No mesh-refinement gate is run in this bounded pilot. Its status remains
`PILOT_NOT_QUALIFIED` even if the sampling/oracle comparisons pass. A later
matrix must independently refine mesh and angles, pass both successive 5%
changes, and cover the SPM/IPM, no-load/loaded, two-speed combinations in #306.

## Reproduce

In a dedicated Python 3.11-3.14 environment, install
`tools/femm_reference/requirements.txt`. FEMM 4.2 must be installed separately;
the collector verifies its actual binary hashes. From this source checkout:

```powershell
python -m tools.femm_reference.rotor_loss_pilot --out output/rotor-pilot --positions 96 --limit 1
# Run the next two commands in separate shells, using the same environment:
python -m tools.femm_reference.rotor_loss_pilot --out output/rotor-pilot --positions 96 --resume --shard 0/2
python -m tools.femm_reference.rotor_loss_pilot --out output/rotor-pilot --positions 96 --resume --shard 1/2
# After both workers finish, use a fresh process (no reference backend activated):
python -m tools.rotor_loss_pilot_report output/rotor-pilot
python -m pytest tests/test_rotor_iron_loss.py tests/test_rotor_loss_pilot_report.py tests/test_iron_loss.py tests/test_loss_breakdown.py tests/test_windows_field_frame_pool.py -q
```

Changes to the reference collector or its source identity require a new output
directory. Committed checkpoint artifacts are verified before resume. Partial
collections cannot produce a complete analysis report. Raw evidence remains in
the output directory; it is not bundled into the application or the repository.

Method reference: David Meeker, [Rotating Losses in a Surface Mount Permanent
Magnet Motor](https://www.femm.info/doku/doku.php?id=spmloss), especially rotor
material coordinates, complete winding periods and mesh-noise sensitivity.

## Follow-up: fixed-mesh closure probe

The moving-air-gap option adds two circular boundaries wholly inside the free
air gap, with a Periodic Air Gap condition and an unmeshed band between them.
The geometry stays at its drawn zero pose. For every requested position the
collector reloads an unsolved baseline, sets the unwrapped inner boundary angle
and updates winding current densities. Each endpoint is solved independently;
the -360 degree angle is saved as -360, not replaced with zero or its solution.

This changes a reference-collection option only. The sealed E/F sources and
the application's existing field/loss calculation are unchanged.

```powershell
python -m tools.femm_reference.rotor_loss_pilot --motion periodic-air-gap --closure-only --out output/rotor-closure
python -m tools.rotor_closure_report output/rotor-closure
```

This probe collects exactly five fresh solves at 0, -3.75, -90, -360 and 0
native mechanical degrees. Its predeclared closure tolerances are 1e-6 T
maximum component error and 1e-7 T RMS component error. It verifies complete
triangular mesh coordinates/connectivity, raw rotor triangles, material query
locations, saved boundary angles, absent previous-solution seeds and artifact
hashes. A count of mesh elements alone is insufficient.

**Coordinate convention:** unlike remeshed exports, moving-air-gap exports are
in FEMM's fixed drawn rotor-material axes. The query positions must remain
fixed in those axes. They must not be rotated again as if they were moving
global coordinates. The history report now accepts this explicit representation
through the tested adapter. Mixed or missing frame declarations are rejected.
A five-pose closure probe is still rejected by the full-history analyser;
the closure check itself reports no loss watts.

The [closure results](benchmarks/rotor-closure-pilot-306-20261115.md) retain the
measured outcome and remaining limits. The original remeshing pilot is retained
unchanged. FEMM documents this method in [Rotor Motion using an (Anti)Periodic
Air Gap Boundary Condition](https://www.femm.info/wiki/RotorMotion).

## Follow-up: fixed-mesh full-turn history

The production sampler accepts the raw material-frame triangles and B without
another rotation. The independent direct-DFT oracle separately reads the raw
material-frame B components directly. Synthetic analytical checks and equivalent
global/material-frame histories verify the two representations give the same
loss, including both rotation directions, nonzero poses, DC bias and real time harmonics.

The analyser requires the complete registered angle list, explicit frame tags,
fresh base reloads, saved unwrapped boundary angles, identical full mesh hashes
and unchanged rotor integration cells. It checks that query locations stay
fixed in the drawn rotor axes and verifies independent endpoint closure.

```powershell
python -m tools.femm_reference.rotor_loss_pilot --motion periodic-air-gap --positions 96 --limit 1 --out output/rotor-fixed-history
# In two separate shells using the same pinned environment:
python -m tools.femm_reference.rotor_loss_pilot --motion periodic-air-gap --positions 96 --resume --shard 0/2 --out output/rotor-fixed-history
python -m tools.femm_reference.rotor_loss_pilot --motion periodic-air-gap --positions 96 --resume --shard 1/2 --out output/rotor-fixed-history
# After both workers finish, in a fresh process:
python -m tools.rotor_loss_pilot_report output/rotor-fixed-history
```

The 24/48/96 comparisons reuse the same full-turn data at integer strides. The
closure endpoint is excluded from each harmonic calculation. Mesh invariance
means the geometry stayed fixed during collection; spatial mesh convergence is
a separate gate. This remains one loaded SPM case, not the full release matrix.

## Follow-up: 192/384 angular refinement

Collect the 384-sample full-turn grid once. Its even-indexed positions form
the 192-sample grid and every fourth position forms the 96-sample grid. Every
position is independently solved, including both endpoints; earlier runs are
retained as reproduction controls. Motor, currents, speed, material law, mesh
and air-gap settings remain unchanged.

```powershell
python -m tools.femm_reference.rotor_loss_pilot --motion periodic-air-gap --positions 384 --limit 1 --out output/rotor-fixed-384
# In separate shells: run this command with --shard 0/4, 1/4, 2/4 and 3/4.
python -m tools.femm_reference.rotor_loss_pilot --motion periodic-air-gap --positions 384 --resume --shard 0/4 --out output/rotor-fixed-384
# After all four workers finish, in a fresh process:
python -m tools.rotor_loss_pilot_report output/rotor-fixed-384
```

The analyser reports 96/192/384 losses and both successive refinement gates.
All workers and the prior zero-angle preflight are separate owned FEMM
sessions; in the four-worker collection each worker reloads the unsolved base
at every assigned pose. Mesh identity and full-turn closure are checked again.
Spatial refinement and the multi-motor release matrix remain separate work.

## Follow-up: fixed-mesh spatial refinement at 384 samples

Use the verified normal-mesh 384-position history as the baseline, with a fresh
zero-angle reproduction control. Collect two further complete histories on
independently refined meshes. Within each history the full triangular mesh,
rotor integration cells and query points must stay fixed through all 385
independent solves. Integration cells may differ between mesh levels; each
level integrates its own physical rotor domain without mass renormalization.

The bounded study uses these explicit controls. Fine and very fine retain the
existing bulk and geometry-arc presets; their air-gap targets are overridden
to intermediate values to bound collection time. Moving-band segmentation is
refined separately from the bulk geometry's arc segmentation.

| Level | Bulk preset | Air-gap target mm | Moving-band arc step degrees |
|---|---|---:|---:|
| Normal | normal | 0.125 | 0.25 |
| Refined | fine | 0.100 | 0.20 |
| Further refined | very_fine | 0.080 | 0.16 |

```powershell
# Prepare each independent integration grid with one fresh zero-angle solve.
python -m tools.femm_reference.rotor_loss_pilot --motion periodic-air-gap --positions 384 --mesh fine --airgap-target-mm 0.1 --airgap-arc-step-deg 0.2 --limit 1 --out output/rotor-spatial/fine
python -m tools.femm_reference.rotor_loss_pilot --motion periodic-air-gap --positions 384 --mesh very_fine --airgap-target-mm 0.08 --airgap-arc-step-deg 0.16 --limit 1 --out output/rotor-spatial/very-fine
# In separate shells: fine shards 0/3, 1/3, 2/3; very-fine shards 0/5 through 4/5.
python -m tools.femm_reference.rotor_loss_pilot --motion periodic-air-gap --positions 384 --mesh fine --airgap-target-mm 0.1 --airgap-arc-step-deg 0.2 --resume --shard 0/3 --out output/rotor-spatial/fine
python -m tools.femm_reference.rotor_loss_pilot --motion periodic-air-gap --positions 384 --mesh very_fine --airgap-target-mm 0.08 --airgap-arc-step-deg 0.16 --resume --shard 0/5 --out output/rotor-spatial/very-fine
# After all workers finish, analyse in a fresh process. The baseline stays read-only.
python -m tools.rotor_spatial_report output/rotor-fixed-384 output/rotor-spatial/fine output/rotor-spatial/very-fine --out output/rotor-spatial/report
```

The spatial report verifies and reanalyses all three raw histories using the
same current sampler and independent DFT. It rejects changes to operating
point, angle grid, fixture, material law, reference binaries or unrelated
reference implementations. Actual saved moving-band arc settings are checked
against the protocol. Distinct mesh hashes, increasing total/core cell counts,
decreasing maximum rotor-cell area, and decreasing air-gap/arc targets are
required; element counts alone do not establish refinement.

At every mesh level, the 96/192/384 subsets recheck angular convergence,
reference agreement, closure and within-turn mesh invariance. Across meshes,
only the 384-position results are compared, with hysteresis, lamination eddy
and total tested separately in both calculations. Both successive mesh steps
must satisfy the predeclared max(5% of finer loss, 0.001 W) criterion. This is
a convergence diagnostic, not a Richardson error bound or measured accuracy.
The one-case numerical gates and the full release qualification remain
separate; the multi-motor matrix is not started by this command.
