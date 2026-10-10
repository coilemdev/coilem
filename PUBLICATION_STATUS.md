# Release status

The release is **coilEM 0.2.0 Developer Preview**, with **Magneto2D 0.3.2**.
Its numerical qualification is the published [A/B/C/D benchmark report
v1.1](benchmarks/main-20261009-bad71d9/benchmark_report.md): SPM and
flat-buried IPM motors are qualified, and V-shape IPM remains experimental.
It is source software without an installer. Passing CI does not establish
engineering accuracy or a supported operating-system matrix.

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
