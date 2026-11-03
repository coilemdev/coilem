# Windows validation of the v0.5.0 stack

Measured candidate: `bb3d8aff93dd2b2c2900ac1b9c65729a939874f6`.
This evidence was collected on October 29, 2026, on Windows Server 2022
(AMD64, 8 vCPUs, 32 GB RAM). The publication commit adds evidence after that
measured pin; it does not describe a new field collection.

## Registered result

All **35 supported native jobs completed**, with zero execution errors.
The registered protocol **1.4.0** evaluation against the original frozen FEMM
v3 reference bundle records **29 PASS and one planned UNSUPPORTED** row:

| Phase | PASS | UNSUPPORTED |
| --- | ---: | ---: |
| A — SPM | 10 | 0 |
| B — IPM | 12 | 0 |
| C — Distributed winding | 4 | 1 |
| D — BLDC | 3 | 0 |

All **42 BLDC gates passed**. The legacy `ornl_prius_2004_ipm` row remains
unsupported; it is distinct from the separate Pyleecan software benchmark.
The 30 report rows aggregate 35 native jobs, including BLDC control jobs.

The registered collection ran from **18:58:26 to 21:45:53 UTC**, taking
**2 h 47 min 26.6 s**. This is an observed VM duration, with no controlled
same-hardware performance comparison. The protocol 1.4 compatibility bridge
retains the frozen reference and numerical gates while allowing the native
nonlinear iteration cap to rise from 100 to 200.

- [Complete numerical report](benchmark_summary.json): all registered rows,
  evaluations, waveforms and measured runtime identity.
- [Completion and per-job hashes](completion-summary.json): 35 verified
  request/result pairs and the source identity checks.
- [Publication provenance](provenance.json): raw and published hashes and
  the hash of the complete local archive.

## Fresh FEMM diagnostic

The same native fields were also evaluated against the newly collected FEMM
4.2 (21Apr2019) reference candidates. That diagnostic records **28 PASS,
1 YELLOW and 1 UNSUPPORTED**, with no additional native field solves.
The sole changed verdict is `ipm_vshape_8p12s_pocket_offset_contract`: peak
back-EMF error changes from **9.806929874448405%** against the frozen reference
to **10.383485630337862%** against the reconstructed reference. The existing
10% green / 15% yellow limits are unchanged.

The [full diagnostic](fresh-femm-diagnostic.json) retains the comparisons and
gates. Those reference candidates remain **REVIEW_REQUIRED** because the
historical sealed adapter was reconstructed. This report does not promote
them or replace the frozen reference bundle.

## Collection integrity and remaining release work

The first collection attempt stopped when a Gmsh/FLTK preferences write
made the source checkout dirty. Nine completed jobs and the failed job were
preserved separately. After preventing that write, the registered collection
was restarted in a fresh output directory at the same source pin. Source
identity was verified before and after every completed job; the checkout was
clean afterward and its original permissions were restored. No numerical
gate was skipped or relaxed.

The completed archive contains 202 hash-verified files, including raw job
requests/results, logs and rendered reports. This public text package
retains the numerical report and integrity summaries. Machine-local path
strings are redacted; numerical values, verdicts, gates and hashes are
unchanged. Private reference-adapter source and VM access details are kept
outside this package.

[Local validation](local-validation.json) at the measured combined stack pin
records **1,421 Python tests passed and 21 failed**, **265 Rust tests passed**,
and successful Python lint, dependency checks, frontend build and dependency
audit. The 21 failures are the documented pre-freeze evidence and measured
physics identity guards; they remain unresolved and have not been repinned
as part of this publication. These are combined-stack results, not a claim
that each intermediate branch had a full test run.

This is development regression evidence for the existing matrix.
[Protocol 1.6.0](../abcd-v1.6/README.md) adds 17 cases and requires 46 supported
FEMM reference records. Its shoed-slot, temperature and loaded d/q coverage
and the final freeze/qualification evidence remain pending. No platform
qualification record, qualification basis, release version or threshold is
changed here.
