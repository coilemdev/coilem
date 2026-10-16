# FEMM performance follow-up (#112)

The subsequent [full-suite run](full-suite.md) validates all 29 cases with the
combined execution optimizations. The matched subset measurements below retain
their original producer identities and scope.

The same eight registered A/B/D cases were collected with four and eight
independent case workers, using identical metrics-only producer identities.
Four workers took **740.71s**; eight took **431.99s**.
That is **1.715x observed speedup** from four to eight workers.

[Machine-readable results, resource use and integrity hashes](scaling-summary.json) ·
[Initial two-case concurrency pilot](README.md) ·
[Producer contract](../../docs/BENCHMARK_PERFORMANCE.md)

Hardware: Windows 11, Ryzen 7 7700 (8 physical / 16 logical cores), 64 GiB RAM.
Each configuration has one observation on the development host. Background
desktop activity was not isolated. These are subset measurements, not a full
29-case A/B/C/D timing result or a qualification change.

## Remove repeated display work

A fresh serial BLDC case (`spm_4p12s_small`) isolates the output-work experiments:

| Mode | Producer time, s | Reduction versus original |
| --- | ---: | ---: |
| Original fresh serial | 324.754 | 0.00% |
| Paired payload reuse | 279.887 | 13.82% |
| Metrics-only output | 199.899 | 38.45% |
| Metrics + Windows readiness | 165.647 | 48.99% |

Paired reuse computes the full field payload once per position and projects
the compact payload from it. The public helper retains only the latest
position; the full-case check exercised 48 builds and 48 reuses.

Metrics-only output additionally skips visual contour segments and field-frame
JSON artifacts. It retains element fields, region classification, steel RMS
accumulation, airgap extraction, flux/current audit inputs and all physical
summary calculations. This mode intentionally does not produce display frames.

The separate Windows experiment replaces fixed pre/post-load settle sleeps
with bounded checks for a newly written nonempty answer and a loaded mesh.
It fails closed if the pinned call sites change. Retry delays and Wine paths
retain their original behavior. This variant was not used in the matched
four/eight-worker comparison.

## Matched concurrency comparison

| Workers | Cases | Wall time, s | Sampled mean CPU cores | Peak sampled committed memory, GiB |
| ---: | ---: | ---: | ---: | ---: |
| 4 | 8 | 740.71 | 2.85 | 2.38 |
| 8 | 8 | 431.99 | 5.93 | 5.15 |

Both runs use the public launcher, the same eight registered requests,
longest-first scheduling and one internal FEMM worker per case. The JSON
records launch order, per-case wall/CPU/memory figures, distinct FEMM PIDs
and command profiles. The original serial reference durations for these eight
cases sum to 3675.92s;
that historical sum is not a fresh matched wall-time control.

## Physical equality and coverage

Every collected case exactly matches frozen v3 physical evidence: non-timing
raw summaries, normalized outputs, waveforms, slot excitation frames, angle
grids, mesh counts, physical solve metadata and current/model contracts.
All flux-linkage and source extraction audits also match exactly.

This comparison covers eight A/B/D cases. Phase C and the larger IPM cases
require a separate full-suite pass. Reference geometry, excitation,
materials, tolerances and within-case loaded/no-load ordering are unchanged.

## Adoption and remaining work

Use the measured faster concurrency setting for this tested workload on this
host with the pinned private producer; keep internal case pools serial.
The public launcher still defaults to one worker. The payload helper requires
an explicit producer opt-in and an exact compact/full projection check.

The later [full-suite pass](full-suite.md) supplies 29-case timing and exact
physical equality, including V-shape/high-output cases and local bundle assembly.
Repeated idle-host measurements, full-suite worker-policy comparisons and
integration for a new motor-discovery source pin remain in
[#112](https://github.com/coilemdev/coilem/issues/112).
Original evidence, numerical gates and scientific review requirements are unchanged.
