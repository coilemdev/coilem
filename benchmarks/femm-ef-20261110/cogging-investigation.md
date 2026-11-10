# Three distributed-cogging reference failures

The evidence supports two numerical mesh effects: the normal FEMM reference has
mesh-dependent mean/closure bias, and the normal Magneto2D mesh has an amplitude
error on these cases. The failure flags are not caused by batching or resume.
No fixture, registered mesh, angle grid, gate or product default is changed here.

## FEMM reference checks

Each mean and independent endpoint mismatch must be no larger than the fixed
case floor. Recomputing the metrics from the retained 25-point waveforms gives:

| Fixture | Floor (Nm) | Normal absolute mean | Normal closure | Half-gap absolute mean | Half-gap closure |
|---|---:|---:|---:|---:|---:|
| 8p24s distributed | 0.028310 | **0.112600 FAIL** | **0.033447 FAIL** | 0.007542 PASS | 0.003412 PASS |
| 8p48s distributed | 0.031519 | **0.038607 FAIL** | 0.015922 PASS | 0.006034 PASS | 0.003499 PASS |
| 12p36s distributed | 0.026074 | **0.057207 FAIL** | **0.042448 FAIL** | 0.004395 PASS | 0.015359 PASS |

Only the airgap mesh target is halved in these FEMM diagnostics. Physical inputs,
25 angular samples, material curve, zero-current excitation and weighted-stress
extraction remain fixed. All six refined reference self-checks pass. The
approximately 1% amplitude change is much smaller than the reduction in the
spurious mean offsets. Holding the angular sampling fixed while changing the
mesh isolates a spatial-discretization effect; it does not establish the fully
converged torque or rule out every remaining quadrature error.

The November 10 standard run reproduces the original normal-mesh fields exactly,
including the failed checks. The failures are therefore reproducible numerical
findings, rather than corrupted checkpoints or inconsistent file writes.

## Native amplitude convergence

All comparisons below use the same refined FEMM reference per fixture, identical
angular samples, unchanged 10%/20% bands and fixed case floors. Values are
peak-to-peak error / first-harmonic error relative to FEMM.

| Fixture | Normal native | Fine native | Very-fine native |
|---|---|---|---|
| 8p24s distributed | 10.73% / 10.17%, YELLOW | 9.02% / 8.25%, PASS | **3.08% / 2.09%, PASS** |
| 8p48s distributed | 9.10% / 7.30%, PASS | 12.63% / 11.05%, YELLOW | **3.27% / 2.51%, PASS** |
| 12p36s distributed | 11.20% / 9.24%, YELLOW | 10.30% / 7.45%, YELLOW | **4.07% / 3.12%, PASS** |

The ordinary fine preset is not a reliable fix: the 8p48s representative mesh
actually drops from 44,718 to 41,662 elements and its error grows. Very-fine
meshes have approximately 106k–127k representative elements and pass all three.
This supports native mesh sensitivity without proving either solver is fully
converged. The native fields retain their November 3 measured source pin;
they are not restamped as a current-main native run.

The three distributed native normal endpoints reuse a mesh/solution. Their exact
zero closure values are not independent remesh checks, and are not used here as
evidence of superior endpoint accuracy. The FEMM endpoints are independent.

## Evidence verification and reproduction

The investigation rechecks **150 retained FEMM model/answer pairs**: all 75
normal and 75 half-gap positions for these cases. Their saved hashes and zero
current integrals verify. It also verifies **nine native request/result pairs**
and identities: three normal, three fine and three very-fine. Restoring only
`solve_params.mesh_density` makes each diagnostic native input identical to its
registered normal input. The existing geometry audit has exact public/reference
region graphs for all 12 E cases.

The committed waveforms and metrics from the
[original convergence study](../../docs/benchmarks/cogging-windows-20261103/README.md)
allow the diagnosis to be recomputed without FEMM:

```powershell
python -m tools.review_cogging_fixtures --out output/cogging-review.json
```

The command performs no fitting, filtering, waveform alignment, offset removal
or rescaling. The [retained-evidence recheck](cogging-retained-evidence.json) records
the 150 reference fields and nine native identities.

A separate November 10 [fresh endpoint replay](cogging-endpoint-replay.json) uses
the PR's repository-owned adapter to solve both endpoints independently on all
three half-gap references. All **6/6 model hashes, answer hashes and physical
payloads match exactly**, and all three measured closure checks pass. This is
six new fields, not three new full sweeps; the mean checks come from the verified
retained full sweeps. The repeated endpoints required no change to the registered
normal-mesh baseline.

## Recommended disposition

Keep the three original cases at `REFERENCE_REVIEW_REQUIRED`, with all five
failed checks intact. The half-gap FEMM sweeps are candidates for a separately
reviewed, versioned reference cohort. Very-fine native meshes are useful for
qualification diagnostics; changing the normal product default is not justified
by this study.

A replacement reference cohort needs its own registration and a matched run at
the intended native commit. Its timing must also be measured: the published
3 h 16 min result covers the unchanged standard matrix, which excludes the
three extra half-gap diagnostic sweeps. This investigation neither silently
substitutes those references nor relaxes any acceptance limits.
