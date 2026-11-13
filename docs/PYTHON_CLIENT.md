# Python client

`backend.client` lets you script coilEM: define a motor in Python, solve it,
and read torque, back-EMF, d/q flux linkage, inductances, cogging and the
waveforms as numbers and NumPy arrays, without writing request JSON by hand.
It ships with coilEM; there is nothing extra to install.

## Quick start

```python
from backend import client as coilem


def main():
    motor = coilem.Motor(
        topology="SPM",
        stator=coilem.Stator(OD_mm=100, ID_mm=60, slot_count=12, stack_length_mm=50,
                             slot_opening_mm=2, tooth_width_mm=9, yoke_thickness_mm=8),
        rotor=coilem.Rotor(OD_mm=54, pole_count=8, magnet_thickness_mm=2.5, magnet_width_mm=16.5),
        winding=coilem.Winding(type="concentrated", layers=1, turns_per_coil=12),
    )
    result = coilem.solve(
        motor,
        coilem.OperatingPoint(current_A=20, current_angle_deg=30, speed_rpm=3000),
        analyses=["torque", "back_emf", "cogging"],
        quality="quick",
        mesh="coarse",
    )
    print(result.average_torque_Nm, result.torque_ripple_pct, result.back_emf_fundamental_V)
    print(result.dq.L_d_H, result.dq.L_q_H, result.cogging.peak_to_peak_Nm)
    angles, torque = result.torque.angle_deg, result.torque.values  # NumPy arrays


if __name__ == "__main__":  # required: see "Scripts and worker processes" below
    main()
```

Two complete examples run end to end in about 10 s and about a minute:

```bash
python docs/examples/client_spm_motor.py
```

```bash
python docs/examples/client_ipm_motor.py
```

The first solves a surface-magnet motor at one operating point and saves the
request and result as JSON. The second sweeps the current angle of a
flat-buried interior-magnet motor and prints torque, d/q flux linkage and
apparent inductances at each angle. Both write to `coilem-client-output/`, or
to the folder given as the first argument.

## Motors

`Stator`, `Rotor`, `Winding`, `Wire` and `Materials` are the app's own input
models, so their fields, units (mm, degrees), limits and defaults are those
of the Design page; your editor shows them as keyword arguments. `Materials`
defaults to M350-50A steel, N42 magnets and copper.

```python
motor = coilem.Motor.load("benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json")
longer = motor.replace(stator={"stack_length_mm": 80})        # merge: only the named fields change
stronger = motor.replace(materials={"magnet_grade": "N52"})
longer.save("longer.json")                                      # request JSON the app's /solve accepts
```

A `Motor` is immutable; `replace` returns a changed copy. `Motor.load` reads
a `.coilem` design file saved by the app, a solve request (the plain motor
configuration, as in `benchmarks/*/fixtures/*.json`, or the app's
`{"config": ...}` wrapper), and `save` writes it back unchanged, including
fields this version does not use. Design files from older versions of the
app are refused with a message to open and save them in the app first, which
updates them; the client does not migrate them itself.
`motor.stator`, `motor.rotor`, `motor.operating_point` and `motor.analyses`
show what a loaded file holds.

## Operating point and solve settings

```python
point = coilem.OperatingPoint(
    current_A=50,              # phase current amplitude, peak unless current_convention="rms"
    current_angle_deg=30,      # γ from the q-axis; positive is toward flux weakening (negative i_d)
    speed_rpm=3000,            # for back-EMF voltage and losses; 0 is a static solve
    magnet_temperature_C=80,   # optional Br/Hc derating; None is room temperature
)
result = coilem.solve(motor, point, analyses=["torque", "back_emf"], quality="standard", mesh="normal",
                      solve_params={"nonlinear_solver": "newton"})
```

- `analyses` names what runs: `torque`, `back_emf`, `cogging`, `losses`,
  `thd` and `flux_density`. Left out, the motor's saved selection is used, or
  the app's defaults for a motor with none.
- `quality` is `quick`, `standard`, `fine` or `custom` (then set
  `rotor_step_deg` and `rotor_sweep_range_deg` in `solve_params`); `mesh`
  is `coarse`, `normal`, `fine` or `very_fine`. Quick and coarse are for
  trying things; use standard or finer for design numbers.
- `solve_params` sets any other request field by name.
- Settings layer in this order: the motor's saved solve settings, then the
  app's new-design solver settings for fields they leave unset (the mesh is
  rebuilt at every rotor position and corner refinement is on), then the
  operating point, `quality`, `mesh` and `solve_params`.
- `coilem.build_request(...)` returns the exact request `solve` would send,
  and `coilem.check(...)` runs the app's pre-solve checks and returns its
  winding warnings, both without solving.

## Results

