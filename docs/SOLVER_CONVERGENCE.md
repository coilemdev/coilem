# Solver convergence

Results includes a **Solver convergence** block. The run PDF and CSV use the
same report, derived only from the run's recorded solver evidence.

The summary shows the accuracy plan, mesh density and element count, maximum
and median iterations, record coverage, and reused fields. Expand **Thresholds
and per-position records** to inspect each loaded and no-load rotor position,
the method, iterations and limit, final residual, stopping ratio and field reuse.
The CSV also preserves the raw per-position records and stage iteration counts.

## Residuals and warnings

- **Picard:** the final unrelaxed permeability mismatch, the maximum of
  `|mu_target(B) - mu_used| / mu_used` over steel elements. It is not multiplied
  by the relaxation factor. Its stopping ratio is this mismatch divided by
  the recorded tolerance.
- **Newton:** the final equation residual relative to that continuation stage's
  initial residual. Newton also accepts a sufficiently small RHS-scaled absolute
  residual. Its stopping ratio is the smaller of relative-residual/tolerance and
  RHS-scaled-residual/absolute-floor when the floor is recorded. A large relative
  residual alone therefore does not imply failure. The final residual describes
  the last accepted continuation stage; iteration counts cover all stages.

**Review convergence** appears when a position reaches **80% or more** of its
total iteration limit or any continuation stage's limit, or its final stopping
ratio is **greater than 1**. Picard and Newton residuals have different definitions
and are never combined into one worst residual.

Iteration maximum and median exclude reused fields and linear-material solves.
Reused fields retain their source's convergence evidence and warning checks.
Linear-material records are labelled **Linear solves**, without a nonlinear
warning for using their single iteration.

## Missing evidence and scope

Older runs without per-position evidence show **Not recorded**. Partial or
invalid records show **Incomplete records** rather than a green status. The
report never reconstructs residuals or limits from iteration counts, current
settings or historical aggregate metadata. An omitted no-load sweep does not
count as missing evidence.

Reading an old run does not rewrite it or regenerate its immutable exports.
Convergence describes the recorded loaded and no-load rotor sweeps; it does not
prove mesh convergence, physical accuracy, benchmark qualification, or the
convergence of a separately requested performance map.
