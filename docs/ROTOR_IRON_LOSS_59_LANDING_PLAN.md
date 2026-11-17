# Rotor iron loss: 0.5.9 integration and deferred qualification

## Release decision, 2026-11-17

The release owner chose to integrate #318 into `release/v0.5.9` with rotor
iron loss remaining **experimental**. Completing the reduced rotor-loss
qualification matrix is deferred to a future release. This decision supersedes
the earlier requirement to finish that matrix before merging #318.

The immediate priority is a full-motor A–F and Prius regression collection on
the assembled 0.5.9 candidate, on Windows and macOS, against the registered
frozen FEMM references and the published 0.5.8 results. Record the exact merged
candidate, source and binary identities. A passing historical report does not
qualify a changed build. Review changes in individual metrics and existing
failures as well as aggregate pass counts; retain all original tolerances.

Sector validation is also deferred. Existing limited sector functionality
remains experimental; sector rotor iron loss remains explicitly unavailable.
The sector rotor material-mesh and loss work remains tracked by
[#319](https://github.com/coilemdev/coilem/issues/319). Do not dispatch the
sector collection as a 0.5.9 release prerequisite.

## Implemented scope

The explicit rotor-loss option defaults off and requires Losses & efficiency.
Supported requests use a full mechanical turn with 384 half-open poses and a
fresh closure solve, following fixed rotor material cells and expressing B in
rotor axes. Supported inner SPM and flat-buried IPM, sinusoidal excitation,
positive speed and bundled M350-50A loss coefficients are described in
[Rotor iron loss](ROTOR_IRON_LOSS.md).

Public results, accounting, efficiency maps, saved runs, API/CLI and exports
carry the separate rotor terms and provenance. Unsupported or incomplete
requests return an unavailable result. Analytical and integration checks cover
frame conventions, closure, speed scaling, exact-once accounting and the
opt-in boundary. Numerical reference agreement does not establish measured
motor accuracy or qualify the empirical loss law.

## Evidence and remaining work

The completed loaded-SPM pilot passed 96→192→384 angular checks and independent
native/FEMM spatial refinement. Default-native total at 3000 rpm was
64.563 mW versus finest-FEMM 64.317 mW, a 0.384% difference. The reduced matrix
also completed SPM no-load and flat-IPM loaded working-mesh comparisons at
1500/3000 rpm. See the [current status](ROTOR_IRON_LOSS.md#numerical-evidence).

At the release decision the FEMM loaded-flat finer history was incomplete,
and flat no-load reference collection was still queued. Native collection was
complete. These incomplete controls and assembled public-path/platform loss
qualification remain future work in [#330](https://github.com/coilemdev/coilem/issues/330),
not implicit passes or 0.5.9 merge gates.
Preserve the registered protocols, frozen sources, raw fields and verdicts.
Do not relabel them as measurements of the integrated release candidate.

The follow-up retains the reduced plan: SPM 8p/12s at 0/20 A peak and flat-IPM
8p/12s FSAE at 0/50 A peak, both evaluated at 1500/3000 rpm. Reuse converged
SPM meshes; check one working/finer loaded flat-IPM pair independently in each
solver. Retain two successive angular checks, component-wise convergence
max(5% of finer, 0.001 W), native/FEMM agreement max(10% FEMM, 0.001 W), and
independent closure maximum 1e-6 T / RMS 1e-7 T. No tolerance is relaxed by
deferring qualification. Existing FEMM collection remains bounded to two workers.

## Historical records

- [First sampling slice and analytical contract](ROTOR_IRON_LOSS_PILOT.md).
- [Fixed-material native pilot](benchmarks/rotor-fixed-material-306-20261116.md).
- [Public-path rehearsal](benchmarks/rotor-public-integration-306-20261116.md).
- [Original release-base diagnostic](benchmarks/rotor-59-landing-306-20261116.json).

These records retain their measured source identities and earlier decisions;
the release boundary above governs the current integration work.