| Accessor | Meaning |
| --- | --- |
| `average_torque_Nm`, `torque_ripple_pct` | Loaded torque sweep |
| `back_emf_fundamental_V`, `back_emf_thd_pct` | Phase back-EMF fundamental at the operating point's speed |
| `lambda_pm_Wb`, `Kt_Nm_per_A`, `Ke_Vs_per_rad_mech` | Magnet flux linkage and constants |
| `dq` | `i_d_A`, `i_q_A`, `lambda_d_Wb`, `lambda_q_Wb`, `lambda_pm_Wb`, `L_d_H`, `L_q_H`, `torque_dq_Nm`, status |
| `cogging` | `peak_to_peak_Nm`, `peak_Nm`, `first_harmonic_Nm`, period, harmonics, status |
| `torque`, `cogging_torque` | `Waveform`: `angle_deg` (electrical) and `values` arrays |
| `back_emf`, `phase_current` | `PhaseWaveforms`: `angle_deg`, `a`, `b`, `c` (and line-to-line `ab`, `bc`, `ca` for back-EMF) |
| `metrics()` | The headline numbers as one flat dict |
| `data`, `request` | The full result as the app returns it, and the request that produced it |

Anything the run did not compute is `None`: `cogging` without the cogging
analysis, `dq.L_d_H` without back-EMF (the apparent L_d needs the magnet flux
linkage from the no-load sweep). `result.save(path)` and
`coilem.Result.load(path)` keep a result with its request; the field
pictures for the app's viewers (several MB per result) are left out unless
you pass `fields=True`, and `result.without_fields()` drops them in memory. As in the app, d/q
quantities, inductances and cogging are experimental outputs; `dq.status`,
`dq.inductance_status` and `cogging.status` carry that label.

## Sweeps

```python
sweep = coilem.sweep(motor, current_A=[25, 50], current_angle_deg=[0, 15, 30, 45, 60],
                     analyses=["torque", "back_emf"], quality="quick")
best = sweep.best("average_torque_Nm")        # the point with the most torque
torque = sweep.grid("average_torque_Nm")       # currents × angles NumPy array, NaN where a point failed
sweep.to_csv("sweep.csv")                       # one row per point, with any error
```

Every point is checked before the first solve. A point that fails keeps its
error (`point.error`) and the sweep goes on, unless `stop_on_error=True`.
`on_point(index, total, point)` reports progress. Each point's result is kept
without its field pictures, so long sweeps stay small in memory; pass
`keep_fields=True` to keep them.

## Errors

- `InputError` (a `ValueError`): an input is outside what the app accepts.
  `error.field` is its dotted path, such as `stator.slot_count`,
  `operating_point.current_A` or `rotor.pole_count`, and the message starts
  with it.
- `SolveError`: the solve started but did not finish. `error.error_code` is
  the app's code, for example `NONLINEAR_CONVERGENCE_FAILED`,
  `GMSH_UNAVAILABLE`, `SOLVE_ALREADY_RUNNING` or `SERVER_UNREACHABLE`; the
  original exception is chained.
- `MainModuleError`: see the next section.

All three derive from `coilem.CoilemError`.

## Scripts and worker processes

The solver meshes and solves rotor positions in worker processes. On Windows
(and wherever Python starts processes with `spawn` or `forkserver`) each
worker imports the main program again, so:

- Call `solve` and `sweep` from under `if __name__ == "__main__":` in a saved
  `.py` file. Without the guard every worker would start another solve.
- A script piped through stdin (`python - < script.py`) cannot be imported
  by the workers at all.

The client checks both before it starts any worker and raises
`MainModuleError` with this advice, instead of the bare `OSError` or
bootstrapping error Python would give. Interactive sessions, notebooks and
`python -m package` need no guard.

## In this process or in a running app

`solve` runs in your Python process by default, through the same checks and
pipeline as the app's `/solve` route: there is no server to start, and sweeps
are not queued behind the app's one-solve-at-a-time lane. To solve in a
running app instead, pass its address:

```python
result = coilem.solve(motor, point, server="http://127.0.0.1:2645")  # the coilem launcher's default port
```

The request then goes to the app's `/solve` route, the run is saved in the
app's run history, and the result has the same accessors. That route reports
no progress, so `on_progress` is for in-process solves only, and a second
solve while one is running fails with `SOLVE_ALREADY_RUNNING`. The `server`
form also avoids the worker-process rules above, because the app's process
does the solving.

## The import name

The client is `backend.client` because coilEM installs a single top-level
package, `backend`; `from backend import client as coilem` reads well in
scripts.

## Tests

```bash
python -m pytest tests/test_python_client.py
```

Most tests run without solving; one solves a small motor at the quick preset
on a coarse mesh (about 10 s).
