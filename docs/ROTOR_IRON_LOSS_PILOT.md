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
- `sample_rotor_field`: transforms both mesh coordinates and vector fields into
  rotor coordinates. Only explicit `rotor_core`/`RotorCore` elements are accepted;
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
global coordinates. The existing global-frame loss report rejects these
exports explicitly. A tested coordinate adapter is required before a later
full-history loss comparison; this five-pose check reports no loss watts.

The [closure results](benchmarks/rotor-closure-pilot-306-20261115.md) retain the
measured outcome and remaining limits. The original remeshing pilot is retained
unchanged. FEMM documents this method in [Rotor Motion using an (Anti)Periodic
Air Gap Boundary Condition](https://www.femm.info/wiki/RotorMotion).
