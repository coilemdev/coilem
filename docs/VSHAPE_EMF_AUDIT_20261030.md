# V-shape back-EMF agreement investigation, 30 October 2026

The six-case average absolute fundamental error rose from **2.39% to 6.50%**
against identical retained FEMM v3 references. The new refined FEMM baseline
also puts the registered normal-mesh candidate at **YELLOW**: peak EMF error
is **10.0876% on macOS / 10.0841% on Windows**, above the unchanged 10% green
line. Its fundamental error is about **8.51%**. These are distinct reference
bases; the six-case 6.50% figure continues to use the unchanged old v3 records.
The candidate must not be described as regression-free.

The measured native candidate is `40d8ab9a0a1cadf5cf60023852229f4af010abad`.
The v0.4.0 evidence was measured at `5b6cb61`; all 53 registered physics-source
hashes match the actual v0.4.0 release `2ede4e8`. The average is an unweighted
mean of the six absolute percentage errors, not an average voltage increase.

## What moved

| Fixture | v0.4.0 native V | v0.5.0 native V | Same FEMM V | Native change | Error before → after |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 2.219174 | 2.354646 | 2.174460 | +6.105% | 2.056% → 8.286% |
| Deep apex | 1.489028 | 1.558831 | 1.440751 | +4.688% | 3.351% → 8.196% |
| Narrow angle | 2.255052 | 2.283919 | 2.181194 | +1.280% | 3.386% → 4.710% |
| Pocket offset | 2.204661 | 2.350592 | 2.174177 | +6.619% | 1.402% → 8.114% |
| Thin bridge | 7.415265 | 7.440945 | 7.359593 | +0.346% | 0.756% → 1.105% |
| Wide angle | 1.947915 | 2.046636 | 1.884456 | +5.068% | 3.368% → 8.606% |

Four cases have 8.11–8.61% fundamental error; narrow angle has 4.71% and thin
bridge 1.11%. The earlier draft's “five cases” wording was incorrect. Every
legacy PASS stays PASS under the same retained-reference gates. The baseline
changes YELLOW → PASS because its *peak* error improves, while its fundamental
and torque errors worsen. These are different metrics.

## Why the estimate changed

Newton previously tested an equation residual normalized by the entire RHS.
The corrected policy requires reduction relative to the initial nonlinear
defect of each continuation stage, with a separately recorded RHS floor.
This makes the weak winding flux converge further and moves the native EMF
upward. The retained [before/after stopping-policy studies](NONLINEAR_CONVERGENCE_WINDOWS.md)
and [IPM diagnosis](IPM_BENCHMARK_DIAGNOSIS.md) document the mechanism.
The harmonic extractor, material curve, geometry-IR definitions and native
field assembly/postprocessing sources are unchanged between the release and
candidate. The winding-current correction is also in this release; the
back-EMF fields here use zero current and no temperature derating.

Better equation convergence does not prove better agreement with FEMM or
hardware. The old closeness may have included error cancellation; that is an
inference, not independent validation of the new amplitude. This investigation
does not repeat a completely isolated old-policy sweep for all six fixtures.

## Native controls at the immutable measured pin

Geometry, material model, excitation and angle grids remain fixed. Controls
use the same frozen binary. The stage-relative tolerance tightens from 1e-5
to 1e-8; the RHS floor remains 1e-8. Fine additionally changes the mesh preset.
Each control checks all 13 loaded and 48 no-load convergence records, including
32 congruence-reused positions; 29 actual raw field reports are retained per
control. No fitted shift, sign or amplitude scaling is used.

| Control | Reported elements | Torque change from original | Fundamental change | Peak change |
| --- | ---: | ---: | ---: | ---: |
| native-newton-1e-8 | 94,688 | -0.00000043% | +0.000169% | -0.000386% |
| native-fine-newton-1e-8 | 101,874 | -0.47448390% | -0.383334% | -1.292091% |
| native-wide-angle-newton-1e-8 | 94,160 | -0.00000010% | +0.001305% | +0.000669% |

Further nonlinear tightening barely changes the baseline and wide-angle
outputs. Fine moves the baseline toward FEMM, but one modest mesh change
cannot establish spatial convergence or account for the whole discrepancy.
The controls retain the absolute floor; they do not claim arbitrarily exact
field solutions.

