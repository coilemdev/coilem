# FEMM 5 A/B/C/D pilot (#112)

FEMM 5 completes the fresh matched Phase A case in **63.87s**,
versus **303.64s** with the optimized FEMM 4.2 producer:
**4.754x observed ratio / 78.96% less producer time**.
All four representative case sweeps complete. FEMM 5 changes the generated mesh
and numerical results, so this remains a separate candidate requiring review.

The [subsequent mesh-refinement study](femm5-mesh-convergence.md) tests two
explicit finer levels for the Phase C torque and IPM peak-flux differences,
including complete case timings and paired refined-input controls with FEMM 4.2.

[Machine-readable measurements and provenance](femm5-pilot-summary.json) ·
[Validated 29-case FEMM 4.2 run](full-suite.md) ·
[Execution contract](../../docs/BENCHMARK_PERFORMANCE.md)

## Build and method

Collected 2026-10-16 on Windows 11, Ryzen 7 7700 (8 physical / 16 logical cores),
64 GiB RAM. Each solve uses one fixed core (affinity mask 1). Cases, the fresh
4.2 control and the retained-input probes run sequentially, with no competing
evaluation solves. Ordinary desktop activity remains; timings are observational.

The official [FEMM 5 06Oct2026 build](https://femm.info/doku/doku.php?id=download5)
is portably extracted after verifying its published SHA-256 and valid David
Meeker Authenticode signature. The installer is not executed. Its shipped Python
binding is loaded in a fresh interpreter; the existing FEMM 4.2 installation,
Python binding, registry and persistent environment are preserved. The JSON pins
the installer, source archive, binding, binaries and local integration sources.

The adapter needs a local owned-TCP session shim in place of the 4.2 COM transport.
Each headless server has a verified executable/listener PID, isolated model,
answer, temp and application-data directories, and a kill-on-close Windows Job
Object with the recorded core affinity. Source and runtime identities are checked
before/after each case; the four cases use the same sealed integration sources.

Physical requests and extraction use the frozen v3 public pin
`738d9516e8500c5996c772bd96470472cbb9a0f9` and adapter pin
`8b95decda27d475ddbb75e99d92744ebc8e53b28`. Geometry, materials, currents, angle grids,
normalization and loaded/no-load history remain fixed. Both engines use the
previously tested metrics output, payload reuse and readiness optimizations.
No mesh setting or acceptance tolerance is relaxed. FEMM 5 nevertheless generates
a different mesh from the same model settings using its new mesher.

## Complete representative cases

| Phase | Case | FEMM 5 producer, s | Mean torque change | BEMF fundamental change | Saved native status, 4.2 / 5 reference |
| --- | --- | ---: | ---: | ---: | --- |
| A | `spm_4p12s_simple__baseline` | 63.87 | +0.127% | -0.010% | PASS / PASS |
| B | `ipm_vshape_8p12s_baseline_contract` | 157.89 | +1.615% | +0.868% | YELLOW / YELLOW |
| C | `spm_8p48s_distributed_femm_validation` | 203.82 | +3.986% | -0.035% | PASS / PASS |
| D | `spm_4p12s_small` | 42.27 | -0.133% | n/a | PASS / PASS |

Metric changes compare each new FEMM 5 reference against the frozen 4.2 reference.
Each case retains all registered positions, raw waveform grids and extraction
audit frame counts. Numeric audit values and physical waveforms differ; these
are **not exact-equivalence results**. The JSON records scalar and waveform
differences, representative mesh counts and original/new measurement hashes.

The last column replays unchanged public gates against already saved native
results. Baseline replay is first verified against the published gates. It is
a sensitivity check on changing the reference, not a new native solve, a
FEMM 5 accuracy certification or a change to the published benchmark result.
Phase D scalar diagnostics use the original signed raw summary, because its
normalized protocol format has waveforms without a summary. Its back-EMF is
not measured in this loaded protocol and is shown as n/a.

Only Phase A has a fresh matched full-case 4.2 timing. That control exactly
reproduces the archived physical payload and audits. The other archived timings
remain in JSON for provenance and are not treated as isolated solver speedups.
The four-case subset does not establish a full 29-case runtime or a speedup
over the previous **1h52m02s** parallel FEMM 4.2 collection. Do not multiply this
single-case ratio into that whole-suite result.

## Numerical sensitivity

For Phase A, mean torque changes by +0.127% and BEMF fundamental by -0.010%;
torque waveform NRMSE is 0.587%. The mesh changes from 43,134 to 31,784 elements.
For the Phase B V-shape IPM, mean torque changes by +1.615% and BEMF by +0.868%,
while tooth peak B changes by +8.382% and yoke peak B by -7.771%. Steel RMS B
changes are much smaller. Its saved native YELLOW result remains visible.

For Phase C, mean torque changes by +3.986%,
and raw weighted-stress torque waveform NRMSE is
5.302%.
Torque ripple changes by +6.299 percentage points.
The detailed energy/coenergy finite-difference diagnostics and peak/RMS B
differences are retained in JSON rather than inferred from a case status.

A separate retained final loaded Phase C model exposes stronger pointwise
sensitivity: 129,548 elements under 4.2 versus 74,894 under 5,
with torque -0.922885 versus -0.708262 Nm.
The difference is +23.256%
of the old torque magnitude at that one rotor position. Energy changes by
+0.208%;
sampled B-vector NRMSE is 4.462%
across 144 points. A single retained position is not the full waveform.

Both engines also read the other's exact saved answer. Torque agrees within
1e-12 Nm for the same answer file, locating the difference upstream in meshing
or solving rather than the torque postprocessor. This does not separate meshing
from solver changes or prove which engine is closer to the converged answer.
The released FEMM 5 CLI remeshes these magnetostatic inputs; an identical-mesh
solver comparison has not been established.

## Repeatability and performance limits

Three fresh retained-input solves per engine run in the order 4.2, 5, 5, 4.2,
4.2, 5. Within each engine, torque and all 144 sampled point fields repeat exactly.
Median analysis calls take **20.623s** for 4.2 and **1.060s** for 5.
The **19.46x** ratio is confounded by the different meshes and is
only a retained-input probe; it is not an identical-mesh, full-case or full-suite
speedup. All six timings, outputs and source/result hashes are retained in JSON.

In the complete Phase A FEMM 5 case, 96 analysis calls total 30.33s, about 47.5%
of producer time. Solution loading takes 5.12s and explicit mesh creation 3.88s.
Further gains may come from avoiding duplicate meshing and batching model/field
commands, followed by measured case concurrency. Those optimizations have not
been enabled or validated in this pilot.

## Adoption decision

FEMM 5 is a promising speed candidate. Keep it in a distinct provisional lane
while checking mesh convergence, torque/ripple and peak-B sensitivity on these
cases, then collect all 29 cases and measure parallel scaling under the new
workload. The old worker costs were tuned for 4.2 and require fresh measurement.

Frozen references, requests, gates and scientific qualification are unchanged.
Raw evidence and solver-specific integration stay local. Three earlier harness
attempts are preserved and excluded: a dependency preflight failure, an incorrect
probe rotor selection, and a text-decoding failure before case analyses. These
do not contribute timings or numerical evidence to this report.
