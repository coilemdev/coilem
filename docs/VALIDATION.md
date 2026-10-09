# Developer-preview validation

The proposed release is coilEM 0.2.0 with Magneto2D 0.3.2. This repository is
an experimental source preview with numerical qualification still pending.
Passing CI does not establish numerical accuracy or authorize a release.

See [Numerical evidence](NUMERICAL_EVIDENCE.md) for measured comparisons and
[Local verification](VERIFICATION.md) for the build, browser and audit record.
These records keep their tested runtime identities and remaining gates explicit.

## Candidate identity

`snapshot-manifest.json` records the source commit and SHA-256 of every exported
file. The public repository has its own commit history; private source history
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
its Python executable. The suite starts its own loopback servers on ports
54173 and 58000 and writes disposable results below `frontend/test-results`.
The automated rehearsal covers part of the walkthrough below; it does not
replace numerical reference comparisons or manual recovery checks.

`verify_snapshot.py --publication` is a content check. It verifies the manifest
and the publication rules encoded in the tool; it does not inspect Git history,
enable private vulnerability reporting, perform numerical qualification, or
grant release signoff. Those checks require separate evidence.

## Numerical and interactive release checks

The intended qualification path is the included 8-pole/12-slot inner-rotor
SPM example, M350-50A steel, native Gmsh meshing, Standard quality, and local
Magneto2D. Both sinusoidal and ideal wye-connected 120-degree six-step
excitation must be exercised from the pinned candidate.

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

- Earlier three-fixture SPM BLDC source comparisons provide supporting
  development evidence; they do not establish arbitrary-motor accuracy or
  replace qualification of the exported candidate.
- Historical IPM and distributed-winding reference regressions are outside
  the verified SPM preview claim. Failed or yellow reference metrics must
  remain visible in any published evidence.
- Thermal, PWM and dynamic ESC behavior, IPM BLDC qualification, installers,
  and broad operating-system certification are outside this preview.
- No engineering certification, supplier-specific loss prediction, or
  thermal/safety suitability is claimed.

See [Release notes](../RELEASE_NOTES.md), [Materials](../MATERIALS.md), and
[Getting started](GETTING_STARTED.md). Report reproducible defects through
[Support](../SUPPORT.md), and vulnerabilities through [Security](../SECURITY.md).
