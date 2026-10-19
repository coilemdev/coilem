# Release status

The next release is being planned as **v0.4.0**. Its
[release plan](docs/RELEASE_0_4_0.md) and
[benchmark evidence report](benchmarks/v0.4.0/README.md) record the completed
Windows/FEMM runs and the outstanding scope, final-candidate, platform and
packaging checks. This preparation does not change the current package version
or mark the release as published.

The release is **coilEM 0.3.1 Developer Preview**, with **Magneto2D 0.3.3**.
Its numerical qualification is the published [A/B/C/D benchmark report
v1.1](benchmarks/main-20261009-bad71d9/benchmark_report.md). It qualifies the
tested SPM and flat-buried IPM combinations listed in [Validation](docs/VALIDATION.md#qualification-status);
V-shape IPM and untested combinations remain experimental.
Benchmark reports [v1.7](benchmarks/macos-rc-20261013-1fac3a1/README.md) (macOS) and [v1.8](benchmarks/windows-rc-20261013-1fac3a1/README.md) (Windows)
measure coilEM 0.3.0, `1fac3a1`, and retain every verdict on both platforms:
29 PASS, the planned unsupported Prius fixture and 42/42 BLDC gates. They do
not change the qualified scope. coilEM 0.3.1 adds Python 3.15 support and
leaves the application unchanged: on Python 3.11 to 3.14 it installs the same
dependencies as 0.3.0, so these reports apply to it.
It installs from PyPI with `uv tool install coilem`; see [Install](README.md#install)
for the platforms its wheels are built and tested on. Passing CI does not
establish engineering accuracy.

[Validation](docs/VALIDATION.md) records the qualified scope, evidence and
current limits. [Release notes](RELEASE_NOTES.md) describe the available workflows.
[Runtime settings](docs/RUNTIME_SETTINGS.md) explains the isolated native
process environment and public configuration names.

The source distribution includes no hosted service or FEMM implementation.
Elmer is disabled by default and requires a separately installed runtime and
an explicit development opt-in. Motor thermal requests are excluded.

The manifest records the original source export, listed public patches, and
current file hashes. It does not certify
numerical correctness or inspect repository history. Private vulnerability
reporting is enabled. Tagging a release requires pinning the public commit,
rerunning the A/B/C/D benchmark on it, and recording the platform walkthrough.
