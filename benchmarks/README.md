# Benchmark reports and protocols

Start with the [latest full Windows report v1.4](windows-process-pools-20261012-02fa24b/README.md)
and [default A/B/C/D run commands](abcd-v1.1/README.md). The selected matrix has
29 PASS and one planned coverage item (numerical status UNSUPPORTED), with
42/42 BLDC gates. This is a fresh native rerun at `02fa24b` against frozen FEMM
data, including the solver and Windows process-pool improvements; no reference
solves were executed. The generated PDF is included in the evidence package.

| Record | Role | Matrix / measured candidate |
| --- | --- | --- |
| [Windows report v1.4](windows-process-pools-20261012-02fa24b/README.md) | Latest complete run; all 30 verdicts and 42 BLDC gates retained, with exact native waveforms across 35 jobs | Protocol 1.1.0; fresh native fields at `02fa24b`, frozen FEMM references |
| [Windows report v1.3](main-20261012-0b463b3-rerun/README.md) | Previous complete run; baseline before later performance changes | Protocol 1.1.0; fresh native fields at `0b463b3`, frozen FEMM references |
| [Baseline v1.2](release-baseline-20261011-v1.2/README.md) | Archived compilation defining the current fixture selection | Protocol 1.1.0; compiled measurements at `45e0a5c` and `af56962` |
| [Higher-output IPM qualification](ipm-high-output-20261011-af56962/README.md) | Source evidence for the two replacement designs | Two cases at `af56962`, with fresh matched FEMM |
| [October 10 macOS rerun](main-20261010-45e0a5c-rerun/README.md) | Archived protocol 1.0.0 run; source evidence for unchanged v1.2 rows | `45e0a5c`; original two FAILs retained |
| [Snapshot report v1.1](main-20261009-bad71d9/README.md) | Archived fresh-reference run and 0.2.0 preview qualification record | `bad71d9`; original two FAILs retained |
| [Protocol 1.0.0](abcd-v1/README.md) | Explicitly selectable historical suite | Original low-output IPM fixtures and saved references |

V1.2 defines the **default benchmark selection**. V1.3 and V1.4 rerun that same
selection at clean candidates on Windows, preserving the inputs, references and
gates. V1.4 records 44.66 minutes of native execution, compared with 176.62 minutes
in V1.3. All physical summary values match exactly except steel RMS accumulation
rounding below 6e-14 T. These runs retain the existing numerical metrics without
broadening application qualification. Later commits require their own measured run.
Concurrent workloads during v1.3 limit direct performance comparisons; see its
[timing record and caveat](main-20261012-0b463b3-rerun/execution-timings.json).

## Why the archive folders remain

The default protocol still reads unchanged input fixtures, BLDC protocols and
golden vectors from `main-20261009-bad71d9`. The compiled v1.2 report links
unchanged measured rows and fixtures in `main-20261010-45e0a5c-rerun`. Tests
also replay the original failed cases. These folders are dependencies and
traceable historical records, not incompatible copies of the current report.
Deleting or moving them would break registered paths, source hashes and links.

The original low-output deep-apex and wide-angle cases are excluded from the
default suite. Reproduce them with the explicit historical suite and bundle
in the [protocol 1.0.0 commands](abcd-v1/README.md).

See the [IPM diagnosis and issue status](../docs/IPM_BENCHMARK_DIAGNOSIS.md)
for the causes found, the replacement results and the remaining solver work.
