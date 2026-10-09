# Security Policy

## Supported release

Security fixes are considered for the latest published coilEM developer
preview. This project is provided without a support SLA or guaranteed response
or fix deadline.

## Report a vulnerability privately

Do not open a public issue for a suspected vulnerability. Use GitHub's private
vulnerability-reporting form for this repository:

<https://github.com/coilemdev/coilem/security/advisories/new>

Include the affected coilEM version and commit, operating system, reproduction
steps or proof of concept, expected impact, and any suggested mitigation. Avoid
including real secrets or data belonging to someone else.

If the private form is unavailable, do not disclose the report in GitHub
Issues. Repository publication is blocked until maintainers verify that the
private reporting route is enabled.

## Public bugs and usage questions

Non-sensitive defects and questions belong in
[GitHub Issues](https://github.com/coilemdev/coilem/issues). See
[SUPPORT.md](SUPPORT.md) for the information that makes a report actionable.

The public runtime is designed to bind only to loopback and make no default
outbound requests. Reports about unexpected network access, path traversal,
unsafe artifact handling, dependency compromise, or exposure of local run data
should be treated as security reports.
