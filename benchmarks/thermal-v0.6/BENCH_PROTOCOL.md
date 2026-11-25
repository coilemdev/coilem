# DC thermal bench protocol 0.6.0-1

**Owner decisions pending:** actual motor, exact geometry and winding record,
cooling arrangement, supply, sensors, instrument uncertainties and schedule.
`bench-gate.json` freezes candidate tolerances and point roles now. Its
`owner_registration` is null: the shipped gate is NOT_COMPARED. Before any real
run, copy that registration, fill exact identities and heat levels suitable for
the selected motor, approve and archive its hash. Do not collect data before
freezing that motor-specific registration. Any later protocol change needs a new
version and new held-out data. The example 10/15/20/25 W levels are a proposed
small-motor design, not an instruction to apply those watts to an unknown motor.

## Setup and observations

Lock the rotor at a recorded angle. Use a current-limited DC supply, isolated
voltage/current measurements, four-wire resistance measurement and logging.
Record serial numbers, calibration dates, uncertainty budgets, mounting/fixture,
orientation, airflow/coolant flow and temperature, housing finish and ambient.
Apply suitable independent thermal protection selected for the actual bench.
Keep the same terminals/connection for cold/hot resistance. Determine lead and
contact resistance independently at each temperature and subtract it; a four-wire
measurement still needs a stated correction (possibly measured zero).

For a star winding, either energize two terminals (R_line=2 R_phase and
P=I_line^2 R_line) or regulate phase currents (Ia,I b,I c)=(I,-I/2,-I/2), giving
P=1.5 I^2 R_phase. Document which is used; do not confuse line and peak sinusoidal
phase current. A DC pattern does not distribute slot heat exactly like balanced
rotation. Record the actual per-slot source pattern, or restrict the claim to
its average winding-to-ambient equivalent. Match predicted and measured source
heat within 3%. Isolate winding copper heat: no iron or mechanical source at DC.
Use terminal V*I less measured lead/contact dissipation and cross-check I²R.

Cold-soak until winding/housing/ambient agree within their uncertainty. Measure
cold winding temperature and resistance. Log voltage/current, ambient (or coolant),
housing at several circumferential points and end winding where accessible.
Sensors are diagnostic; the qualification metric is **average winding by
resistance rise**, not the hottest sensor. Wait until drift <=0.05 K/min over a
recorded final 20 min window, with ambient stable within 0.5 K. Record sample
interval, window data and drift fit, not just an operator assertion. After power
off, extrapolate promptly measured winding resistance back to shutoff time, or
use a validated in-situ method; include cooling-delay error in uncertainty.

Copper is the only initially registered conductor, alpha20=0.00393/K as in M1's
resistance model (engineering coefficient). With corrected resistances:

```
T_hot = 20 + ((R_hot / R_cold) * (1 + alpha20 * (T_cold - 20)) - 1) / alpha20
```

Do not use 1/alpha20 with an arbitrary cold temperature without this correction.
Propagate cold-temperature, resistance ratio, lead correction and timing errors;
include gradients and ambient drift. Report expanded winding uncertainty <=2 K
with coverage factor and method; uncertainty is added to error, not to tolerance.
If the budget is larger, the registered gate cannot pass.

## Calibration is separate from validation

One frozen calibration level (10 W proposed) sets the single positive resistance
multiplier. Three held-out levels (15/20/25 W proposed) judge it. Repeat each at
least three times after independent cold soaks; preserve individual traces and
report a predeclared repeat aggregation plus repeatability in uncertainty. No
validation point may be reused for fitting or selected away after seeing errors.
If one level is unsafe or unreachable, register an amended future experiment;
the incomplete existing result stays NOT_COMPARED or is rejected as incomplete.

**Before any measurements are collected**, freeze the uncalibrated M1 model,
geometry, cooling, heat distribution and predicted rises for every registered
level, with zero iron/mechanical heat. Archive these predictions and the source
code/config hashes under `prediction_identity` in the owner registration.
For measured heat or ambient that differs slightly from its nominal target,
pre-register the linear normalization rule and active/end rise per watt as well:
`predicted_C = measured_ambient_C + frozen_rise_per_W * measured_copper_W`.
Only measured heat and ambient may enter this frozen rule; measured winding
temperatures must not tune predictions, paths, coefficients or geometry. Heat
must still meet the existing target and source-consistency bands. Include input
uncertainty in the predeclared uncertainty budget.

