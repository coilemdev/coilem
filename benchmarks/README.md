# Benchmark reports and protocols

Start with the [current next-release baseline v1.2](release-baseline-20261011-v1.2/README.md)
and [default A/B/C/D run commands](abcd-v1.1/README.md). The selected matrix has
29 PASS and one planned coverage item (numerical status UNSUPPORTED).

| Record | Role | Matrix / measured candidate |
| --- | --- | --- |
| [Baseline v1.2](release-baseline-20261011-v1.2/README.md) | Current selection for the next release | Protocol 1.1.0; compiled measurements at `45e0a5c` and `af56962` |
| [Higher-output IPM qualification](ipm-high-output-20261011-af56962/README.md) | Source evidence for the two replacement designs | Two cases at `af56962`, with fresh matched FEMM |
| [October 10 macOS rerun](main-20261010-45e0a5c-rerun/README.md) | Archived protocol 1.0.0 run; source evidence for unchanged v1.2 rows | `45e0a5c`; original two FAILs retained |
| [Snapshot report v1.1](main-20261009-bad71d9/README.md) | Archived fresh-reference run and 0.2.0 preview qualification record | `bad71d9`; original two FAILs retained |
| [Protocol 1.0.0](abcd-v1/README.md) | Explicitly selectable historical suite | Original low-output IPM fixtures and saved references |

V1.2 supersedes the old matrix as the **default benchmark selection**. It is
not a new complete run at one release commit, so it does not replace the
earlier preview qualification claim. Run the default command on the next
release checkout to produce that evidence.

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
