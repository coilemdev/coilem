# coilEM 0.5.6 candidate qualification

Measured clean candidate: `e9eb89e818edf9a579c20e900a9ea93a0731ad28`; coilEM 0.5.6, Magneto2D 0.5.0. The exact versioned candidate was measured before this evidence publication commit.

Both recovered [PR workflow joins](https://github.com/coilemdev/coilem/actions/runs/42674975329) passed. Each platform has 46 supported A-D cases, 336/336 gates and 52 completed job stages, plus the declared unsupported generic ORNL fixture. Each Prius report has all 17 jobs, 568 audited field positions and ten software checks passing. All 69 guarded source hashes and the before-field grader snapshots verify.

| Platform | A-D report | Prius report |
|---|---|---|
| Windows x86-64 | [46 PASS / 336 gates](windows-x86_64/report/benchmark_summary.json) | [17 jobs / ten PASS checks](windows-x86_64/prius/app-results.json) |
| macOS arm64 | [46 PASS / 336 gates](macos-arm64/report/benchmark_summary.json) | [17 jobs / ten PASS checks](macos-arm64/prius/app-results.json) |

[Owner decisions](owner-decisions.json) approve unchanged FEMM references via the registered protocol 1.9 Newton-only bridge. The prior scoped acceptance of the same near-zero macOS Prius observation is retained: 0.030181329933354963 Nm, only -5.33e-13 Nm from the accepted v0.5.5 value. The immutable older anchor and every gate/tolerance remain unchanged. [Automatic review before acceptance](automatic-review-before-owner-decision.json), [full numerical comparison](comparison.json), and [verification receipts](verification.json) retain the evidence.

No A-D metric moved outside the registered replay tolerances against either the previous or approved baseline. No reference field, measured source identity, or approved anchor is replaced. E/F remain separate experimental diagnostics; inherited LRK and cogging findings are retained.

Summed A-D job process wall time in this recovered PR workflow is 78.44 minutes on Windows and 142.29 minutes on macOS. The independent complete fresh Windows repeat was 93.24 minutes ([run 42679561932](https://github.com/coilemdev/coilem/actions/runs/42679561932)); the PR's v0.5.5 comparison retains that repeat (220.74 to 93.24 minutes, 57.76% less) and the macOS collection (264.04 to 142.29 minutes, 46.11% less). These are single collections, not controlled repeated timing trials or elapsed parallel-workflow duration. Original failed attempts remain in CI artifacts.

The [qualification assessment](release-qualification.json) covers this frozen candidate. Main merge, version tagging, and TestPyPI/PyPI publication remain separate.

The public Mac summary and HTML replace only machine-specific `solve_cache_dir` paths using the existing repository redactor. [Transformation hashes](publication-transform.json) retain the original joined report identity; measured requests/results, numerical values, configurations, gates and verdicts are unchanged. The original full artifacts remain in the CI run.
