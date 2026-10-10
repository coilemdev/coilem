# Developer-preview validation

The release is coilEM 0.2.0 with Magneto2D 0.3.2, a source-built developer
preview. Its numerical qualification is the published A/B/C/D benchmark
report v1.1, which compares the native solver with fresh, matched FEMM
references. Passing CI alone does not establish numerical accuracy.

See [Numerical evidence](NUMERICAL_EVIDENCE.md) for measured comparisons and
[Local verification](VERIFICATION.md) for the build, browser and audit record.
These records keep their tested runtime identities explicit.

## Qualification status

The maintainers accept [benchmark report v1.1](../benchmarks/main-20261009-bad71d9/benchmark_report.md)
as the numerical qualification record for this preview. Qualification
applies to the tested combinations of rotor, winding and excitation below. A
combination is qualified when every registered v1.1 fixture for it passes its
FEMM parity gates. Failed and unsupported outcomes remain visible and are not
waived by the aggregate pass count.

| Rotor | Winding | Excitation | v1.1 fixtures | Outcome | Status |
| --- | --- | --- | --- | --- | --- |
| SPM | Single-layer concentrated | Sinusoidal | Phase A: ten operating points on 4-pole/12-slot and 8-pole/12-slot designs | 10 PASS | Qualified |
| SPM | Single-layer concentrated | Ideal six-step 120-degree wye (BLDC) | Phase D: 4-pole, 8-pole and 14-pole 12-slot designs | 3 PASS; 42/42 gates | Qualified |
| SPM | Two-layer distributed, full pitch or 5/6 short pitch | Sinusoidal | Phase C: 8p/24s, 8p/48s, 8p/48s 5/6-chorded, 12p/36s | 4 PASS | Qualified |
| Flat-buried IPM | Single-layer concentrated | Sinusoidal | Phase B: six fixtures | 6 PASS | Qualified |
| V-shape IPM | Single-layer concentrated | Sinusoidal | Phase B: six fixtures | 4 PASS, 2 FAIL | Experimental |
| Multi-layer IPM (Prius 2004 fixture) | - | - | Phase C | Rejected by the public policy | Unsupported |

The application also accepts combinations that v1.1 did not measure. They are
experimental:

- SPM with distributed windings under ideal six-step excitation;
- SPM with single-layer distributed windings;
- flat-buried or V-shape IPM with distributed windings; and
- Halbach, lessons and generic field mode, which are outside A/B/C/D.

Ideal six-step excitation is available for SPM only.

Qualified means agreement with FEMM within the registered gates for the
measured fixtures, under these conditions: Magneto2D 0.3.2, native Gmsh meshes
at the normal density used by the Standard plan, weighted-stress torque, the
bundled M350-50A curve, the public magnet grades and angular grids matched to
the reference.
The sinusoidal gates are mean torque within 8% (0.01 N m absolute for
near-zero references) and Back-EMF fundamental and peak within 10%. The BLDC
fixtures pass fourteen gates each, covering torque parity, commanded currents,
commutation sequence, angular refinement and low-current power balance.

The bundled **Example SPM 8p/12s** design uses a qualified combination
(SPM with a single-layer concentrated winding, under sinusoidal or six-step
excitation); it is not itself a registered fixture. Designs in a qualified
combination but outside the measured geometry range use the same solver path,
but their accuracy has not been measured individually. Check
mesh and angular convergence before relying on small differences.

The deep-apex V-shape fixture fails mean-torque parity (36.02% difference).
The wide-angle V-shape fixture fails Back-EMF H1 and peak parity (36.03% and
25.16%); its mean-torque gate is YELLOW (12.41%). The other four V-shape
fixtures pass. Treat V-shape results as experimental until a solver change
passes all six fixtures.

## Benchmark report v1.1

The completed v1.1 report measures public Coilem commit
`bad71d9cbcb10bf2daa293c5577f9d9e26778a12` with public native defaults against
fresh, matched FEMM references from the separately pinned reference commit
`8b95decda27d475ddbb75e99d92744ebc8e53b28`. The [HTML report](../benchmarks/main-20261009-bad71d9/coilem_benchmark_report.html),
[numerical summary](../benchmarks/main-20261009-bad71d9/benchmark_summary.json),
and [evidence package](../benchmarks/main-20261009-bad71d9/README.md) retain
the exact fixtures, gates, runtime identities and reference provenance.

| Phase | Coverage | Recorded outcomes |
| --- | --- | --- |
| A - SPM | Ten sinusoidal operating points | 10 PASS |
| B - IPM | Twelve flat and V-shaped fixtures | 10 PASS, 2 FAIL |
| C - Distributed Winding | Four accepted fixtures and the rejected Prius fixture | 4 PASS, 1 UNSUPPORTED |
| D - BLDC | Three SPM fixtures; four stages and fourteen gates per fixture | 3 PASS; 42/42 gates |

