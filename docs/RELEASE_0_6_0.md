# 0.6.0 implementation candidate: steady-state thermal estimates

This candidate is stacked on the 0.5.0 release PRs. It is not a release sign-off.
The 0.5.0 protocol 1.6.0 Windows FEMM run and freeze rerun are still prerequisites;
the existing 21 physics-hash guard failures have not been re-pinned here.

## Implemented work

- #18 / PR #27: map cache computation identity, including physics/solver and loss
  model identity; unavailable identity fails before claiming the solve lane.
- #19 / PR #28: geometry-derived thermal network, explicit cooling/contact/material
  assumptions, heat destinations, hand-network gates, limits and calibration provenance.
- #21 / PR #29: two-temperature maps, no extrapolation, frozen intermediate and
  off-grid acceptance bands, resumable native collection and identity-bound records.
- #22 / PR #30: resistance/magnet-temperature fixed-point coupling, sampled torque
  search, explicit failures, convergence evidence and direct native limiting-point
  checks. A fresh SPM worked-example rerun at 0/3000 rpm uses the audited heat
  paths and separate active/end copper feedback, with the original strong
  assumed cooling and 5 A cap. The historical rating is preserved separately.
- #23 / PR #31: explicit thermal inputs, Thermal card, separately styled thermal
  curve and frozen PDF/CSV exports with statuses, reasons and provenance.
- #20: separate conduction registration and FEMM request, area-weighted rise/mesh
  gate; see [Windows request](../benchmarks/thermal-v0.6/FEMM_REQUEST.md). Also
  includes an independent [analytical protocol](../benchmarks/thermal-v0.6/ANALYTICAL_PROTOCOL.md)
  for exact circuits, conduction primitives, copper feedback and reduction diagnostics.
- #24: separated calibration/held-out DC bench protocol and gate; see
  [bench protocol](../benchmarks/thermal-v0.6/BENCH_PROTOCOL.md).

## Evidence and remaining owner work

The result records and write-ups named in this section are generated
measurements, kept in the private repository (see [releasing](RELEASING.md)).

- The corrected `surface_mean_v2` analytical candidate is run with the original
  registered inputs, independent references and tolerances. Its results preserve
  every comparison and source identity. The original failed evidence remains
  unchanged.
  The failures came from treating a generated-heat mean resistance as a general
  transport path. Distinct slab means and surface ports correct the layered
  temperature and unequal-boundary flow errors. The production tooth/yoke paths
  use the corrected elements, including the bore and outer-stator surfaces.
  [Root cause and scope](../benchmarks/thermal-v0.6/ANALYTICAL_REDUCTION_FIX.md)
  document remaining geometry, side-heat and cooling assumptions. These checks
  do not establish physical motor error bounds or qualify thermal outputs.
  Point and rating records identify their thermal processing separately from EM.
- The remaining-path audit adds further checks. It corrects the missing end-arc axial
  resistance, inconsistent end-bundle geometry/cooling, magnet mean resistance
  and shared-temperature copper assumption in ratings. Its reference mesh
  checks, including a failed first attempt, are preserved. The local point
  records were recomputed without replacement. No physical calibration exists to
  refit. Housing labels identify the outer-surface proxy; other geometry/cooling
  assumptions remain experimental.
- Both registered native interpolation collections are complete. They are kept
  in the private repository and are not packaged, so an installed app reports
  the native check as NOT_COMPARED. Both EM bundles remain unchanged. Thermal
  propagation was recomputed with the audited model. Runtime acceptance
  requires matching thermal-processing hashes, source-bundle identity and grids.
  The fresh comparisons check interpolation-error propagation, not physical heat
  paths. Both historical and recomputed evidence are retained.
- The off-grid flux comparisons combine temperature and current/angle
  interpolation. `tools.isolate_temperature_map_error` separates the two
  contributions from a saved bundle; see the thermal benchmark README. The
  bands and algorithm are unchanged; matching coupled ratings preserve the
  acceptance evidence and remain experimental.
- Native interpolation collection is computationally expensive. Its registration
  and commands live in [thermal-v0.6](../benchmarks/thermal-v0.6/README.md); its
  measured evidence is kept in the private repository. Preserve failed metrics and
  computation identities; do not widen bands to obtain a pass. A missing or
  incompatible acceptance record is NOT_COMPARED, and ratings remain experimental.
- The new conduction cases remain NOT_COMPARED until the owner's Windows heat-flow
  bundle arrives. Export and freeze a corrected `surface_mean_v2` request before
  running it. The exporter retains `legacy_mean_paths_v1` for existing owner runs;
  identities prevent old bundles from being relabelled as corrected comparisons.
  Physical problems and all frozen bands are unchanged. A code-to-code PASS
  cannot qualify uncertain physical cooling.
