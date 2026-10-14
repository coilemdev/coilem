# 8p12s six-step ripple investigation

Separate diagnostics at measured commit `1ea9e406818b9ceafe5408e9c16acd33e9c439b0`. The original suite remains **FAIL**: 147.737333012% -> 152.771389258%, a **5.034056246 percentage point** change against the unchanged **5.0 pp** limit.

## Angular sampling

| Electrical step (degrees) | Points | Mean torque (Nm) | Minimum torque (Nm) and angle | Ripple (%) |
| ---: | ---: | ---: | ---: | ---: |
| 7.5 | 48 | 17.446357092 | 4.767361602 at 195 | 147.737333012 |
| 3.75 | 96 | 17.469421148 | 3.853866894 at 11.25 | 152.771389258 |
| 1.875 | 192 | 17.477690803 | 3.850692317 at 193.125 | 152.717268321 |
| 0.9375 | 384 | 17.478491621 | 3.691994106 at 12.1875 | 153.618234075 |

| Successive grids (degrees) | Mean delta | Ripple delta | Shared torque samples |
| --- | ---: | ---: | --- |
| 7.5 -> 3.75 | 0.132025304% | 5.034056246 pp | 48 / exact |
| 3.75 -> 1.875 | 0.047315489% | 0.054120937 pp | 96 / exact |
| 1.875 -> 0.9375 | 0.004581734% | 0.900965755 pp | 192 / exact |

Every shared-angle torque is bit-for-bit identical. The 7.5-degree grid misses the lower trough between its samples; refinement exposes it without changing the existing solutions. The finest minimum occurs at 12.1875 electrical degrees inside a commutation sector, with commanded phase currents +50, -50, 0 A. The additional refinements move ripple by 0.054121 and 0.900966 pp; the trough continues to change, so this is evidence of angular sampling sensitivity rather than a claim of fully converged extrema. Normal spatial mesh was held fixed; this does not establish spatial convergence.

## Current correction control

At this same fixed commit a fresh 25 A, 3.75-degree field sweep reproduces **all 96 torque samples exactly** from the earlier recorded `04f87a5` fine result (old registered request: 50 A). Mean is 8.738405960 Nm and ripple 298.537416632%. The old helper applied a hidden 0.5 factor to the slot current for this winding. Removing it makes the intended 50 A source effective; this control isolates that current correction from other intervening changes. Commanded-current waveforms differ (new 25 A control versus old 50 A request); the exact comparison is of the independently solved torque field samples, with no rescaling of old results.

## Verification and disposition

All three supplemental jobs completed, using the original source and binary identities. Diagnostic wall time: 242.453 s; solver job runtime sum: 236.850 s. Original registered requests/results, report artifacts and gate remain unchanged. All 48, 96 and 192 common torque samples in successive grids compare exactly. Runtime/request/result/log hashes are retained in [investigation.json](investigation.json), with portable diagnostic evidence under [jobs](jobs).

Keep the original failure. A future registered protocol can qualify finer angular grids against matching FEMM samples; these supplemental measurements do not replace that protocol or its reference data. No threshold relaxation is justified by this investigation.
