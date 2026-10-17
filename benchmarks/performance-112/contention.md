# FEMM 4.2 large-model contention controls (#112)

**Retain existing four large policy.** The two-large policy makes this retained workload slower in both order-balanced comparisons. Keep the existing four-large budget policy. Lower per-job latency, if observed, does not compensate for the loss of overlapping work in this experiment.

This is a repeated **retained-model throughput experiment**, not a new
registered case or A/B/C/D suite run. The validated 29-case result remains
**1h52m02s** with the existing worker-cost configuration.

[Audited timings, input hashes and exact solution checks](contention-summary.json) ·
[Existing full-suite result](full-suite.md) · [Earlier large-model controls](large-model.md)

## Workload and controls

Hardware: Windows 11, Ryzen 7 7700 (8 physical / 16 logical cores), 64 GiB RAM.
The FEMM 4.2 binaries, dependencies and physical source pin match the earlier
`738d951` collection. No FEMM 5 process participates.

Each round schedules the four largest models (both 48-slot distributed
cases, 12p/36s distributed and 24s/16p flat IPM), plus the same eight
smaller A/B/D jobs used in the earlier scaling comparison. Each worker
independently reloads its saved final-angle loaded/no-load models twice.
The two BLDC jobs have only loaded models. This gives **44 fresh analyses
per round**, **176 total**. Models have 40,690 to 129,548 triangles.

Both policies use at most eight workers, a budget of eight, longest-first
order and exclusive physical-core leases for owned FEMM jobs. Small jobs
cost one; large jobs cost two in the existing policy and three in the
candidate. The candidate therefore permits two large plus two small jobs
at once while both large jobs remain active. It is not a separate class
cap allowing two large plus six small workers.

Run order is existing, candidate, candidate, existing (ABBA). Startup,
source-identity checks, mesh construction, analysis and solution-integrity
checks are included in coordinator wall time. Normal desktop activity
continues; this is not an isolated idle-host study.

## Measured comparison

| Policy | First observation, s | Second observation, s | Mean wall time, s | Mean large-job time, s | Mean large analysis, s/solve |
| --- | ---: | ---: | ---: | ---: | ---: |
| Up to four large, cost 2 | 159.63 | 160.04 | 159.83 | 120.70 | 29.41 |
| Up to two large, cost 3 | 188.06 | 189.54 | 188.80 | 90.35 | 21.86 |

The candidate changes mean retained-workload wall time by **+18.13%**
(negative means faster). Its paired wall-time reductions are
**-17.81%** and **-18.44%** (positive means faster).

Mean large-model analysis latency falls by **25.69%**,
but the lost overlap outweighs that per-solve gain in this workload.

Per-model analysis times below sum the two repetitions and divide by
their actual solve count, then average the two rounds for each policy.

| Large model | Four-large analysis, s/solve | Two-large analysis, s/solve |
| --- | ---: | ---: |
| `spm_8p48s_distributed_femm_validation` | 38.59 | 29.06 |
| `spm_8p48s_chorded_5_6` | 38.05 | 25.94 |
| `spm_12p36s_distributed_femm_validation` | 22.31 | 16.76 |
| `ipm_flat_24s16p_industrial_contract` | 18.70 | 15.67 |

## Integrity and interpretation

Every independently recomputed mesh node, triangle and nodal magnetic
vector potential matches its saved FEMM 4.2 answer exactly. Input file
hashes also match. The verifier checks all 176 solves, request/result
hashes, before/after source identities, worker costs, concurrency events
and exclusive core leases with matching process affinity. Per-round
resource samples and source hashes are retained in the JSON.

The experiment replays retained inputs; it does not regenerate a rotor
sweep, registered torque/back-EMF curves or extraction audits. Its timing
includes short-job startup and hashing costs that are proportionally
smaller in full sweeps. Two runs per policy cannot characterize all
host-load variability. No whole-suite runtime is inferred from them.

This tests the existing weighted-budget mechanism. It does not rule out
every possible schedule or a separate two-large/six-small class cap.

The two-large policy makes this retained workload slower in both order-balanced comparisons. Keep the existing four-large budget policy. Lower per-job latency, if observed, does not compensate for the loss of overlapping work in this experiment.

The existing worker-cost file, frozen references, motor-discovery
sources, gates, FEMM version and scientific qualification are unchanged.
