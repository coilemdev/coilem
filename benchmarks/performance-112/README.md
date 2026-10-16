# FEMM case-concurrency pilot (#112)

The subsequent [full 29-case run](full-suite.md) completed in **1h52m02s**, versus
the archived serial span of **9h08m46s**, with exact physical outputs and audits.
The initial two-case results below remain a separate historical observation.

The subsequent [FEMM 5 A/B/C/D pilot](femm5-pilot.md) measures a fresh paired
case and four complete representative sweeps. It records changed meshes and
numerical results separately from the exact-equivalence FEMM 4.2 work.
The [mesh-refinement follow-up](femm5-mesh-convergence.md) tests the Phase C
torque and IPM peak-flux differences at two explicit finer mesh levels, with
complete case timings and paired refined-input controls against FEMM 4.2.

The [follow-up measurements](scaling.md) add matched four/eight-worker testing,
CPU/memory observations and full-case output/readiness optimization checks.
The [large-model study](large-model.md) records throughput/core-affinity probes
and the explicit mixed-workload policy used for the full-suite validation.

Two registered cases completed in **13m35.2s serially**
and **8m21.6s in parallel**:
**1.625x observed speedup**, or a
**38.46% runtime reduction**.

This is a two-case development-host pilot, with one observation per configuration.
It is not a full A/B/C/D performance result or a qualification change.

[Machine-readable summary and hashes](pilot-summary.json) ·
[Execution tools and producer contract](../../docs/BENCHMARK_PERFORMANCE.md) ·
[Workstream #112](https://github.com/coilemdev/coilem/issues/112)

## Measurements

The physical source is the unchanged FEMM v3 pin
`738d9516e8500c5996c772bd96470472cbb9a0f9`, under its original registered requests,
materials, grids, extraction and within-case loaded/no-load ordering. The serial
run used the public launcher at `3347c27`; the parallel run used the local prototype
coordinator with the same physical producer and isolated automation bridge.

Hardware: Windows 11, Ryzen 7 7700 (8 physical / 16 logical cores), 64 GiB RAM.
Short tests and retained-field profiling shared the development host during
collection. These are observational timings, not an isolated or repeated study.

| Phase | Case | Serial producer time, s | Parallel producer time, s | Physical payload versus serial and archive |
| --- | --- | ---: | ---: | --- |
| A | `spm_4p12s_simple__baseline` | 486.436 | 499.498 | Exact |
| D | `spm_4p12s_small` | 324.754 | 336.678 | Exact |

The pair wall times above include the respective coordinators' overhead. Individual
case time can increase under contention even while overlapping jobs reduces total
wall time. Neither result should be extrapolated directly to the full suite.

## Integrity and ownership

Non-timing physical summaries, raw and normalized torque/current/available back-EMF
waveforms, angle grids and mesh counts are exactly equal between both fresh runs
and the archived v3 measurements. The JSON records a common canonical physical
payload hash and the original measurement/result file hashes for each case.
All recorded flux-linkage and current-source extraction audits also match exactly;
their counts and common audit hashes are retained in the summary.

The two concurrent FEMM instances had distinct verified process IDs and private
model, answer, temporary and cache directories. An actual termination check closed
one owned FEMM probe while a separate real reference solve continued unaffected.
The public scheduler's subprocess tests cover overlap, deterministic manifest
order, source and result tampering, resume, live-worker locks, failures and timeouts.

Historical reference bytes, failures, YELLOW/unsupported outcomes and scientific
review requirements remain unchanged. Raw measurements and private producer
sources remain local; the summary does not replace the original evidence.

## Next bottleneck

Command profiling shows substantial runtime outside FEMM's `mi_analyze` calls.
Retained-field profiling identified duplicate contour construction: the legacy
adapter builds compact and full field payloads separately for the same position.
A separate helper prototype reuses that computation, with exact equality of both
payloads in the retained-field check. Its three samples took about 1.5-1.6 seconds
per pair originally and 0.8 seconds with reuse.

That is a helper microbenchmark, not a full-solve speedup. Payload reuse was not
enabled in either fresh solve configuration. Steel RMS depends on the full field
payload, so dropping field extraction outright would change a physical summary.

The [follow-up](scaling.md) completes the full-case reuse check and measures
four/eight-worker subset scaling and CPU/memory use. Full-suite scaling and
repeated idle-host controls remain in #112. The public launcher retains a serial
default while producer-specific configurations are validated.
