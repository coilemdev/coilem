# Higher-output IPM benchmark addendum v1.0

Measured Coilem candidate `af56962e690ade4816e48f562e380249aac7542e`; separate reference `8b95decda27d475ddbb75e99d92744ebc8e53b28`.
This candidate is the local diagnostic commit, not the PR base or next release commit.
Two new physical designs, fresh matched FEMM, unchanged gates. Normal spatial meshes,
13 torque points (0–90°), 48 Back-EMF points (0–352.5°), step 7.5°.
Public native defaults include Newton tolerance 0.05; WST and native Gmsh.
M350-50A curve and N42 Br = 1.315 T, μr = 1.05 match.

| Case | Native mean (N·m) | FEMM mean (N·m) | Mean gap | BEMF H1 gap | BEMF peak gap | Outcome |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| ipm_vshape_8p12s_wide_angle_high_output_v1 | 0.789964 | 0.737758 | 7.08% | 3.49% | 3.95% | PASS |
| ipm_vshape_8p12s_deep_apex_high_output_v1 | 0.625690 | 0.582518 | 7.41% | 3.35% | 3.95% | PASS |

Magnet legs increase from 9 to 10 mm for wide angle and 9 to 12 mm for deep apex.
The wide 75° angle / 13.5 mm apex depth and deep 60° angle / 17 mm apex depth remain.
Current, winding, stack, material inputs and public numerical settings are unchanged.
These designs exceed 0.5 N·m in both measured mean torques.

The original deep-apex mean torque is 11.99 mN·m native versus 18.74 mN·m FEMM;
its absolute gap is 6.75 mN·m and relative gap 36.02%. Historical N·m units were
correct. Changing units cannot change relative error. The original wide-angle
means are 0.088852 / 0.101438 N·m. Both original recorded FAILs are retained.
These are replacement physical designs for the default matrix; their PASS does not establish a solver
fix for the originals. Normal meshes do not establish spatial convergence.

See [plots and fixture links](coilem_benchmark_report.html), [summary](benchmark_summary.json),
[historical A/B/C/D evidence](../main-20261009-bad71d9/benchmark_report.md),
[release baseline v1.2](../release-baseline-20261011-v1.2/benchmark_report.md),
and [protocol 1.1 commands](../abcd-v1.1/README.md).
This measures two new Phase B cases; it is not a new full A/B/C/D or release signoff.
