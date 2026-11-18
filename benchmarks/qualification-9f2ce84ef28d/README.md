# coilEM 0.5.9 numerical qualification

The release owner approved this baseline on November 18, 2026. The candidate
was measured at `9f2ce84ef28de3d732b0fa5a880822c677b671c1`, whose source tree
matches the release-branch merge `81ff84dd`. The collection used the frozen
references for [protocol 1.12.0](../ag-v1.12/README.md).
[GitHub Actions collection](https://github.com/coilemdev/coilem/actions/runs/44396810368)

| Platform | A–G cases | Phase G | Prius software checks |
| --- | --- | --- | --- |
| Windows x64 | 84 pass, 1 planned unsupported | 16/16 | 10/10 |
| macOS arm64 | 84 pass, 1 planned unsupported | 16/16 | 10/10 |

The 69 shared A–F cases retain their requests and verdicts. Every comparable
metric from the shared cases and Prius collection stays within the prior
approved baseline's replay tolerances. Compared with 0.5.8, the only cases
outside those tolerances are the six V-shape fixtures previously reviewed
after the corner mesh refinement.
[Prior baseline comparison](prior-baseline-comparison.json)

The separate Prius software suite covers 17 jobs and 568 field positions per
platform. The ORNL Prius hardware case remains unsupported. Phase G checks
stator iron and specified-wire DC copper losses. Rotor iron loss and complete
motor efficiency remain experimental.

- [Approval and exact source identities](qualification.json)
- [Windows A–G report](windows-x86_64/report/benchmark_report.md) and
  [Prius report](windows-x86_64/prius/app-results.md)
- [macOS A–G report](macos-arm64/report/benchmark_report.md) and
  [Prius report](macos-arm64/prius/app-results.md)
- [Strict release gate result](release-qualification.json)
- [Public report hashes and path redactions](publication-projection.json)
