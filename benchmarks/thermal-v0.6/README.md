# Thermal validation evidence

## Stored records

The protocols, gates, fixtures and transcribed published data in this folder are
public. The records they produce are generated measurements and are kept in the
private repository, where release qualification runs (see
[releasing](../../docs/RELEASING.md)): the `*-results.json` and `*-metrics.csv`
records, the `*-native.json` comparison and rating bundles and their
`*-recomputed.json` recomputations, `path-audit-initial.json`,
`rotor-heat-path-checks.json`, `ipm-interpolation-isolation.json`, the FEMM
outputs in `femm/`, `screenshots/`, and the write-ups that report them
(`*RESULTS*.md`, `THERMAL_PATH_AUDIT.md`, `ROTOR_HEAT_SCOPE.md`, and
`MEASURED_CLAIMS.md`, which keeps the measured statements taken out of the
public documents). They are not part of the public source or the wheel; tests
that compare against them skip where they are absent or are kept privately. Each section below names the command that regenerates
its records.

## Remaining-path audit

The heat-path audit (`python -m backend.benchmark_suite.thermal_path_audit`,
registered in `path-audit-fixtures.json`) checks the remaining winding, end-turn,
magnet and rating assumptions. Its record keeps every check, including any that
failed, recomputes the saved example point records and both native thermal
propagations, and directly rechecks the SPM worked rating at 0/3000 rpm. The
record and the original evidence are kept unchanged in the private repository.
Physical motor temperatures remain experimental; Windows and bench evidence are
pending.

## Analytical thermal verification

The independent [analytical protocol](ANALYTICAL_PROTOCOL.md) runs entirely on
the local machine without a motor, FEMM or EM jobs. Its default candidate,
`surface_mean_v2`, distinguishes slab means from both surface temperatures,
correcting the source-versus-transport error that the original
`legacy_mean_paths_v1` reduction exposed. The [root-cause analysis](ANALYTICAL_REDUCTION_FIX.md)
describes the derivation, production tooth/yoke integration and remaining scope.
The model-reduction comparisons are exact-equality diagnostics, not full-motor
error bounds. The JSON and CSV records of both candidates, which preserve every
comparison, failure and source identity, are kept in the private repository.

Run `python -m tools.check_thermal_analytical --out-dir /tmp/coilem-analytical-run`
from a source checkout, or `python -m backend.benchmark_suite.thermal_analytical`
from an installed package. The default is `surface_mean_v2`; use
`--candidate-model legacy_mean_paths_v1` to reproduce the original failures.
An overall FAIL exits 1. This suite and its
numerical tolerances are separate from every frozen FEMM, native and bench gate.
App outputs remain experimental. Registered inputs, references, cooling
assumptions and numerical tolerances were not tuned for the corrected candidate.

## Native temperature-map interpolation checks (M3a, issue 21)

> **Status:** the stored evidence for these checks, kept in the private
> repository, was collected before the outer-rotor network and the 0.5.9
> solver. The app ties it to the solver build and the thermal sources it was
> collected with and refuses it for any other, so a torque curve currently
> reports this check as "Not compared".
> `test_native_acceptance_requires_current_thermal_processing` is marked as an
> expected failure for that reason and will flag the day it passes again.
> Recollect the evidence once the thermal sources are frozen for a release; it
> takes two torque-speed maps per case.

