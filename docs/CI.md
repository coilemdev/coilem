# CI feedback and coverage

Ordinary PRs and pushes to `main` select jobs from the complete Git diff. The
selector defaults to running all checks for an unknown path or missing history;
renames include both the old and new paths. It does not rely on GitHub's
paginated changed-file API. Publication validation and lint run independently,
including for documentation-only changes. Qualification retains its separate
physics/evidence gate.

| Changes | Python + Windows cancellation | Frontend build/audit | Browser workflows | Native job | Python/Rust audit |
| --- | --- | --- | --- | --- | --- |
| Frontend only | No | Yes | Yes | No | No |
| Backend, Python tests/tools | Yes | No | Yes | No | No |
| Rust sources | Yes | No | Yes | Yes | Yes |
| Dependencies, packaging, workflows, unknown paths | Yes | Yes | Yes | Yes | Yes |
| Markdown / snapshot manifest only | No | No | No | No | No |

PR runtime coverage uses Ubuntu 24.04 and Windows with Python 3.11. Release
branch pushes, nightly runs and full manual dispatches run all checks and also
include macOS/Python 3.11 and Ubuntu/Python 3.15. Python dependency, packaging,
Python support policy and CI workflow changes also select that broader runtime
matrix on PRs. The release-wheel workflow retains installed-package acceptance
on all four supported platforms and all five Python versions (3.11–3.15).
That separate workflow still runs on its packaging-related PR paths, manual
rehearsals and release tags; ordinary source-only PRs do not trigger it. Draft PRs skip ordinary jobs;
qualification's existing draft policy is unchanged. Manual performance-only
acceptance still runs only its own acceptance job.

## Parallel Python audit

Use `python -m pytest -q tests -n 2 --dist loadfile` after installing `.[dev]`.
Two processes bound memory and avoid multiplying native worker pools excessively.
Tests within each file stay on one worker to retain existing module lifecycle
assumptions. The separate Windows cancellation regression job remains serial.

The audit found that real HTTP servers request ephemeral ports (`bind(..., 0)`);
fixed port literals in other tests are mocked or in-process `TestClient` URLs.
Existing filesystem writes use temporary directories. Process-global monkeypatches
are isolated by worker processes and restored by pytest. The shared default
`COILEM_USER_DATA_ROOT` was a risk: an autouse fixture now gives every test its
own temporary user directory, also inherited by spawned processes. Individual
tests can override the environment to exercise explicit storage paths. This
also prevents local tests from writing to real user data.

The seven allowed-cancellation security cases previously used a fake solver
that set its cancellation flag but never released its fake solve lane. Each
case therefore waited the production 60-second timeout. The fake now releases
its lane and the tests assert the completed cancellation response, removing
seven minutes of artificial waiting per environment. Production cancellation,
release-wait timeout tests and launcher shutdown regressions are unchanged.

## Caches and browser shards

Pip caches are keyed by Python/runtime requirements and development dependency
metadata. npm caches use the frontend lockfile. Cargo caches include OS,
architecture, the exact Rust/LLVM compiler fingerprint, lockfile and sources;
Cargo still checks/builds the requested artifacts. Playwright browser downloads
use OS/architecture and the frontend lockfile. Browser system dependencies are
installed even on a browser-cache hit. Measurement workflows and qualification
publication are unchanged.

The release workflow suite has three shards and progressive design has two.
Each job owns one backend and one browser worker, so no app receives concurrent
solves. Playwright test-level sharding keeps explicitly serial groups together.
All tests remain selected; no tests are quarantined or automatically retried.
Timing JSON is retained even on success to measure the slowest shard.
The capstone completion regression checks the automatic 3D reveal, then switches
to 2D for its remaining stale-result checks; continuously rendering software
WebGL had exhausted its CI time budget before the final completion timer.

Progressive tests use the public `/?new=1` shortcut. It initializes the same
blank New Design workspace before the first render and consumes the query
parameter. Normal startup and File → New Design are still covered separately.
The shortcut avoids constructing the animated landing WebGL scene, without
mocking motor configuration or numerical requests.

The 15-minute feedback objective still needs hosted-run measurements, including
cold and warm caches. Local timings alone cannot establish Windows reliability
or CI performance. Issue #234's installed-wheel interruption case remains an
explicit release concern; passing source-run cancellation tests is insufficient
to close it.

The reference-recovery regression now holds completed worker processes with an
explicit event wait until controller cleanup terminates them. Its former
one-second atexit sleep allowed an early worker to exit before the other result
arrived, making the assertion depend on runner scheduling.
