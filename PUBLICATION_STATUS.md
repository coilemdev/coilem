# Release status

The proposed release is **coilEM 0.2.0 Developer Preview**, with **Magneto2D
0.3.2**. It is experimental source software; exact-candidate motor numerical
qualification remains pending. Passing CI does not establish engineering
accuracy or a supported operating-system matrix.

[Validation](docs/VALIDATION.md) records the evidence requirements and current
limits. [Release notes](RELEASE_NOTES.md) describe the available workflows.
[Runtime settings](docs/RUNTIME_SETTINGS.md) explains the isolated native
process environment and public configuration names.

The source distribution includes no hosted service or FEMM implementation.
Elmer is disabled by default and requires a separately installed runtime and
an explicit development opt-in. Motor thermal requests are excluded.

The manifest records the original source export, listed public patches, and
current file hashes. It does not certify
numerical correctness or inspect repository history. Final publication requires
maintainer review of the numerical evidence, platform checks, security reporting
route and the actual public commit.
