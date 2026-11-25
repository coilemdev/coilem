# Analytical heat-path failures: cause and correction

The `surface_mean_v2` candidate corrects the reduction behind the original
failures of the unchanged `thermal-analytical-0.6.0-1` registration. The
original `legacy_mean_paths_v1` result is in `analytical-results.json`,
`analytical-metrics.csv` and `ANALYTICAL_RESULTS.md`. Those files have not been
replaced. New evidence is in `analytical-surface-mean-results.json`,
`analytical-surface-mean-metrics.csv` and `ANALYTICAL_SURFACE_MEAN_RESULTS.md`.
All six records are kept in the private repository.
Inputs, independent references and numerical tolerances are unchanged.

## Root cause

The linear solver correctly solved the network it was given. The faulty step
was constructing a general heat-transport network from a special-case
generated-heat mean resistance.

For a slab with full surface-to-surface resistance `R=L/(k*A)`, the resistance
from its mean temperature to one cooled face is `R/3` only when the other face
is insulated and the heat is generated uniformly inside that slab. With heat
`F` entering from another layer and additional heat `Q` generated inside it:

```
T_left - T_right = (F + Q/2)*R
T_mean - T_right = (F/2 + Q/3)*R
```

The old chain used `R/3` between consecutive mean nodes. That discarded both
the transported-heat contribution and the distinction between an adjoining
surface and a material average. This caused the layered failures.

The unequal-boundary diagnostic used two `R/6` branches from the mean to the
faces. This preserves the symmetric generated-heat response but implies a
surface-to-surface resistance `R/3`, instead of `R`. With `R=1 K/W`, a 20 K
boundary difference and 12 W generated heat, that produces boundary flows of
66/-54 W instead of 26/-14 W. The mean is still 31 C and both flow sums are
12 W. Correct average temperature and global balance did not detect the error.

## Exact planar slab element

The corrected element retains three distinct temperatures: spatial mean `Tm`
and surfaces `Ta`, `Tb`. Direct integration of the steady conduction equation
with constant conductivity, area and uniform generation gives:

```
Tm = (Ta + Tb)/2 + Q*R/12
Qa_out = Q/2 + (Tb - Ta)/R
Qb_out = Q/2 + (Ta - Tb)/R
```

Eliminate Q and assemble the terminal balance in `(mean, face a, face b)` order:

```
        1       [ 12  -6  -6 ]
G_slab = -  *   [ -6   4   2 ]
        R       [ -6   2   4 ]
```

The mean row equals the uniformly distributed source. Each face row is the
heat entering the slab at that face, so boundary rejection is its negative.
The row sums vanish, preserving energy conservation and ambient translation.
The eigenvalues are `0, 2/R, 18/R`; the element is positive semidefinite.
Its positive face-to-face off-diagonal must not be interpreted as an ordinary
negative-resistance link. `ThermalLink` still requires positive resistance;
`ThermalSlab` is assembled as a complete three-terminal element.

Connecting a face to another layer or contact preserves surface temperature
and flux continuity. An unconnected exterior face is an insulated unknown,
not an invented mean-temperature boundary. Fixed-temperature ports can have
signed heat flow, including heat supplied from a hotter boundary.

The governing heat equation and outward-flux boundary convention follow the
[INL MOOSE heat-conduction formulation](https://mooseframework.inl.gov/getting_started/examples_and_tutorials/tutorial03_verification/step01_heat_conduction.html).
The matrix and references above are independently derived for this idealized
constant-property slab; this is not a claim of external motor validation.

## Production integration and remaining approximations

The production tooth and yoke paths now use slab means plus bore,
tooth/yoke-interface and outer-stator surface ports. The tooth and yoke share
the interface surface. Bore convection attaches to the bore surface; the
contact and unheated cylindrical housing attach to the outer surface. Internal
surface temperatures remain in the serialized network, not in the eleven
component-average result rows or hottest-material headline.

The existing slot-to-tooth path still assumes equal tooth-wall temperatures
and distributes its side heat at the tooth mean. Tooth/yoke geometry remains a
planar aggregate with constant cross-section; the yoke uses the outer
circumference area. Axial/end-winding paths, material homogenization and cooling
coefficients remain reduced assumptions. These are not resolved 2D gradients.
Passing the planar fixtures does not establish an error bound for the motor.

All resistances, including full slab R, receive the same recorded calibration
multiplier. Copper feedback uses the assembled conductance matrix and the
separate winding averages. The positive-definite cooling/stability criterion
is retained; no fitted coefficient or looser stability limit was introduced.
Both point and rating records now carry thermal-processing source identities
separately from their unchanged electromagnetic map identities. Existing saved
records retain their original numbers and provenance.

A saved SPM point (30 A rms / 2400 rpm / 25 C ambient) recomputed before and
after the correction, with identical cooling, loss and material assumptions and
copper feedback, isolates the effect of this correction; that comparison is kept
in the private repository. The previous implementation reproduces the frozen
saved point before the comparison. Neither result is a measured motor
temperature. Rotor-group outputs remain unavailable under the same
missing-frequency assumption. The correction does not remove the need to
establish realistic cooling and material properties.

## Evidence, compatibility and next validation

- The exact same 23 registered inputs and references are run for both named
  candidates. `--candidate-model legacy_mean_paths_v1` reproduces the original
  failures; the default is `surface_mean_v2`. Reports name the model.
- Tests also cover pure boundary-driven transport, reversed boundary gradients,
  insulated surfaces, varied layer sources/geometry/contacts, copper feedback
  with slab ports, instability, and the production radial path's independently
  integrated isolated limit. Internal ports do not leak into average outputs.
- The FEMM exporter defaults to the corrected model and gives it a new request
  identity and source hashes. `--candidate-model legacy_mean_paths_v1` preserves
  the original request schema and identities for existing owner runs. Old bundles
  cannot be relabelled as comparisons of the corrected model.
- No conduction registration, mesh criterion, acceptance band, native measured
  bundle or guarded EM source was changed. The Windows comparison remains
  NOT_COMPARED until matching reference data arrives. Export and freeze a new
  corrected request before its run; the CLI refuses to overwrite an old request.
- Physical motor temperatures, hotspots, rotor loss and continuous ratings remain
  experimental. The analytical correction is not bench qualification.
