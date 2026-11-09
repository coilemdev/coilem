# Windows FEMM results for release v0.5.6 — draft

The **46 completed fresh A–D FEMM reference cases reproduce all 26,633 physical
numeric values exactly**: zero changed values and zero maximum absolute or
relative delta. **Current native-vs-FEMM grading and fresh F results are pending.**
This draft establishes reference reproduction, not a current native accuracy verdict.

The measurements are pinned to [`8b6b394f8a5b3408d07c1ff00c7c32f012fd0373`](https://github.com/coilemdev/coilem/commit/8b6b394f8a5b3408d07c1ff00c7c32f012fd0373).
The publication branch starts at [`11aa06b1aa45ceac7d3d1b7cd75fa96463b0c894`](https://github.com/coilemdev/coilem/commit/11aa06b1aa45ceac7d3d1b7cd75fa96463b0c894),
which includes a later E/F Newton fixture amendment. The original F requests at
the measurement pin select Picard; this run does not measure the later Newton
fixture changes. Application versions and benchmark protocol versions
are distinct identifiers.

## Current evidence

| Evidence | Verified result |
|---|---|
| Fresh A–D FEMM reference reproduction | 46/46 cases exact; 26,633/26,633 physical numeric values exact |
| Phase coverage | A: 19, B: 20, C: 4, D: 3 |
| Complete result comparison | 46/46 exact after the eight explicit timing/location exclusions below |
| Current native-vs-FEMM A–D grading | **PENDING** full reference seal and grading |
| Fresh F references, reproduction and native grading | **PENDING** collection, verification and grading |
| Full dataset seal | **PENDING** |

The comparison excludes only these timing/location fields, where present:
`solve_metadata.postprocess_source_cache_dir`, `solve_metadata.postprocess_time_s`,
`solve_metadata.solve_cache_dir`, `solve_metadata.solve_time_s`,
`solve_metadata.solver_cpu_time_s`, `solve_metadata.timestamp`, `solve_time_s`,
and `summary.solve_time_s`. No physical numeric field is excluded. Values are
compared without fitting, rounding, filtering, interpolation, sign changes or
angle alignment. The companion JSON includes per-case comparison counts.

References remain **REVIEW_REQUIRED**. This documentation does not approve or
promote a reference bundle, change gates, or promote release qualification.
No fresh native measurement or active F metadata was read for this draft.

## Historical v0.5.1 and v0.5.5 context

| Application tag | Tag commit | Actual measured native commit | Guarded tag bridge |
|---|---|---|---|
| v0.5.1 | `5a3e80a0a91c715ad6268cfb7caedde3e8ffa427` | `a4f9f4dccf2ba3aad530e7bd1604ece8eeaca86f` | 64 files, zero hash mismatches |
| v0.5.5 | `63c7f2b0911871954c6aac9522ab6ad8e7dee9f3` | `34de0f4ca1604311f15edf6fb49b5a2a1bf27909` | 69 files, zero hash mismatches |

The bridges establish equality of the retained guarded physics files only.
They do not represent new solves at the tags or equality of every repository
file. The v0.5.5 tag is distinct from its measured `34de0f4` commit.

Both historical A–D comparisons have **46 PASS + 1 unsupported** and
**336/336 PASS gates** under protocol 1.6. The unsupported case is the ORNL
2004 Prius IPM. An independent bounded recheck found all **52 published native
waveform-stage sets exactly equal** between the historical runs. The v0.5.1
overnight run solved 46 fresh FEMM cases; PR218/v0.5.5 reused the same unchanged
published reference bundle rather than producing a second fresh FEMM collection.

The historical largest non-nearzero mean-torque error is **7.0224%**; the largest
back-EMF fundamental and peak errors are **8.6062%** and **9.8069%**, all PASS.
The worst near-zero absolute torque difference is **0.00201519 Nm**, below its
registered **0.01 Nm** PASS floor. These are historical native accuracy results,
not the pending current native verdict.

Historical F at `34de0f4` has **10 PASS / 60 PASS gates**, with worst loaded-torque,
back-EMF fundamental and peak errors of **0.86234%**, **0.31201%** and **0.35872%**.
Both half-gap controls meet their strict-under-2% torque/fundamental limits.
The normal producer and 0.5 mm hub bulk-mesh variant retain separate source
identities: **COMPLETE_WITH_FLAGS / REVIEW_REQUIRED**, with the standard
single-producer contract unsatisfied. LRK original and refined checks each remain
**9 PASS / 2 FAIL**, with no waiver or reclassification. There is no matched
v0.5.1 F cohort, so this is not an F version comparison.

Historical experimental cogging also retains its flags: original references
**9 PASS / 3 FAIL**; selected finer references **10 PASS / 2 YELLOW**. It is
outside the current fresh A–D/F collection. No controlled version speedup is
claimed from these historical runs.

## Evidence and completion boundary

The [companion JSON](windows-femm-release-v056-20261109.json) contains only selected public metrics,
case identifiers, commit identifiers and evidence hashes. Private paths, raw
archives and full producer identities are omitted.

| Audited input | SHA-256 |
|---|---|
| Completed current A–D reference comparison | `03e5ea3908bba1e7f10843890a09abda87b0538b20253f87199b89e05ff7779b` |
| Historical v0.5.1/v0.5.5 comparison | `5c083c43a9df5443d185da6c252b95272d6d20c7b2893d334ff414317bdfa86b` |

This PR remains draft until the complete fresh collection, native grading,
sealed evidence and public report have been validated. Scientific FAIL, YELLOW,
unsupported and reference-mismatch outcomes must be preserved in the final report.
