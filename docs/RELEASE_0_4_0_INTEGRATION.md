# v0.4.0 integration after the measured candidate

The release stack is **#146 -> #147 -> #148 -> #149**. Every later head includes
the preceding heads and preserves the original PR commits. #146 targets `main`;
#147 targets `fix/concentrated-type-layers` (#146), #148 targets
`fix/wound-teeth-hidden-note` (#147), and #149 targets
`fix/thinner-field-axis-arrows` (#148). Each PR therefore shows its own changes.
Merge from #146 upward with merge commits. After a predecessor lands, retarget
the next PR to `main` and require its checks before merging. Also require the
combined stack's CI and package acceptance before releasing. The top branch
remains the complete stack for local testing.

| PR | Scope | Review follow-up |
| --- | --- | --- |
| #146 | Repair layers and parallel paths when changing winding type | Check the actual submitted configuration, save/reopen and a native smoke solve |
| #147 | Winding guidance and experimental example labels | Describe coilEM's supported layouts without implying a physical impossibility |
| #148 | Field-axis arrows, tooltip and stator-field progress | Check progress, cancellation, error visibility and retention of completed results |
| #149 | Named runnable model workflows and deferred coverage presentation | Recompute completed-model summaries from retained evidence before accepting resume |

## Numerical evidence retained

The original measured candidate is
`4b88c4e1687acd6c40d37af2ee4d33348824734e`, application 0.4.0 and
Magneto2D 0.3.3. Its complete external qualification collection is sealed;
its original freeze, source archive, reports and measured identities stay intact.

- Windows: all 35 supported A/B/C/D jobs complete; 28 PASS, 1 YELLOW and one
  unsupported legacy ORNL Prius row. All 42 BLDC gates pass. Every recorded
  physical value, verdict, gate and waveform equals the preceding Windows run.
- macOS: the complete same selection passes its existing checks and matches
  the Windows candidate for all 30 rows under the unchanged published platform
  tolerance policy. [The native workflow](https://github.com/coilemdev/coilem/actions/runs/39255621550)
  retains the measured run identity. These values are not bit-identical to Windows.
- Pyleecan Prius: 17 jobs, 568 audited field reports and 10/10 software checks
  pass. Complete physical results match the preceding registered collection;
  torque-angle points, angular and mesh controls and discrepancies are retained.
- [Candidate CI](https://github.com/coilemdev/coilem/actions/runs/39209236686) and
  [all four wheel targets and installed acceptance](https://github.com/coilemdev/coilem/actions/runs/39255624955)
  passed on that candidate. Local production-wheel browser and native probes
  are retained in its qualification evidence.

The original freeze SHA-256 is
`db9e87b28560f17e95f4ba7ba2c828f74779a6f1c6f361b77121de482c8ae296`.
The sealed qualification manifest SHA-256 is
`f2befe8dca6d014c58a0eb61823e24465894ed589fd64ef2b311a17104f515a7`.
Retain the full evidence as release assets with these identities. The packaged
historical macOS record still has its original source guard; the current full
macOS record is separate external evidence. Do not restamp either one.

## Validation for the integration candidate

The reviewed changes leave all 53 registered physics files, native sources,
materials, numerical requests, reference bundle, numerical grids, limits and
runtime dependency locks unchanged from the measured candidate. The frontend
changes and the version 1.5.1 report presentation still need their own validation.
Reuse the numerical evidence through an explicit source/input identity comparison;
do not describe it as freshly measured on the integration commit.

Before accepting the new candidate:

1. Require the combined stack's Python, frontend, browser, native and dependency
   checks. Exercise #146's edited winding request and #148's stator-field progress,
   cancellation and error paths, including save/reopen and completed results.
2. Compare the final integrated physics sources, material/reference data, requests,
   grids, gates and runtime locks to the measured candidate. A changed numerical
   input or physics source needs review and the affected numerical reruns.
3. Record the new clean candidate commit and tree in a new external freeze receipt.
   Keep the original sealed freeze. A post-merge commit with an identical source
   tree can be linked explicitly, without rewriting the measured records.
4. Build the exact accepted candidate's release wheels with `publish=none`, review
   all platform acceptance jobs and repeat the installed production-UI walkthrough.
5. Record the reused numerical evidence and the new candidate's own CI, package
   and UI results in an integration qualification addendum before the owner release
   decision. Preserve the V-shape YELLOW, deferred ORNL hardware coverage for v0.5.0,
   historical Honda identities, and unmeasured Linux/Python-runtime numerical scope.

No full numerical recollection is required solely for this reviewed frontend and
reporting stack when the identity comparison passes. Publication and tagging remain
separate release decisions under the [release plan](RELEASE_0_4_0.md).