This pre-registered **native interpolation** check is separate from the
thermal-conduction-0.6.0-1 FEMM heat-flow comparison (#20) and physical bench
qualification (#24). All derived thermal outputs remain experimental. Analytic
synthetic tests exercise the pipeline without being published as native evidence.

Each registered collection (concentrated SPM, 8 poles / 12 slots, and flat IPM,
8 poles / 12 slots) contains five full 35-point maps (including repeated
zero-current entries) and nine directly solved off-grid points: 154 actual
native jobs per case. Its bundle preserves the frozen registration and fixture
hashes, computation identity, endpoint maps, direct intermediate maps, off-grid
observations and every comparison metric, so each recorded verdict and metric
can be recomputed from it without further FEM solves. Both bundles are kept in
the private repository and are not packaged, so an installed app reports this
check as NOT_COMPARED. Where a bundle is present, application consumers require
matching map identities and current grids and preserve experimental thermal
status.

The off-grid comparisons exercise both temperature interpolation and the
preview map's current/angle interpolation. Where a bundle is present,
`python -m tools.isolate_temperature_map_error BUNDLE` separates the two
contributions at its off-grid points without new FEM solves. A YELLOW or FAIL
comparison stays visible to matching coupled ratings, which remain
experimental; the bands and the interpolation algorithm are never changed in
response to it.

Interpolation checks and final rating-point verification load their tolerances
from the same frozen `map-interpolation-gates.json` registration. Direct rating
verification requires the PASS band; a YELLOW-sized direct error still fails
that verification. No acceptance threshold changed during this refactor.

These checks apply to the registered designs, grids, limits and numerical
settings. They do not qualify cooling, homogenization, hotspots, rotor heat,
physical temperatures or efficiency.

## Frozen collection contract

`map-interpolation-gates.json` pins a registered concentrated SPM and FSAE
flat-IPM fixture by SHA-256. The fixtures are unchanged. Preview maps cover
20 and 80 C, with direct intermediate maps at 35, 50 and 65 C. Maximum current
is twice each fixture's baseline (40/100 A peak). At each intermediate
temperature collect all map grid points and three additional off-grid points:
(current fraction, gamma) = (0.375, 22.5), (0.875, 52.5), (0.875, 82.5).
The fixed 48 V bus and 12,000 rpm search must exercise field weakening;
otherwise the check remains NOT_COMPARED instead of passing vacuously.

PASS requires every supplied metric within `max(relative*reference, floor)`.
YELLOW extends that band by two; a larger error is FAIL. Flux components use
reference |lambda_dq| as the denominator, not the small component itself.

| Quantity | Relative PASS | Absolute floor |
| --- | ---: | ---: |
| lambda_d, lambda_q | 1% of reference flux norm | 1 micro-Wb |
| torque | 1% | 0.05 N m |
| total stator iron loss | 5% | 1 W |
| phase peak voltage | 1% | 0.1 V |
| winding/end-winding/tooth/yoke/housing temperature difference | — | 2 K |
| base speed and feasible maximum speed | 2% | 50 rpm |

Voltage feasibility at the reference speed must agree exactly for each point.
A disagreement is FAIL, including one near the boundary; it is not silently
accepted by the voltage-error band. Full direct maps additionally check base
speed and the feasible maximum speed. Missing temperatures, off-grid points,
iron loss, thermal comparisons, direct maps, or field-weakening coverage leave
NOT_COMPARED. A known failed comparison remains FAIL even if other evidence
is missing. Every verdict preserves experimental output status.

The thermal comparison propagates direct and interpolated iron losses through
**the same unqualified M1 network**, at fixed winding-temperature resistance.
It checks interpolation error propagation, not accuracy of cooling, material
conductivities, hotspot estimates, or the EM-thermal fixed point. The registered
cooling/contact values are explicit sensitivity assumptions, not measurements.
The directly re-solved final limiting point belongs to the rating search in
M3b (#22); this issue does not pretend to validate a rating that does not yet
exist.

## Run from a source checkout

Use the supported Python environment, set PYTHONPATH to this checkout, and
keep output outside the publication tree. Without `--collect`, this prints
NOT_COMPARED and does no FEM work. This is a collection dry run; it does not
inspect the stored bundles:

```sh
python -m tools.check_temperature_maps --case spm_8p12s_concentrated
```

To collect and judge one registered case:

```sh
python -m tools.check_temperature_maps --case spm_8p12s_concentrated --collect --out /tmp/coilem-spm-temperature-check
python -m tools.check_temperature_maps --case ipm_flat_8p12s_fsae --collect --out /tmp/coilem-ipm-temperature-check
```

Each case uses five preview maps (145 map jobs) plus nine off-grid
solves: 154 ordinary native jobs. Maps persist under `out/maps`, so completed
map points resume; the nine extra points are re-solved on a rerun. The bundle
records the registration hash, fixture hash, both endpoint maps, all direct
maps/off-grid points, source computation keys, metrics and the verdict.
A FAIL exits nonzero. Keep measured results either way, retaining hashes, in
the private repository; never adjust the bands in response to the observed error.

## Derived-map provenance and limitations

`TemperatureMapBracket` checks the two maps against the current design,
numerical settings and installed computation identity; temperature is the
only permitted physical difference. Both maps must be complete and use the
same grids, speed and torque method. Grades without cited Br(T) coefficients
are rejected before starting either map.

`interpolate_temperature_map` interpolates flux, torque and hysteresis/eddy
loss in Br scale. It never extrapolates: a caller must explicitly extend the
bracket with solved data or report unsupported. Interpolated maps have their
own derived key, separate from a solved map at the same temperature, and retain
both source keys. No fake convergence or torque-ripple result is supplied at
an unsolved temperature. A small cache-resume metadata fix keeps the map's
rotor-position count when every point was reused.

Hotter magnets can reduce torque and improve voltage headroom simultaneously.
Consumers must evaluate both constraints at the relevant temperature; neither
endpoint is declared universally conservative. Saturation, iron loss and
bridge leakage can be nonlinear in Br. The linear interpolation and any
coupled rating remain experimental even when these numerical checks PASS.

## Coupled-rating reporting boundaries

Current limits identify their binding source: drive continuous, drive peak,
map domain, or tied sources. Raising a drive limit cannot extend the solved map.
The coupling loop's temporary `IronLoss` adapter carries placeholder mass and
validation caps solely to satisfy the existing loss-allocation input contract.
Only its watt totals feed the network. The adapter is not part of `CoupledPoint`
or `ThermalResult`, frozen rating records, or their UI/PDF/CSV exports; no design
mass or material qualification may be inferred from it. A regression checks that
these placeholder fields are absent from the complete serialized result.

The growth/runaway guard is an engineering heuristic: after iteration six,
three consecutive residual increases above 1.2 times the previous residual
trigger failure; a temperature above 1000 C triggers immediately. This is not
an analytic stability proof. Iteration failure and out-of-bracket temperatures
remain separately reported unavailable outcomes.

## Supplied-run trust boundary

The thermal point endpoint deliberately follows the local run-report flow:
`source.summary` is supplied by the client, its iron-loss record and requested
config are validated, and the exact numerical source/config/inputs are frozen.
This permits estimates from restored run results without another solve. Freezing
prevents later edits from silently changing that analysis; it does not attest
that the supplied torque/loss summary was solved for that config. The point
card and saved-result notes disclose this limit, and PDF/CSV retain the note.
The rating route independently obtains its maps through the identity-bound store.
Native acceptance is fixture/grid-exact; NOT_COMPARED means matching evidence
is absent, not that a comparison failed.

## Rotor heat-transfer scope

The current UI exposes the previously hidden heat-transfer temperatures without
a declared-frequency gate. Internally generated rotor/magnet losses remain
unknown; supplied extra heat is a recorded scenario assumption. The claim
boundary, two saved-point comparisons and fresh processing-identified evidence
are in `ROTOR_HEAT_SCOPE.md`, kept in the private repository. Historical records
and evidence remain unchanged.
