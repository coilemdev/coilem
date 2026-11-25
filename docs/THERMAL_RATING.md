# Steady-state thermal coupling and the sampled torque rating (M3b)

This backend builds on M1 and the two-temperature maps. It is an experimental
estimate under the user's cooling assumptions, not a measured continuous
motor rating. Rotor and magnet heat remains incomplete. The winding and
end-winding limits use the selected insulation-class limit less the explicit
hotspot allowance. The magnet limit is the existing grade-table maximum;
it is not a demagnetisation safety verdict.

## Coupling

At each speed, peak current and current angle, start the winding at ambient
and the EM magnet temperature inside the solved brackets. Update winding DC
resistance and copper heat using R(T), and sample flux, torque and iron loss
from the Br-interpolated map. Hysteresis and eddy loss scale from the map's
reference speed with frequency and frequency squared, respectively. At zero
speed the steady iron heat is zero; the original map's nonzero reference
frequency remains only loss-record provenance.

Solve M1, relax winding and magnet temperatures, and repeat to a maximum node
update of 0.1 K by default. Default relaxation is 0.5 and iteration limit 50;
all three are recorded, together with every temperature update and residual.
No FEM is performed inside this loop. A user-set magnet temperature provides
an additional EM sensitivity case at the selected operating point; its EM
magnet temperature and M1's predicted magnet temperature are both retained.

Missing heat/material/cooling data, temperatures outside the Br brackets,
iteration exhaustion and sustained temperature growth are explicit unavailable
outcomes. Growth/runaway is a numerical diagnostic, not a proof of a global
thermal instability boundary. No bracket is silently extended or extrapolated.

## Rating search

At each speed, evaluate a bounded current/angle grid within the user's
continuous/peak cap and map coverage, followed by three local refinements.
Select the largest sampled torque satisfying peak phase voltage, current,
winding/end-winding and magnet-temperature limits. The closest normalized
constraint is reported. MTPA uses lower current as its torque tie-break;
least-loss uses lower copper plus stator-iron loss. This is a sampled,
locally refined search; it does not certify a global optimum or an exact
controller trajectory. The UI/report must retain that limitation.

An unavailable speed is retained with its reason. Cancellation retains explicit
unavailable entries for the remaining speeds, rather than silently truncating
a curve. The user magnet sensitivity does not replace the predicted-magnet
rating or claim its thermal temperatures are measured.

## Direct limiting-point verification

When a native solver is supplied, re-solve each final limiting point at its
converged magnet and winding temperatures, using the map's rotor sweep. This
occurs after the search, never inside fixed-point iteration. Registered
comparison bands are flux 1% of direct |lambda_dq| (1 micro-Wb floor), torque
1% (0.05 N m floor), voltage 1% (0.1 V floor), iron loss 5% (1 W floor), and
core-node temperature difference 2 K. These follow M3a's frozen bands.

A failed comparison keeps the output experimental and names the failed
quantity. A direct violation of voltage or temperature limits makes that speed
unavailable. Without a native solver the verification is NOT_COMPARED, never
an invented PASS. The full interpolation acceptance status/reason must also
travel with the rating; a passing interpolation check does not qualify M1.

Public controls, cancellation/progress, saved records and PDF/CSV integration
are provided in M4 (#23). FEMM conduction (#20) and bench evidence (#24) remain
separate qualification tracks.

## Native worked example

The search samples integer rpm (nearest integer, bounded by the entered maximum),
matching the native solver's unsigned-integer speed contract. A regression
checks both the reported grid and the final solver input type. In particular,
NumPy float speeds such as 3000.0 must not reach native JSON as floating point.

`benchmarks/thermal-v0.6/spm-rating-native.json`, kept in the private repository,
records an actual concentrated SPM example using the registered 20/80 C preview maps
at 0 and 3000 rpm. The explicit sensitivity cooling inputs are deliberately strong
(housing/end-space 1000, gap 500 W/m2 K), not measured. The entered current cap is
5 A peak, with 48 V bus; this is not a physical continuous-current qualification.

The record retains, for each sampled speed, the coupled and directly solved torque
and winding temperature and the direct check against every frozen limiting-point
band (flux components, voltage, torque, iron loss and propagated core
temperatures), together with iterations/residuals, source map keys, source SHA256,
native computation identity and inputs. This tests the coupling/direct-check path;
it does not replace the broader intermediate/off-grid map acceptance collection,
prove global optimality, or qualify cooling or magnet temperature.

Reproduce with the supported Python environment and PYTHONPATH at the checkout:

```
python -m tools.check_thermal_rating --maps-root /tmp/coilem-spm-temperature-check/maps --out /tmp/coilem-spm-rating.json
```

This resumes or computes the two endpoint maps before the search, then re-solves
the final points. Use a bounded solve cache when collecting alongside other jobs.
