# Making E/F part of the ongoing benchmark

There is no architectural barrier. The collection and grading harnesses already
support E and F. Reference collection now takes 3 h 16 min 14 s on the measured
Windows host, with the original meshes and angle grids. That removes the
collection-time problem; it does not by itself complete scientific review or
current-candidate platform qualification.

## Evidence and remaining work

| Area | Evidence available | Work before full-suite qualification |
| --- | --- | --- |
| E: nine original cases | Retained native comparisons pass the original gates; fresh FEMM replay reproduces the reference data exactly | Register their reviewed references and collect complete Windows/macOS native runs at the same candidate |
| E: three distributed cases | Refined FEMM records are reviewed and registered in protocol 1.7.1; matched Windows/macOS very-fine qualification passes all 36 gates at candidate `3ae3458` | Include this explicit mesh cohort in the full E selection; the original biased references and normal-mesh outcomes remain preserved |
| F: ten requests | Retained Windows native collection passes 10/10 cases and 60/60 gates in about 9 min 51 s | Complete the scoped reference review, accounting for inherited LRK low-torque/mesh-orientation findings and the existing hub recipe; register the bundle and collect both platforms at the freeze candidate |
| Routine benchmark | Default CLI selection and release qualification currently cover A-D | Add E/F suite orchestration, candidate/platform records, release CI and reports with explicit mesh-specific coverage |
| Application qualification | Current product qualification does not use the new E/F cohort records | Connect accepted records to the qualification policy for the covered combinations, retaining unsupported combinations as experimental |

The three-case registration is documented in
[the refined cohort](../cogging-refined-v1/README.md). It preserves the original
case floors, 25-position grids, materials, Newton solver and corner refinement;
the registered native density is `very_fine`. A pass for that cohort does not
establish a pass for the original normal-mesh requests.

## Ongoing execution

Freeze and review FEMM references once per reference recipe. Candidate benchmark
runs should read those immutable records and collect Magneto2D fields. Recollect
FEMM when a reference recipe or covered physical contract changes, or for a
deliberate reference audit; do not repeat the entire FEMM collection on every
candidate merely to compare unchanged inputs.

Keep a fast numerical smoke selection for pull requests and the complete E/F
selection for release candidates or a scheduled benchmark. Each complete run
must use the same candidate and reviewed bundle hashes on Windows and macOS,
with the registered mesh settings, full grids and existing numerical gates.
The published timing must distinguish reference collection from native candidate
execution. Preserve failed checks and raw source identities when registering a
new mesh cohort.

This is the remaining integration plan, not a claim that all of E/F is currently
qualified. The measured native F timing comes from its recorded November 9
candidate; a new full E/F timing requires matching current-candidate runs.