- The owner still needs to choose/register the actual bench motor, cooling,
  equipment, sensors, uncertainties and timeline before collection. Proposed heat
  levels are not approved levels for an unknown motor. No physical DC measurements
  have been fabricated or entered; the default bench registration is pending.
- A passing physical DC gate qualifies only the exact motor/cooling experiment's
  average winding-to-ambient paths. Importing approved physical evidence into saved
  app analyses can follow in 0.6.x once the motor is registered and tested. A
  rotating experiment is required for any speed-dependent thermal qualification.

Every app thermal output remains experimental or explicitly unavailable. Node
averages are not hotspots. Rotor/magnet eddy heat is absent; rotor and magnet
estimates remain experimental regardless of DC bench evidence. A user-entered
single calibration multiplier does not identify several uncertain heat paths.
Solve includes a Thermal setup section with an explicitly labelled still-air
starter (25 C ambient, class F, 15 K hotspot allowance). Its example coefficients
and construction values are documented in MATERIALS.md and recorded in results;
they are neither measured nor guaranteed conservative. Forced-air/liquid modes
require custom coefficients. Existing browser drafts are preserved. The torque search is sampled with local
refinement, not a certified global maximum or a validated continuous rating.

## Implementation decisions for owner review

The owner authorized finishing the implementation without waiting for feedback.
These choices keep the candidate usable while making assumptions visible:

| Open decision | Implemented choice | Reason and review boundary |
| --- | --- | --- |
| Hotspot allowance | Editable 15 K illustrative starter, recorded with the result | An example assumption, not an established hotspot allowance for the motor; review before use. |
| Cooling presets | Labelled still-air starter; forced-air and liquid-jacket coefficients require custom entry | Starter values make exploration accessible. Cooling performance still depends on the actual installation; changing mode clears coefficients and source. |
| Insulation limits | Offer A/B/F/H at 105/130/155/180 C, reduced by the entered hotspot allowance | These are thermal-class labels, not qualification of the motor's insulation system. |
| Mechanical heat destination | Require an explicit bearings/housing/rotor split summing to one whenever mechanical loss is nonzero | A default allocation would hide an unsupported heat-path assumption. |
| Rotor/magnet heat scope | Show transferred-heat estimates, separately record supplied additional/mechanical heat, and disclose unmodelled internal losses | Owner requested visible transferred heating with the missing contribution explicit. Zero supplied heat is an omission, not zero physical loss. Legacy frequency declarations are ignored on recomputation; no safe frequency range is claimed. |
| Calibration | One multiplier with measurement, operating-point and cooling provenance; independent validation remains separate | Fitting alone cannot qualify the model or identify multiple uncertain paths. |
| Bench motor and equipment | Leave registration pending; provide the protocol, input format and gate | The actual motor, available equipment and measurements cannot be inferred from the repository. No hardware has been purchased or measurements invented. |
| Optional reverse-field screening (#25) | Defer it | It is independent of the agreed core thermal scope and needs its own field/mesh validation. |

Remaining external inputs are the owner's Windows FEMM results (including the
0.5.0 freeze prerequisites) and the registered physical bench experiment. Missing
evidence stays NOT_COMPARED. Native interpolation results, including any failed
bands, must be recorded as measured; they do not substitute for either external
track. No release merge or qualification sign-off is implied by completing the
implementation PRs.

## Deliberately deferred

Optional #25 reverse-field screening is not part of this core thermal stack.
Transient overload, demagnetization safety, 3D/Elmer, AC copper loss, magnet eddy
loss, more steels, outrunners, sweeps and two-layer winding qualification remain
out of scope. There is no safety verdict or release qualification implied by
these numerical examples.

## Rotor heat-transfer display follow-up

The motor visual now includes rotor, magnet, air-gap, end-space and bearing
estimates without an arbitrary frequency gate. All numerical paths and prior
available temperatures are unchanged. Saved old results remain immutable;
recompute the thermal point to see the new scope and values. Invalid/unstable
solutions still withhold temperatures. Extra heat remains an explicit scenario
input, and coupled-rating margins apply only to the supplied heat assumptions.
The selected SPM/IPM comparisons and fresh processing-identified evidence are
in `ROTOR_HEAT_SCOPE.md`, kept in the private repository with the recomputed
analytical, path-audit, native-propagation and native rating evidence.
Physical validation remains pending.
