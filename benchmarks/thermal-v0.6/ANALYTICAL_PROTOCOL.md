# Analytical thermal protocol 0.6.0-1

This suite checks idealized, steady-state problems without a motor, FEMM or EM
solve. It is independent of the frozen conduction, native interpolation and
physical bench registrations. It never changes app qualification or calibration.

The experiment registration remains fixed; candidate implementations are named
separately. The default `surface_mean_v2` uses explicit mean/surface slab elements.
`--candidate-model legacy_mean_paths_v1` retains the original diagnostic adapters
described below and reproduces their original failures. See
[root cause and correction](ANALYTICAL_REDUCTION_FIX.md) for the new element and
its production scope. Both use the same independent references and tolerances.

`analytical-fixtures.json` freezes 23 cases and numerical equality tolerances.
Its SHA-256 is pinned by the runner before the initial benchmark execution.
Changing inputs or criteria requires a new protocol version. The registered
limits are numerical floors (1e-8 K, 1e-8 W, 1e-10 dimensionless) with relative
tolerance 1e-10, not motor accuracy bands. Temperature scaling uses reference rise
above the case datum, never absolute Celsius. There is no YELLOW band in this
exact-solution protocol. Existing FEMM/bench bands remain untouched.

## Two distinct scopes

- **solver**: exact thermal circuits, isolated source-mean slabs, a cylindrical
  shell, scalar and two-winding copper feedback, and required rejection cases.
  These exercise production `solve_network`, `slab_mean_resistance`,
  `cylindrical_resistance` and `solve_copper_feedback`.
- **model_reduction**: chained one-face source-mean resistances and a two-face
  extension compared with exact 1D heat equations. These deliberately expose
  the limits of using a generated-heat average resistance as a general transport
  resistance. A disagreement is a retained FAIL, even when global energy is
  balanced. A passing scalar solver must not conceal a failed reduction.

The layered adapter isolates the one-face reduction used by the current
tooth/yoke paths. Its winding/teeth/yoke names are labels for planar slabs, not
actual motor geometry. It does not execute `build_network` or validate its IR
areas, cylindrical approximations, two-sided slot paths or all eleven nodes.
The asymmetric two-face adapter is a diagnostic extension of the symmetric
slab formula, not an asserted model of a shipped motor heat path. Its failure
would constrain future use of that approximation, not establish a new app bug.
This explicit scope prevents these fixtures from claiming full-motor accuracy.

## Independent reference derivations

`thermal_analytical_reference.py` imports only standard-library math and data
containers. It does not call production thermal functions, matrix assembly,
linear solvers or eigensolvers. Numerical candidate values never enter a
reference calculation. Tests separately anchor interfaces, means, boundary
fluxes and copper balances with worked scalar examples. Saved coilEM outputs
are evidence of a run, not the reference for the next run.

### Passive paths and boundary flows

For a slab with constant conductivity k, length L and area A, surface-to-surface
resistance is L/(k*A). Series and parallel circuit references follow heat
conservation and temperature continuity. The cylindrical shell integrates
`dT/dr = -Q/(2*pi*k*length*r)` to give
`T_inner-T_outer = Q*log(r_outer/r_inner)/(2*pi*k*length)`.
The inner cylinder value is a surface temperature, not a volume mean.

For one node between two boundaries with resistances R1, R2 and source Q:
`T = (Q*R1*R2 + T1*R2 + T2*R1)/(R1+R2)`.
Individual rejection powers are `(T-T1)/R1` and `(T-T2)/R2`. A negative value
means that boundary supplies heat. Summing only absolute fluxes would be wrong.
The zero-source case reaches ambient; an isolated unheated node must be rejected
because it has no determined steady temperature.

