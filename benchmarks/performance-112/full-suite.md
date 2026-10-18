# Full FEMM A/B/C/D performance run (#112)

A [fresh full-suite repeat on 2026-10-16](repeat-20261016.md) completed all
29 cases in **1h50m54s**, with every physical output and extraction audit exact.
The measurements below preserve the original **1h52m02s** observation.

All **29 registered FEMM cases** completed in **1h52m02s** with up to eight
independent case workers and the metrics/readiness/core-affinity producer. The archived
serial measurement span was **9h08m46s** on the same host:
**4.898x observed ratio / 79.58% less collection time**.

Every case exactly matches its frozen v3 physical outputs and extraction
audits. This is one new full-suite observation versus the archived serial
collection, with normal desktop activity present.

[Machine-readable results and integrity hashes](full-suite-summary.json) ·
[Matched four/eight-worker subset comparison](scaling.md) ·
[Execution tools and producer contract](../../docs/BENCHMARK_PERFORMANCE.md)

Later [repeated retained-model controls](contention.md) test a two-large-job
alternative to this four-large budget. The alternative slows that workload
by 18.13% despite faster individual analyses. It supplies no new full-suite
time; the configuration and result below remain the validated observation.

## Scope and configuration

Physical source: `738d9516e8500c5996c772bd96470472cbb9a0f9`.
Hardware: Windows 11, Ryzen 7 7700 (8 physical / 16 logical cores), 64 GiB RAM.
FEMM product version: `4, 2, 0, 0`; pyFEMM: `0.1.3`. Binary hashes and dependency versions are recorded in the JSON.
The public launcher schedules longest first; every case retains one internal
FEMM worker and its original loaded/no-load ordering. Models, materials,
excitation, angle grids, extraction definitions and tolerances are unchanged.

Owned FEMM jobs are leased distinct physical cores for the duration of each
case. The topology, CPU masks, lease intervals and verified process assignments
are recorded per case. This setting improved retained large-model throughput
in the preceding affinity probe; no numerical solve options are changed.

A worker budget of eight assigns cost two to the four models with more than
100,000 recorded mesh elements and cost one to the remaining models. This
caps concurrent largest models at four and permits up to eight smaller jobs.
The selected policy trades large-model latency against overall overlap; a
completed full-suite comparison against unbudgeted eight workers is not available.

A timestamp audit verifies the recorded worker and cost limits throughout the run,
exclusive physical-core lease intervals, and matching process affinity assignments.

Metrics mode avoids duplicate compact/full payload construction and omits
display contour segments and field-frame JSON. Numeric element fields,
region classification, steel RMS, airgap data and audit inputs remain.
Windows readiness checks replace identified fixed settles with bounded
fresh-answer and loaded-mesh probes. Retry and Wine paths are unchanged.

## Measured coverage

| Phase | Cases | New summed case time, s | Archived summed case time, s | Physical outputs/audits |
| --- | ---: | ---: | ---: | --- |
| A | 10 | 4646.98 | 5701.01 | Exact |
| B | 12 | 16948.36 | 16620.09 | Exact |
| C | 4 | 14806.46 | 8873.39 | Exact |
| D | 3 | 1278.94 | 1712.97 | Exact |

The two 48-slot cases illustrate the latency cost of contention:
`spm_8p48s_chorded_5_6` took 1h25m47s versus 0h44m02s archived; `spm_8p48s_distributed_femm_validation` took 1h31m09s versus 0h44m16s archived.
The collection overlaps this work with other cases; its overall wall-time gain
does not imply that every individual case becomes faster.

Case sums overlap under concurrency and must not be read as phase wall times.
The JSON contains each case, original/new measurement hashes, common physical
payload and audit hashes, per-case timing/resource profiles, cache/readiness
counts, launch order and distinct FEMM process IDs.

Sampled average owned CPU use was **5.39 logical-core equivalents**.
Peak sampled committed memory was **4.95 GiB**
and peak working set was **1.57 GiB**.
Sampling every two seconds can miss short-lived children. Per-case Windows
Job Object CPU accounting and peak commit are retained as additional evidence.

FEMM analysis calls account for **87.2%** of summed per-case wall time.
This locates the remaining compute cost; summed case times overlap in the run.

## Bundle integration

The completed collection also assembled into a local 29-record bundle in **3.50s**.
Both the pinned 1.1 loader and current 1.3 loader accepted it, with an explicit
local hash-bound compatibility candidate for the latter. Every normalized physical
reference result matches the published bundle. The published suite, requests,
numerical gates and validation frames are unchanged. Bundle and compatibility
candidate remain `REVIEW_REQUIRED`; this check performs no new native collection
or scientific qualification. Integrity hashes are in the JSON.

## Interpretation and adoption

The matched smaller-case comparison and large-model probes guided this mixed
policy. This full observation measures its collection time and exact physical
equality. Use the recorded budget and affinity configuration on the measured
host with the pinned producer, retaining the serial fallback and identity checks.

This measures FEMM reference collection. Native collection, reference-bundle
assembly, gate evaluation and report rendering remain separate stages. The
public launcher continues to default to one worker. Private integration and
raw scientific evidence stay local; historical reference bundles are unchanged.

Later motor/winding changes need their own compatible reference run. Existing
unsupported cases, YELLOW/FAIL outcomes and scientific review requirements
remain visible. Repeated idle-host controls, full-suite worker-policy comparisons
and integration for a new motor-discovery source pin remain in
[#112](https://github.com/coilemdev/coilem/issues/112).
