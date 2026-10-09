# Local verification record

The 2026-10-09 UTC rehearsal used macOS 15.7.3 arm64, Python 3.12.13,
Node.js 25.2.1, Rust/Cargo 1.94.0 and Gmsh 4.15.2. This is one tested local
platform; it does not establish support for every operating system.

| Check | Result |
| --- | --- |
| Exported Python suite | 249 passed; one Starlette/httpx deprecation warning |
| Native Rust suite | 246 passed; optimized solver build passed |
| Frontend contracts, types, production build and bundle audit | Passed |
| Real Chromium release rehearsal | 2 passed |
| Publication content, lint and first-party identity scans | Passed |
| Python, npm and Rust dependency audits | No known vulnerabilities reported |

Rust's dependency audit still reports the unmaintained `paste` 1.0.15 package.
The audit results describe the databases and locked dependencies checked on this
date; they are not a guarantee that undiscovered vulnerabilities are absent.

The browser rehearsal exercises a real local backend and native solver: reopen a
saved design, complete Standard sinusoidal and ideal six-step solves, download
PDF/CSV/replay reports, navigate comparison and history, and cancel a later run
while retaining completed results. It also rejects an untrusted-origin cancel
request and holds a geometry preview pending while testing restored solve controls.

Isolation regressions cover inherited native options, shaft material overrides,
request-derived armature settings and retained solver provenance. A separate
process test confirms that a deliberately altered Gmsh configuration does not
change the motor mesh. The public API tests cover loopback Host/Origin checks,
artifact/run path handling and output escaping.

Additional Chromium recovery checks started the UI before the backend, stopped
and restarted the backend while retaining an edited diameter, and loaded the UI
with the backend already running. A controlled full-workspace fixture rejected
a new solve, preserved the run when deletion was cancelled, and restored capacity
after confirmed deletion. These checks produced no page errors. The direct API
now returns the same actionable storage-limit guidance as the streaming API.

[Numerical evidence](NUMERICAL_EVIDENCE.md) gives measured torque comparisons,
waveforms, frozen acceptance gates, request payloads and an analytical field
check. Build and browser tests do not establish motor accuracy.

The source revisions in this record belong to the private development repository;
they identify provenance and are not available as public Git commits.
The main browser rehearsal used the runtime exported from source `763b9d25`.
The recovery rehearsals include the direct-API storage correction from
`c63dd8bf`. The final Python suite covers the CLI precision fix from `65c340f5`,
with a subsequent test-only fixture correction to use the public bundled steel.
Preset wording changes do not change the solve flow. The numerical report keeps
its frozen snapshots and follow-up measurements separate; different commit
hashes are not interchangeable qualification records.

Before publishing a release, pin the actual public commit and verify its new
repository metadata, private vulnerability-reporting route and hosted CI runs.
CI specifies Python 3.11 and Node 24 and includes Windows, macOS and Linux jobs;
those hosted runs are separate from this local record. The complete interactive walkthrough and full numerical qualification remain
pending; the automated recovery checks above cover backend reconnection and
configured workspace-capacity recovery.

The original high-pole comparison exposed truncated CLI angles at exact
six-step commutation boundaries. The adapter now preserves full floating-point
precision. Boundary regressions pass; the numerical evidence retains the
original failure and distinguishes fresh measurements after the correction.
