# Two-layer solution reuse — Windows, 2026-11-09

Measured implementation `68c3167f` is based on release/v0.5.6 `8b6b394f`. The steel-classification experiment is not included.

## Change

Conformal native flux contributions now identify their actual physical winding layer and turn fraction. Complete two-layer reports can reuse a whole-slot congruent solution: rotate the field, map the same physical layer to its new global slot, and apply the target winding direction/phase. The source contribution already includes its turn fraction; it is never halved again.

Reuse requires complete explicit layer identities, matching turns/fractions, consistent gauge/terminal scaling and sinusoidal excitation, plus the existing per-element current-density equality gate. Legacy one-row-per-slot reports keep their path. Ambiguous, partial, sector or incompatible reports retain parallel native fallback. Ideal six-step reuse remains disabled.

## Whole-job measurements

| Case | Baseline mean (range) | Branch mean (range) | Less wall time | Speedup |
| --- | ---: | ---: | ---: | ---: |
| Phase F micro | 80.38 s (79.75–81.01) | 65.48 s (64.38–66.58) | 18.54% | 1.23× |
| Phase F drone | 63.85 s (63.46–64.24) | 62.69 s (62.65–62.73) | 1.81% | 1.02× |

Two fresh-process observations per variant/case on an AMD Ryzen 7 7700, 64 GiB Windows host. These ranges are observations, not confidence intervals. Both variants use the same metadata-only native executable, identical Rust sources, unchanged explicit-Newton requests, and the existing eight-worker pool. The unchanged public worker timer includes numerical postprocessing and field extraction; HTTP, public-run saving and playback drawing are excluded. All source/request identities were checked before and after.

Micro native solves fall from **96 to 64**, with 32 synthesis fallbacks eliminated (16 loaded and 16 no-load). Drone falls from **96 to 76**, eliminating 20 no-load fallbacks; its loaded current patterns correctly remain independent solves. Both retain all 48 loaded field frames. The drone's smaller wall-time benefit reflects the whole pipeline, rather than the fraction of launches eliminated.

The first drone baseline overlapped a snapshot verifier and is excluded from primary timing. Its independent native reports remain valid physics evidence. The JSON retains that observation and every quiet repeat. The single-layer control took **48.80 s baseline / 50.28 s branch** in one run per variant (about 3% longer), with exact physical-output parity. That single pair does not establish a timing regression. Treat the small drone improvement as an observation from two runs; a robust whole-job gain is not established at this sample size.

## Independent physics comparison

The baseline natively solved the actual derived target meshes. Comparing those reports with synthesized targets checked **52 targets, 1,056 physical winding sides, and 96 full playback frames containing 10,917,264 element records**. Mesh connectivity/materials/boundaries, rigid geometry/magnetization rotation, layer labels/coefficients and the existing global-norm RHS gate all passed. The synthesized quantities were also checked against the candidate aggregates actually consumed.

Micro's maximum returned torque difference is **4.85e-15 Nm**; drone's is zero. Maximum phase back-EMF differences are **1.22e-13 V / 1.30e-13 V**, and winding-side flux differences **1.89e-17 Wb / 1.31e-17 Wb**. Nodal A_z differences are at most **5.54e-16 / 3.64e-15 Wb/m**. Full loaded playback B differences are at most **5.26e-13 T / zero**.

All consumed physical outputs pass fixed **1e-9 relative plus quantity-specific absolute floors**, listed in the JSON. This is a regression check on the retained discretizations, not a new physical qualification. Runtime/nonlinear work counters are excluded from parity.

Copied fixed-angle contour samples and quadrant debug allocations remain source-angle diagnostics; they are not claimed equivalent to fresh target-angle debug samples. The JSON lists the differing paths and diagnostic explanation. Selected torque, energy, flux, A_z and full fields have separate strict checks.

The single-layer control passes **exact** result/aggregate, mesh, native-report/A_z and decoded full-frame comparison, after explicit timing/provenance exclusions. Its counts are in the JSON.

## Validation and limits

- Python: **2,013 passed, 3 skipped**, including 85 new reuse cases. Two source-provenance tests passed separately in their required environment.
- Rust: **269 passed**. Ruff and the implementation snapshot/publication gate passed.
- The full A-D/F/E collection, FEMM reference regeneration and two-platform qualification are separate from this experiment.
- Memory samples and all per-run timings/hashes are retained in the [machine-readable report](two-layer-solution-reuse-windows-20261109.json). Private commit differs from resident RAM; summed working sets can count shared pages more than once. Samples occur about every 0.5 s.

The native executable SHA-256 is `95088c7b08b60a1630957a1639af8dcd6b49e24223e7832f13f81417d992c498`. Raw evidence, logs and validator receipts remain local, with verified lossless archives used where needed to preserve free space.
