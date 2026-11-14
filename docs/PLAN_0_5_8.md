# 0.5.8: no solver changes, faster everything else

This is the expanded **0.5.8** scope, before publishing the release to PyPI.
Work starts from current `main`. Open implementation PRs as drafts; run local
checks before enabling CI. Sector models (#222 / draft #242) belong to **0.6.0**.

## Qualification constraint

Keep every registered physics source unchanged, including `MotorConfig`, the
geometry builders and the native solver. Dependency pins for physics libraries
and benchmark contracts also affect qualification. Check each PR with
`tools.physics_impact` and the strict evidence gate; a UI label alone does not
establish that settings match qualification. Reuse the approved 0.5.8 evidence
only when those checks pass. New tooth or slot styles need fresh qualification
and are outside this scope.

## Implementation order

1. **Faster CI, first.** Select jobs from changed paths; audit shared test state
   before using two pytest workers; cache Cargo, pip, npm and Playwright; use
   Ubuntu/Windows on PRs and the complete matrix on release branches/nightly.
   Split browser tests across isolated backends and avoid repeatedly mounting
   the animated landing scene in progressive-design tests. Investigate reference
   recovery and Windows interrupt #234 failures without hiding failed checks.
   Target roughly 15 minutes of typical PR feedback; measure actual runs before
   claiming that target is met.
2. **Saved solve profiles (#127).** Continue draft #293 with named existing
   accuracy, mesh, step/sweep, advanced options, analyses and operating-point
   settings. Add Quick look, Design iteration, Report quality, Cogging study and
   Torque–speed map presets with estimates. Store user profiles separately from
   the motor config and carry them inside `.coilem` metadata. Show a qualification
   match badge only for the exact benchmark settings; identify custom profiles.
3. **Compare 2.0, the headline.** Show differing inputs and profiles, compare
   3–6 runs with a pinned baseline, and add losses/efficiency, Ld/Lq and d/q,
   Kt/Ke, cogging, torque–speed and side-by-side field views. Add Results →
   compare with previous run, CSV/PDF export and optional API-backed studies.
4. **API and studies.** Provide `import coilem`, a solve CLI accepting a design
   and profile, a schema route, consistent errors, validation matching solve
   acceptance, compact results and smaller scratch usage. Add the batch/study
   endpoint used by Compare. Keep existing launcher compatibility explicit.
5. **UX and release QA.** Verify or fix tutorial reload progress (#259), Halbach
   3D fitting (#265), example torque–speed bus defaults (#274), two-layer tooth
   coil wording (#102), and opening a design during guided setup. Reuse a
   repeatable UI QA pass before the release.

The Windows installed-wheel interrupt hang (#234) and V-shape convergence
(#285) remain open. A CI optimization must not label either issue fixed without
reproducing and validating the relevant behavior. Changes to numerical mesh
behavior would require reconsidering the qualification constraint above.