Phase D covers ideal six-step 120-degree wye BLDC; thermal analysis is outside
A/B/C/D. See [Numerical evidence](NUMERICAL_EVIDENCE.md#public-main-snapshot-benchmark-report-v11)
for the measured values and interpretation limits.

### Rerun on public main `45e0a5c`

The [rerun evidence package](../benchmarks/main-20261010-45e0a5c-rerun/README.md)
publishes this run's per-fixture results, gates, native inputs and runtime
identity, including the source and Magneto2D binary hashes. The v1.1 package
is unchanged.

On 2026-10-10 the same harness and protocol (1.0.0) measured public main
`45e0a5c7662ade04a4be5519b7e5bac771a6122f` on macOS 15.7.3 arm64 (Python
3.12.13, Gmsh 4.15.2) against the retained v1.1 FEMM references. It
reproduced every v1.1 verdict:

| Phase | v1.1 at `bad71d9` | Rerun at `45e0a5c` |
| --- | --- | --- |
| A - SPM | 10 PASS | 10 PASS |
| B - IPM | 10 PASS, 2 FAIL | 10 PASS, 2 FAIL (same fixtures) |
| C - Distributed Winding | 4 PASS, 1 UNSUPPORTED | 4 PASS, 1 UNSUPPORTED |
| D - BLDC | 3 PASS; 42/42 gates | 3 PASS; 42/42 gates |

Across passing A/B/C fixtures, the gated torque and Back-EMF differences
moved by at most 0.17 percentage points. The failing V-shape metrics moved by
at most 0.9 points: wide-angle mean torque went from 12.41% to 13.28% (still
YELLOW), and its Back-EMF peak from 25.16% to 25.78%. This is new native
evidence against retained references, not a regenerated FEMM baseline; the
command above reproduces it.

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
are identified separately from the original fresh-reference benchmark. Rerun
the suite on the commit you tag, and keep the qualification claim only if the
recorded verdicts do not regress.

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

## Release checks

Every numerical candidate lane must request `weighted_stress` and record
`solve_metadata.torque_method = weighted_stress`. Missing extractor provenance
or a fallback method fails qualification even if numerical deltas pass. The
report shows the requested and actual methods separately.

The earlier preregistered six-case comparison in
`benchmarks/m350-launch/benchmark_spec.json` was not completed; v1.1 replaces
it as the qualification record. v1.1 measured four of its six operating points
with the same geometry, current and steel against fresh FEMM references, all
PASS, on a 7.5° grid rather than the preregistered 3.75° grid. The 8p/12s
no-load and 1.5× saturation points, and the preregistered airgap, THD and
harmonic gates, were not measured. See [Numerical evidence](NUMERICAL_EVIDENCE.md#superseded-sinusoidal-rows)
for the row-by-row mapping.

The release record must distinguish earlier source benchmarks from results
collected from public commits. Source results cannot silently be relabelled
as public-candidate evidence. The automated browser rehearsal is recorded in
the local verification report.

Before tagging a release, record the interactive walkthrough on the tagged
commit. It covers startup in both orders, Standard sine and six-step runs,
phase currents and commutation sectors, phase/line Back-EMF, THD/harmonics,
field playback, saved-run comparison, project save/reopen, PDF/CSV/replay
downloads, cancellation, backend reconnection, and storage-limit recovery.
Record the exact OS, architecture, Python/Node/Rust/Gmsh versions, public
commit, commands, and accepted limitations.

## Claim boundaries

- Qualification is agreement with FEMM, a reference 2D finite-element solver,
  on the measured fixtures. It is not a hardware measurement and does not
  establish arbitrary-motor accuracy.
- v1.1 does not gate cogging torque, THD, airgap field harmonics, spatial mesh
  convergence, losses or efficiency. Fine BLDC stages refine angular sampling
  on the same spatial mesh.
- V-shape IPM contains two failures and remains experimental. The Prius
  fixture is unsupported. Failed, yellow and unsupported outcomes must remain
  visible.
- Thermal, PWM and dynamic ESC behavior, IPM BLDC, outer-rotor machines,
  installers, and broad operating-system certification are outside this
  preview.
- No engineering certification, supplier-specific loss prediction, or
  thermal/safety suitability is claimed.

See [Release notes](../RELEASE_NOTES.md), [Materials](../MATERIALS.md), and
[Getting started](GETTING_STARTED.md). Report reproducible defects through
[Support](../SUPPORT.md), and vulnerabilities through [Security](../SECURITY.md).
