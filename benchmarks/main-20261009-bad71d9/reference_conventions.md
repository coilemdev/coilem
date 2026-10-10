# Back-EMF sign root cause

The apparent inversion came from the benchmark reference conversion. The
initial harness reflected FEMM angle samples into the public clockwise frame
and negated axial torque, but it kept voltages evaluated for positive
counterclockwise FEMM speed. That compared opposite physical rotation
directions at the same plotted angle.

Coilem's public native solver solves negative native rotor angles as public
angles increase. It differentiates flux linkage on that increasing public
grid and multiplies by positive public electrical speed. FEMM differentiates
on its increasing counterclockwise grid and multiplies by positive
counterclockwise electrical speed. Both report terminal Back-EMF using
`e = omega * d(psi)/d(theta)`.

For the same physical position and positive public clockwise speed:

```text
theta_public = -theta_FEMM
psi_public(theta) = psi_FEMM(-theta)
omega_FEMM = -omega_public
e_public(theta) = -e_FEMM(-theta)
```

The minus sign follows from the flux derivative and speed conversion. It is
fixed for every fixture and all three phase voltages; no waveform sign,
phase shift, scale or alignment is fitted.

The copied `public_femm_series` helper was written for a separate BLDC
diagnostic lane. Its docstring explicitly leaves voltage sign to a separate
speed-convention audit. Using its angle-only mapping as a complete Back-EMF
conversion was the harness error.

## Why OpenEM did not show the flip

The archived OpenEM v0.2.5 three-way report came from
`scripts/compare_elmer_magneto2d.py::_run_threeway_solver`, which calls
`Magneto2DSolver()` and `FEMMSolver()` in the same native counterclockwise
frame. The Magneto2D default is `launch_surface=False`. The archived baseline
voltages begin near -3.26 V for FEMM, Magneto2D and Elmer. They needed no
direction conversion. This Coilem run deliberately uses
`Magneto2DSolver(launch_surface=True)` to measure the public clockwise runtime.

## Verification

`audit.json` records source hashes, derivative function lines and evidence for
every completed pair available when the audit ran. The checks:

- Reproduce the saved Coilem baseline voltage exactly from its recorded
  no-load flux linkage for all three phases.
- Confirm winding/flux polarity independently: the baseline loaded flux
  linkage agrees at reflected physical angles within 0.10% NRMSE on all
  three phases using the rounded FEMM values in the retained solver log.
- Run the pinned FEMM derivative function with positive and negative speed;
  the negative-speed voltage is exactly the negative of the positive-speed
  voltage.
- Compare both pinned derivative operators on independently defined
  multi-harmonic flux data in reflected coordinates. Interior residual is
  below 1e-10 V. FEMM's one-sided endpoint stencils are excluded from this
  identity check; their effect remains in measured waveform diagnostics.
- Validate every completed native/reference result against its registered
  SHA-256; preserve raw measurements and the original report.
- Apply the fixed transform to all three raw phase voltage series. The
  normalization is idempotent, leaves input evidence unchanged, and leaves
  torque, amplitude metrics and declared gate verdicts unchanged.

For `spm_4p12s_simple__baseline`, phase A Back-EMF NRMSE changes from
199.987970% to 0.168322%; correlation changes from -0.999998605 to
+0.999998605. Phase B/C endpoint errors remain about 2.73% / 2.98% NRMSE;
these are retained rather than hidden by waveform alignment.


## Publication records

The original audit and raw measurements remain in the frozen local snapshot.
This report publishes the fixed conversion and retained waveform metrics;
no fitted alignment or new field solve was used for the revision. Original
audit SHA-256: `e32c1b031be9cbe9950a87e26db9df765034caaab12d90cd18baac403a5d4a3f`.