These conduction principles are described in the
[DOE heat-transfer handbook](https://www.energy.gov/documents/doe-hdbk-1012-92vol2).
The [DOE MFiX slab benchmark](https://mfix.netl.doe.gov/doc/vvuq-manual/main/html/fluid/fld-02.html)
is an example of verification against a closed-form boundary-value problem.
The formulas and calculations below are independently derived for this suite.

### Uniformly heated slab

Use `k*T'' = -g`, where `g=Q/(A*L)` and k and g are constant.

- Both faces at Tb: `T(x)-Tb = g*x*(L-x)/(2*k)`; spatial averaging gives
  `T_mean-Tb = g*L^2/(12*k)`.
- Left face insulated, right face at Tb:
  `T(x)-Tb = g*(L^2-x^2)/(2*k)`; averaging gives `g*L^2/(3*k)`.
- Unequal face temperatures Tl, Tr: add the linear no-source solution to the
  first expression. `T_mean=(Tl+Tr)/2+g*L^2/(12*k)`.
  Outward heat flows are `Q_left=Q/2+k*A*(Tr-Tl)/L` and `Q_right=Q-Q_left`.

The split-boundary candidate uses two branches of twice the symmetric
source-mean resistance, preserving their original parallel equivalent.
Compare both mean temperature and each face's heat flow. A matching average and
global balance alone cannot establish the correct flux distribution.

### Layered source and transport problem

The left outer surface is insulated. The right surface rejects all heat through
an explicit resistance to ambient. Each planar layer has constant k and A and
uniform generation Q_i; interfaces have optional contact resistances (also
representing a source-free liner of known L/(k*A)). There is no spreading,
radiation, contact-temperature dependence or axial bypass in this idealization.

Let `F_i=sum(Q_j for j<i)` be heat arriving from inner layers and
`r_i=L_i/(k_i*A)`. Integrating the heat equation gives:

```
T_left,i - T_right,i = (F_i + Q_i/2)*r_i
T_mean,i - T_right,i = (F_i/2 + Q_i/3)*r_i
Q_out,i = F_i + Q_i
```

Start at `T_right,last = Ta + sum(Q_i)*R_outer`, then work inward. An interface
temperature jump is `Q_out,i * R_contact,i`. Thus reference temperatures follow
scalar integrations and boundary continuity; no thermal-network linear solver
is used. Reference interface temperatures and incoming/outgoing watts are
retained in the JSON bundle.

The legacy candidate chain instead links successive mean nodes with
`slab_mean_resistance(..., two_sided=False) + R_contact`, and the last mean to
ambient with the mean resistance plus R_outer. This is the documented reduced
source-mean chaining, not an exact multi-terminal representation.
Winding-only, iron-only, mixed, zero-source and single-layer controls distinguish
transported from internally generated heat. These cases measure the limitation;
the original result remains available alongside the corrected candidate.

Worked winding-only anchor: full layer resistances are 1, 0.1 and 0.05 K/W;
contacts are 0.1 and 0.05 K/W; outer resistance is 1 K/W. At 25 C ambient with
10 W generated in the first layer only, exact means are 41.333333 C winding,
36.5 C teeth and 35.25 C yoke. The outer yoke surface is 35 C. These values come
from integration, not saved production output.

### Fixed-current copper feedback

Q20 is the total source at 20 C (e.g. `3*I_rms^2*R_phase,20` for balanced phase
currents). With thermal resistance R, coefficient alpha and ambient Ta:

```
T-Ta = R*Q20*(1+alpha*(Ta-20))/(1-alpha*Q20*R)
```

A positive-capacitance version of this scalar circuit is stable only for
`alpha*Q20*R < 1`. Critical and supercritical problems must be rejected, even
when algebraic inversion returns a finite negative-temperature branch.
Zero current and alpha=0 are separately registered controls. These are exact
circuit checks at fixed current and constant thermal properties; no transient
time prediction or cooling coefficient is validated.

The two-winding problem gives each source its own temperature and resistance
to a shared housing. The housing has a fixed additional source Qh and resistance
Rh to ambient. With x=Tw-20 and y=Te-20, eliminate the housing to form:

```
(1-alpha*(Rh+Rw)*Qw20)*x - alpha*Rh*Qe20*y
    = Ta-20 + Rh*(Qw20+Qe20+Qh) + Rw*Qw20
-alpha*Rh*Qw20*x + (1-alpha*(Rh+Re)*Qe20)*y
    = Ta-20 + Rh*(Qw20+Qe20+Qh) + Re*Qe20
```

The reference uses Cramer's rule. Stability uses the explicit larger root of
the two-by-two heat-response matrix's characteristic quadratic. This detects
shared-path instability even when each individual self-feedback is below one.
The production candidate uses its full conductance solve and spectral check.
Reported watts must match the resolved temperatures and boundary rejection.

## Run and preserve evidence

From a checkout, set PYTHONPATH to that checkout and use its supported Python:

```
python -m tools.check_thermal_analytical --out-dir /tmp/coilem-analytical-run
```

The installed-package equivalent is:

```
python -m backend.benchmark_suite.thermal_analytical --out-dir /tmp/coilem-analytical-run
```

`--case` can be repeated to select a labelled subset; no empty/unknown/duplicate
selection can pass. A new output directory is required, preserving earlier
evidence. JSON retains every case, parameters, exact references, candidate
outputs, numerical tolerances, errors, rejection reasons and source hashes.
CSV includes every numerical comparison and non-numerical rejection outcome.
Markdown separates solver verification from model-reduction discrepancies.
Any failed case makes the overall result FAIL and the command exit 1, even if
that discrepancy is already understood. Unit tests can pass while correctly
checking that the benchmark reports FAIL; neither is a physical qualification.

Register future model changes separately as needed and preserve the original
result. Never enlarge numerical tolerances to conceal reduction error.
The physical motor's convection, interfaces, conductivity/homogenization,
hotspots, rotor heat, rotation and continuous torque remain outside this suite.