Resistance
rise observes **both active and end-turn copper**, so compare the R20-weighted
mean: active_fraction * T_active + (1-active_fraction) * T_end. For the uniform
conductor model, use the winding record's active_fraction (length and R20 share),
not a guessed weight. Record both predicted node temperatures and that fraction;
the gate computes this mean itself. It must not compare terminal resistance
temperature to the active winding node alone. This assumes equivalent uniform
parallel paths; a different connection/source distribution needs a new registration.
The bundle records the resulting per-point inputs/outputs and the pre-run
prediction identity; archive the frozen response alongside the raw data so a
reviewer can reproduce it. Merely copying an identity string does not establish
that supplied predictions followed that response. Verify the numerical source
against the archived registration before interpreting a physical PASS.
Scaling all M1 resistances by m scales temperature rises by m in this fixed,
linear DC experiment. Fit through-origin least squares on calibration rises:

```
m = sum(predicted_rise * measured_rise) / sum(predicted_rise**2)
```

Only calibration rows enter the fit. One multiplier cannot identify individual
housing, slot, contact or end-turn paths. It is specific to this motor, fixture
and cooling arrangement. No claim is made for changed housing/mounting or airflow.

Before collection, the owner must also record a plausible multiplier interval
and its physical rationale in the registration's diagnostic notes. There is no
universal interval supplied here. Report the fitted multiplier beside the verdict
and compare it with that predeclared interval. A value such as 3.5 can indicate a
wrong boundary assumption even if held-out levels scale together. Publish that
diagnostic, investigate the paths, and register any revised model for a new
experiment; do not tune the interval after seeing data. This plausibility note
is an owner-reviewed diagnostic, not an extra numerical PASS/FAIL band silently
added to the frozen gate.

Held-out PASS uses error + measurement uncertainty <= max(5% measured rise, 3 K);
YELLOW <= max(10% measured rise, 5 K); FAIL beyond. These candidate engineering
bands are frozen before data. Publish results either way. Reject mismatched
identities, missing levels, changed roles, heat mismatch, excess drift or excess
uncertainty instead of silently omitting data.

## Data and use

Run `python -m tools.check_thermal_bench` for the current pending result. With
`--registration owner-registration.json --bundle measured.json`, the tool fits
and judges the registered experiment. Output includes calibration point IDs,
multiplier, every held-out error and band, scope and exact qualification identity.
A synthetic bundle never qualifies anything. A physical PASS emits a qualification
record for the exact motor/cooling identity; it does not change app settings or
upgrade unrelated designs. Importing owner-approved evidence into saved analyses
is a later 0.6.x step once the actual motor is registered and measured. Until then
all app temperatures remain experimental.

Bundle fields:

- registration_sha256: SHA256 of canonical registration JSON (sorted keys, compact separators).
- motor_id, geometry_sha256, cooling_id, thermal_inputs_sha256, prediction_identity:
  exact match to owner_registration. The latter binds the uncalibrated model/code
  and per-point numerical source record, not a free-floating fitted number.
- evidence_kind: physical_measurement or synthetic; raw_data_sha256: archived
  instrument logs, repeated runs, uncertainty calculation and source predictions.
- points: one aggregate per registered ID, with id, role, ambient_C,
  predicted_active_C, predicted_end_C, active_fraction, measured_copper_W, model_copper_W,
  winding_uncertainty_K, steady_drift_K_per_min and resistance object:
  cold_C, cold_ohm, hot_ohm, cold_lead_ohm, hot_lead_ohm.

This gate qualifies average winding-to-ambient **DC** paths only. End-winding or
housing sensors support diagnosis, not independent hotspot qualification. Rotor,
magnets, air gap, rotation and continuous torque-speed ratings remain
experimental. Register and perform a rotating experiment with measured losses
and cooling before any speed-dependent thermal qualification. ORNL Prius thermal
figures are at most a coarse external plausibility bound; different geometry and
cooling prevent treating them as a gate for this motor.

## Prediction refresh after the heat-path audit

The heat-path audit (see the [README](README.md)) changes the prediction model and
therefore requires a new registered prediction identity before measurements.
No physical measurements or fitted multiplier currently exist to refit. If
measurements are later available, regenerate predictions at each measured heat
and ambient, fit using only the registered calibration rows, and recheck the
held-out rows. Do not reuse a multiplier fitted to an earlier model as validation.
The through-origin fit relies on prescribed heat: multiplying resistances scales
temperature rise in the passive network. It does not scale a fixed-current R(T)
equilibrium linearly, because that changes copper heat. New rating copper feedback
does not change the bench's measured-heat normalization or frozen bands.
