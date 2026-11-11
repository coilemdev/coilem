# Protocol 1.10.0 qualification

Both platforms measured the clean candidate `70c5e3404c1962a811a915db292c31c28b92cf1a`. Each passes **68 supported cases and 468 gates**, plus one planned unsupported Prius suite row. The separate Prius run passes **10/10 software checks**, with 17 jobs and 568 field reports on each platform.

| Platform | A-F collection span | Sum of job wall times | Evidence |
| --- | ---: | ---: | --- |
| windows-x86_64 | 37m 06s | 117m 19s | [A-F report](windows-x86_64/report/coilem_benchmark_report.html), [Prius](windows-x86_64/prius/app-results.md), [workflow](https://github.com/coilemdev/coilem/actions/runs/42917477308) |
| macos-arm64 | 80m 52s | 209m 49s | [A-F report](macos-arm64/report/coilem_benchmark_report.html), [Prius](macos-arm64/prius/app-results.md), [workflow](https://github.com/coilemdev/coilem/actions/runs/42923836479) |

Collection span is earliest A-F shard start to latest finish, including queue gaps and Windows repair. It excludes setup, download and final report verification. Summed job time is not elapsed wall time.

All 47 A-D rows match the preceding record on their own platform within the existing replay tolerances. The new E and F cases are compared against the reviewed original source cohorts. In a separate cross-platform comparison, 69/69 macOS rows match the Windows record within replay tolerances. The [comparison summary](comparison-summary.json) lists the per-phase results and any replay differences.

| Largest difference versus FEMM | Windows | macOS |
| --- | ---: | ---: |
| E peak-to-peak | 5.880% | 5.913% |
| E first harmonic | 6.038% | 6.003% |
| F loaded mean torque | 0.862% | 0.862% |
| F back-EMF fundamental | 0.312% | 0.312% |
| F back-EMF peak | 0.359% | 0.359% |

The three refined E fixtures each pass all six gates on both platforms. Their individual errors and gate outcomes are included in the comparison summary.

[Original collection](https://github.com/coilemdev/coilem/actions/runs/42910700958) had two Windows worker-handle errors. The [outrunner repair](https://github.com/coilemdev/coilem/actions/runs/42915510381) and [cogging repair](https://github.com/coilemdev/coilem/actions/runs/42915717040) reused 17 completed jobs, retried only the two failed requests and preserved their meshes, grids, binary and gates. Worker concurrency was bounded for the retries. All A-F request/result hashes were verified and the complete platform results regraded independently with zero additional field solves.

The [qualification receipt](qualification.json) binds the suite, reviewed references, candidate, platform reports and verification receipts. This is software parity for the registered requests. It does not extend the application policy to arbitrary E/F inputs or make a hardware validation claim.
