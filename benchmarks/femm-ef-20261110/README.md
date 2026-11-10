# FEMM E/F batching and adapter consolidation — November 10, 2026

The complete standard FEMM collection and independent comparison finished in
**3 h 16 min 14 s**, meeting the 3–4 hour target without changing meshes or angle
grids. All **1,502 model hashes, solution hashes and physical point payloads**
match the retained references. All **26 assembled results** match, apart from
the explicitly retained execution-provenance differences.

| Measurement | Result |
|---|---:|
| Collection, including preflight, solves, checkpoint verification and assembly | 3 h 15 min 36 s |
| Final comparison tail after collection | 38.43 s |
| Phase E fields | 350: 12 cases plus 2 mesh controls, 25 positions each |
| Phase F fields | 1,152: 10 cases plus 2 mesh controls, 48 loaded + 48 no-load each |
| Scheduler | 8 workers, 4 positions per batch |
| Actual FEMM `mi_analyze` calls | 1,502 |
| Field batches / owned FEMM sessions | 386 / 638 |
| Worker failures or retries | 0 |
| Lowest sampled available host RAM | 41.8 GiB |
| Exact model / answer / physical payload matches | 1,502 / 1,502 / 1,502 |
| Assembled waveform / summary / self-check differences | 0 / 26 |

This is a Windows development-host measurement. The three additional E
refinement diagnostics are outside the timed standard selection. Position
runtime sums represent worker time and cannot be substituted for wall time.

## Recorded Magneto2D comparisons

The faster FEMM execution reproduces the original reference data, so it preserves
the existing native comparison results. The native E and F fields were collected
separately at their recorded commits; these are not a newly measured combined
native E/F runtime benchmark.

| Phase | Existing native outcome | Largest differences versus FEMM |
|---|---|---|
| E, cogging | 9 PASS; 3 REFERENCE_REVIEW_REQUIRED | Among passing cases: 5.88% peak-to-peak, 6.04% first harmonic |
| F, outrunners | 10 PASS; 60/60 gates PASS | Loaded mean torque 0.8624%; EMF fundamental 0.3121%; EMF peak 0.3588% |

F uses Magneto2D 0.5.0 at `82fb31f08621aa25893cfcd5f64814be686ac6a5`;
the ten native cases completed in approximately 9 min 51 s on November 9.
The E comparison retains its November 3 source pin and original gates. Near-zero
no-load F mean torque is judged with its absolute floor, not a relative percentage.

The three unchanged E reference-review cases are:

| Case | Failed FEMM self-checks | Native peak-to-peak / fundamental differences |
|---|---|---:|
| 8p24s distributed | periodicity, zero mean | 9.61% / 9.22% |
| 8p48s distributed | zero mean | 8.13% / 6.46% |
| 12p36s distributed | periodicity, zero mean | 9.94% / 8.25% |

Those flags are neither waived nor changed to PASS. The inherited LRK review
findings also remain. These results do not promote a reference bundle or release
qualification.

The follow-up [three-fixture investigation](cogging-investigation.md) rechecks
the normal/refined FEMM evidence and native mesh-convergence study. It identifies
mesh sensitivity while preserving the original baseline and failed checks.

## Consolidated source validation

The full timed collection used the original batched external wrappers. The
subsequent move into [`tools/femm_reference`](../../tools/femm_reference/README.md)
has a separate execution identity. All **26 preparation records** match exactly,
and a fresh **19-position pilot** matches all model hashes, answer hashes and
physical payloads, including hub, split winding and mesh-control cases.
The adapter and position-runner tests passed **15/15** before rebasing.

The new entry point requires only this checkout, the optional Python dependencies,
and a separately installed, matching FEMM 4.2 COM server:

```powershell
python -m tools.femm_reference --out-dir output/femm-ef --workers 8 --batch-size 4
```

## Data and provenance

- [Timing and data summary](timing-and-data-summary.json): measured wall time,
  field counts, case statistics, source evidence hashes and unchanged failures.
- [FEMM results](femm-results.json): all 26 assembled summaries, waveforms,
  physical metadata and self-checks.
- [Field hashes](field-hashes.json): all 1,502 model, answer, physical-payload and
  immutable receipt hashes. Only runtime and owned-process metadata are excluded
  from the physical-payload hash.
- [Assembly comparison](assembly-comparison.json): per-case exact comparison and
  explicit provenance metadata differences.
- [Consolidation validation](consolidation-validation.json): 26 prepared-data
  hashes and the 19 fresh field comparisons.
- [Recorded native comparison](native-comparison.json): per-case E/F values,
  gates, waveform diagnostics and original report hashes.

The original models, solution files, receipts and full evidence seals remain on
the measurement host. This compact Git record includes their hashes and derived
data; it does not include the raw multi-gigabyte FEMM artifacts or executable files.