## FEMM precision and bridge controls

All three full baseline controls use exact **FEMM 4.2 (21Apr2019)** with verified
binary hashes and the retained reconstructed private producer/model at
`2ede4e8`. The baseline fixture and registered input hashes match protocol 1.6.
This is a diagnostic of that retained model, not the requested 46-record
protocol 1.6 reference bundle. The adapter and every reference remain
**REVIEW_REQUIRED**.

The [FEMM 4.2 manual](https://www.femm.info/Archives/doc/manual.pdf)
defines its precision setting as the linear-system relative residual limit.
This control is not an independent audit of FEMM's nonlinear stopping rule,
and its number is not directly comparable to native Newton's stage-relative
tolerance.

The precision control changes only 1e-8 → 1e-10. The bridge control also
subdivides 32 outer bridge/pocket segments with a 0.2 mm maximum length;
the rotor interior remains automatic. Minimum angle stays 30°. Every saved
model is compared: geometry, materials and currents are identical; only these
precision/mesh constraints differ.

| FEMM control | Torque N·m | Fundamental V | Peak V | Fundamental movement vs fresh baseline | Torque movement |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 0.842168178 | 2.172854851 | 3.264896102 | +0.000000% | +0.000000% |
| precision | 0.842168209 | 2.172855084 | 3.264897049 | +0.000011% | +0.000004% |
| bridge | 0.839566363 | 2.169969505 | 3.242987480 | -0.132791% | -0.308942% |

| Reference control | macOS native fundamental error | Windows native fundamental error | macOS / Windows diagnostic gates |
| --- | ---: | ---: | --- |
| baseline | 8.368303% | 8.366447% | PASS / PASS |
| precision | 8.368292% | 8.366435% | PASS / PASS |
| bridge | 8.512397% | 8.510539% | YELLOW / YELLOW |

The bridge control moves FEMM's fundamental by only **−0.13279%** and its
peak by **−0.67104%** from the fresh baseline. That does not explain away the
native/FEMM gap, and the changed peak is enough to cross the registered green
line for the normal-mesh candidate. Both platforms have the same YELLOW
outcome; this is not a platform execution failure.

The diagnostic native Fine mesh against this refined FEMM baseline is
reported separately in the data. It is a changed-request control, not the
registered normal-mesh candidate or a qualified replacement default. One
Fine step cannot establish spatial convergence or qualify the other fixtures.

All signed waveform diagnostics, original limits, peak/torque outcomes and
model/source hashes remain in the [data](VSHAPE_EMF_AUDIT_20261030.json).
The original serial, global-rotor refinement and shorter-window bridge
attempts were interrupted for bounded execution and retained in full. They
have no completed reference verdict and are not relabelled as successful
collections. Completed baseline, precision and bridge runs have independent
registrations; all raw bytes were archived and verified locally.

## Retained-field extraction screen

One unchanged retained no-load FEMM field (the last registered pose,
352.5 electrical degrees) was re-extracted without any field solve. Replacing
its small interior sampling grid with the block-integrated mean vector
potential changes the three-phase flux vector by only **0.01658%** in relative
L2. Native's corresponding retained flux vector remains **8.43290%** above
that block-averaged FEMM vector in relative L2 (norm difference **8.43082%**).
No angle, polarity or amplitude fit is applied.

This screen locates a discrepancy in flux linkage before differentiation or
harmonic voltage extraction. It does not isolate field discretization from
geometry/material/winding-model differences, and one pose cannot qualify a
full EMF waveform or every extraction pose. The point runner, original fields,
completion receipt and launcher bookkeeping warning remain retained; the
actual source/result hashes were independently checked.

## Claim boundary

The [Prius audit correction](PRIUS_CONVERGENCE_AUDIT_20261030.md) resolves its
reporting compatibility failure separately, preserving original 9/10 reports.
These V-shape controls investigate an actual increase in reference error;
they do not authorize changing a numerical gate, choosing tolerances to fit
FEMM, promoting the private producer, or declaring the whole candidate
regression-free. Keep V-shape accuracy experimental pending review of the
remaining spatial/model discrepancy and the complete matched protocol 1.6
reference collection. Same-mesh field/linkage comparisons would separate
spatial/discretization effects from model/extraction differences more directly.
No hardware correlation or controlled runtime claim is added.
