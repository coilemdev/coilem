# Developer-preview validation

The proposed release is coilEM 0.2.0 with Magneto2D 0.3.2. This repository is
an experimental source preview with numerical qualification still pending.
Passing CI does not establish numerical accuracy or authorize a release.

See [Numerical evidence](NUMERICAL_EVIDENCE.md) for measured comparisons and
[Local verification](VERIFICATION.md) for the build, browser and audit record.
These records keep their tested runtime identities and remaining gates explicit.

## Published A/B/C/D benchmark

The completed [benchmark report v1.1](../benchmarks/main-20261009-bad71d9/benchmark_report.md)
measures public Coilem commit `bad71d9cbcb10bf2daa293c5577f9d9e26778a12`
with public native defaults against fresh, matched FEMM references. It is
evidence for that October 9 snapshot; it does not qualify a later `main` or
the final release commit. The [HTML report](../benchmarks/main-20261009-bad71d9/coilem_benchmark_report.html),
[numerical summary](../benchmarks/main-20261009-bad71d9/benchmark_summary.json),
and [evidence package](../benchmarks/main-20261009-bad71d9/README.md) retain
the exact fixtures, gates, runtime identities and reference provenance.

| Phase | Coverage | Recorded outcomes |
| --- | --- | --- |
| A - SPM | Ten sinusoidal operating points | 10 PASS |
| B - IPM | Twelve flat and V-shaped fixtures | 10 PASS, 2 FAIL |
| C - Distributed Winding | Four accepted fixtures and the rejected Prius fixture | 4 PASS, 1 UNSUPPORTED |
| D - BLDC | Three SPM fixtures; four stages and fourteen gates per fixture | 3 PASS; 42/42 gates |

The deep-apex IPM fixture fails mean-torque parity (36.02% difference).
The wide-angle IPM fixture fails Back-EMF H1 and peak parity (36.03% and
25.16%); its mean-torque gate is YELLOW (12.41%). These failures remain
part of the evidence. Phase D covers ideal six-step 120-degree wye BLDC;
thermal analysis is outside A/B/C/D. See [Numerical evidence](NUMERICAL_EVIDENCE.md#public-main-snapshot-benchmark-report-v11)
for the measured values and interpretation limits.

To measure a new checkout against the saved, audited FEMM data after the
documented Python and Rust setup:

```sh
python -m tools.run_benchmarks --phases A B C D --out-dir ../benchmark-output/my-run --pdf
```

The [versioned benchmark protocol](../benchmarks/abcd-v1/README.md) documents
resuming, reference integrity checks, native-only runs and macOS execution.
The command runs the current public native solver without a FEMM installation
or reference adapter. A changed fixture, material contract or protocol requires
new matched reference evidence. New native results against retained references
are identified separately from the original fresh-reference benchmark.

## Candidate identity

`snapshot-manifest.json` records the original source export, the listed public
patches, and the current SHA-256 and byte count of each distributed file. Each
patch entry identifies its public base commit and the file hash before that
patch; Git history records the corresponding changes. The public repository has its own commit history; private source history
is not transferred. A release must pin the public commit as well as this
manifest. Source archives and their checksums must be generated from that
same public commit.

Exporting source without its development history does not anonymize the public
repository's own commits. Before publication, review its author and committer
metadata, historical file contents, tags, release assets, and issue attachments
for unintended personal information or secrets. A clean current snapshot does
not prove that this earlier material is clean.

## Automated checks

The public CI workflow checks the snapshot manifest, publication contents,
Python dependencies, lint and exported tests on Python 3.11 across Windows, macOS and Linux,
the locked native solver build, real native-mesh sinusoidal and six-step smoke
solves, frontend contracts and production build, and native Rust tests. Dependency
audits cover the Python, JavaScript and Rust locks. A separate Chromium job
exercises real Standard sine/six-step runs, save/reopen, report downloads,
comparison, history and cancellation against an isolated local workspace.

These are build and behavior checks. The smoke tool uses a coarse, reduced
grid; its result is not a Standard-tier accuracy benchmark. Automated checks
on hosted runners do not constitute a supported operating-system matrix or a
complete interactive release walkthrough.

To run the browser rehearsal after the documented Python/native setup:

```sh
cd frontend
npm ci
npx playwright install chromium
npm run test:browser
```

Activate the backend virtual environment first, or set `COILEM_TEST_PYTHON` to
its Python executable. On Linux, install browser system dependencies with
`npx playwright install --with-deps chromium`, as CI does. The suite starts its own loopback servers on ports
54173 and 58000, writes disposable results below `frontend/test-results`, and
writes its HTML report below `frontend/playwright-report`.
The automated rehearsal covers part of the walkthrough below; it does not
replace numerical reference comparisons or manual recovery checks.

`verify_snapshot.py --publication` is a content check. It verifies the manifest
and the publication rules encoded in the tool; it does not inspect Git history,
validate the completeness of `public_patches`, enable private vulnerability
reporting, perform numerical qualification, or
grant release signoff. Those checks require separate evidence.

## Numerical and interactive release checks

The intended qualification path is the included 8-pole/12-slot inner-rotor
SPM example, M350-50A steel, native Gmsh meshing, Standard quality, and local
Magneto2D. Both sinusoidal and ideal wye-connected 120-degree six-step
excitation must be exercised from the pinned candidate. Standard describes
the interactive walkthrough. The preregistered numerical comparison in
`benchmarks/m350-launch/benchmark_spec.json` uses a custom full-electrical-cycle
grid: 96 positions at 3.75° over [0°, 360°). It is not the sinusoidal Standard
preset's base 180°/7.5° grid; the adapter promotes Standard Back-EMF/THD
runs to a full cycle when required.

Until numerical qualification is completed and recorded, all motor outputs are
experimental estimates and no motor path is release-qualified.

The release record must distinguish earlier source benchmarks from results
collected from this transformed candidate. Source results cannot silently be
relabelled as public-candidate evidence. The automated browser rehearsal is recorded in the local verification report.
Full numerical qualification and the remaining manual walkthrough checks are
still pending for the final release commit.

Every numerical candidate lane must request `weighted_stress` and record
`solve_metadata.torque_method = weighted_stress`. Missing extractor provenance
or a fallback method fails qualification even if numerical deltas pass. The
report shows the requested and actual methods separately.

The interactive walkthrough covers startup in both orders, Standard sine and
six-step runs, phase currents and commutation sectors, phase/line Back-EMF,
THD/harmonics, field playback, saved-run comparison, project save/reopen,
PDF/CSV/replay downloads, cancellation, backend reconnection, and storage-limit
recovery. Record the exact OS, architecture, Python/Node/Rust/Gmsh versions,
public commit, commands, and accepted limitations.

## Claim boundaries

- The published A/B/C/D report provides measured public-snapshot comparisons,
  including three SPM BLDC fixtures. Earlier source comparisons are separate
  supporting evidence. Neither establishes arbitrary-motor accuracy or
  replaces qualification of the final release commit.
- The public IPM comparison contains two failures, and distributed-winding
  coverage contains an unsupported fixture. Failed, yellow and unsupported
  outcomes must remain visible; this report does not qualify those motor
  families generally.
- Thermal, PWM and dynamic ESC behavior, IPM BLDC qualification, installers,
  and broad operating-system certification are outside this preview.
- No engineering certification, supplier-specific loss prediction, or
  thermal/safety suitability is claimed.

See [Release notes](../RELEASE_NOTES.md), [Materials](../MATERIALS.md), and
[Getting started](GETTING_STARTED.md). Report reproducible defects through
[Support](../SUPPORT.md), and vulnerabilities through [Security](../SECURITY.md).
