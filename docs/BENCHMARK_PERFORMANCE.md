# Benchmark execution performance (#112)

The ordinary `python -m tools.run_benchmarks --phases A B C D` command collects
native results against saved reference data. Fresh reference generation is a
separate, operator-maintained workflow. Measure those costs separately.

The historical Windows v3 reference run contains 29 successful measurements:
32,907.46 seconds of summed case runtime and 32,928.43 seconds of registered
wall time. The published native collection took 2,737.39 seconds of wall time.
These observations identify a useful starting point; they do not reproduce
every reported 13-hour cycle or establish a controlled speedup.

The [initial two-case pilot](../benchmarks/performance-112/README.md) measured
13m35s serially versus 8m22s concurrently, with exact physical-payload equality.
Its limits and separate retained-field profiling are recorded with the result.
The [follow-up](../benchmarks/performance-112/scaling.md) measures the same eight
cases in 12m21s at four workers and 7m12s at eight, with exact physical equality.
It also validates field-output and Windows readiness optimizations separately.
The [large-model probes](../benchmarks/performance-112/large-model.md) show
stronger contention on larger inputs and motivate the measured-host affinity
and worker-cost configuration. The [completed full-suite run](../benchmarks/performance-112/full-suite.md)
collected all 29 cases in **1h52m02s**, versus the archived same-host serial span
of **9h08m46s** (**79.58% less time**). All physical outputs and audits match
exactly. This is one development-host observation, with the combined execution
optimizations and a frozen physical source. FEMM analysis remains 87.2% of summed
case time; native collection and report rendering are separate stages.

The [fresh full-suite repeat](../benchmarks/performance-112/repeat-20261016.md)
completed the same 29 cases in **1h50m54s**, 68.06 seconds (1.01%) less than the
prior run. All physical payloads and extraction audits remain exact; recorded
worker budgets, core leases and bundle-compatibility checks pass. Keep reference
bundle v3 and validation protocol 1.3.0 for these unchanged physical results.

The [matched native comparison](../benchmarks/performance-112/native-20261016/README.md)
completed all 35 supported native jobs against that fresh FEMM bundle in
**43m40s**, versus 45m37s in the saved Windows v3 report. All physical summaries,
waveforms and evaluation numbers match exactly; the existing 28 PASS, 1 YELLOW
and planned unsupported Prius outcomes remain. Both current collection stages
sum to **2h34m34s**, excluding the gap between starting them.

The [repeated FEMM 4.2 contention controls](../benchmarks/performance-112/contention.md)
compare the four largest retained models plus eight small jobs under large-worker
cost two versus three, using existing/candidate/candidate/existing run order.
Cost three permits two large plus two small jobs: individual large-model
analyses become 25.69% faster, but total retained-workload time increases 18.13%.
All 176 recomputed solutions match the saved meshes and nodal potentials
exactly. Keep the existing cost-two guidance; this short throughput experiment
does not supply a new registered case or whole-suite runtime.

The [FEMM 5 pilot](../benchmarks/performance-112/femm5-pilot.md) evaluates the
06Oct2026 headless/TCP build alongside the existing 4.2 installation. Its fresh
matched Phase A case takes 63.87s versus 303.64s with the optimized 4.2 producer.
Four complete representative A/B/C/D cases retain the saved native gate statuses,
but meshes and physical results differ, including a 3.99% Phase C mean-torque
change. FEMM 5 remains a separate candidate requiring mesh-convergence review;
this subset does not establish a new full-suite runtime or replace frozen data.

The [mesh-refinement checks](../benchmarks/performance-112/femm5-mesh-convergence.md)
reduce the Phase C mean-torque difference to 1.87% at fine and 0.42% at very_fine,
with measured case times of 6m08s and 14m32s. The study also tests IPM peak flux
and pairs retained refined inputs with both solver versions. All mesh policies,
non-target metric changes and timing limits remain visible; this is candidate
evidence without a frozen-reference or numerical-gate rule change. The finest
IPM level worsens local peak-B agreement and crosses the saved native BEMF peak
gate; its FAIL verdict remains visible. Fine better preserves agreement with
the archived IPM reference at lower cost; the finer IPM field samples agree
better with equivalently refined 4.2, so archived agreement is not an accuracy
oracle. Phase C also retains a pointwise torque gap against refined 4.2.

## Analyze saved measurements

```powershell
python -m tools.analyze_benchmark_runtime `
  --run C:\bench\original-run --out-dir C:\bench\runtime-analysis
```

The command reads native or external-runner `run_manifest.json` files with
their registered per-job results, or the historical external layout's
`measurements/<case-id>/measurement.json` files. It writes
JSON and Markdown in a new analysis location, without running a solver or
editing the measured run. Select a historical suite with `--suite` if needed.

The report separates registered wall time, the span of successful measurements,
summed successful-job runtime, errors and unsupported jobs. It also simulates
1/2/4/8-worker schedules from recorded durations, including longest-first order.
Those simulations add no contention or coordinator overhead to the recorded job
durations and are explicitly estimates.
They are useful for choosing experiments, not for claiming a measured speedup.

## Run an external reference producer in independent case processes

```powershell
python -m tools.run_reference_benchmark `
  --producer C:\reference-tools\producer.py `
  --out-dir C:\bench\reference-p2 --workers 2 `
  --timings C:\bench\runtime-analysis\runtime-analysis.json
```

Use the Python environment required by the external producer. The public
repository supplies the scheduler; it supplies no reference-solver adapter,
installation discovery or reference-solver dependencies. The native benchmark
command and application solve path are unchanged.

The installed native harness lives in `backend.benchmark_suite`. External
reference scheduling stays in `tools.benchmark_suite` with standard-library
file and process primitives, so it leaves a producer's own `backend` namespace
available. The documented reference command and payload-reuse import stay the
same after the installed-harness migration.

The external Python module has three functions:

```python
def identity():
    # Return JSON-compatible provenance for every physical source, input,
    # normalizer, solver executable, material and required dependency.
    return audited_producer_identity()

def cases():
    # In registered order; phase labels are recorded in the run manifest.
    return {"registered_case_a": "A", "registered_case_d": "D"}

def measure(case_id, work_directory):
    # Preserve the registered physical request and within-case solve sequence.
    # Use only work_directory for mutable models, answers, temporary files and caches.
    # Close every owned solver session, including on failure.
    return {"status": "COMPLETE", "result": measured_result}
```

`identity()` must be side-effect free and cover the complete producer contract.
The scheduler additionally hashes the bridge module, its own execution sources
and the Python executable. It checks identities before each launch and after
each successful measurement, and stores both worker identities and request/result
hashes. The producer remains responsible for matching its registered geometry,
materials, grids, extraction methods and numerical gates.

Start with representative cases using repeated `--case <id>` arguments, then
compare serial, 2, 4 and 8 workers on the same machine. `--workers` defaults to
1 and accepts 1..16. `--timings` orders jobs longest first; manifest order stays
registered. Keep each case's internal pools capped and record resource use.
The default per-job timeout is four hours; change it with `--timeout-s`.

### Limit resource cost as well as process count

Large models can contend more than the small cases used to test startup and
isolation. Measure throughput on representative sizes before choosing a limit.
For mixed workloads, `--worker-budget <positive-integer>` explicitly enables
optional `worker_cost` values in the timing JSON:

```json
{"jobs": [
  {"case_id": "large_case", "runtime_s": 1200, "worker_cost": 2},
  {"case_id": "small_case", "runtime_s": 300, "worker_cost": 1}
]}
```

At `--workers 8 --worker-budget 8`, at most four jobs with cost two can run,
while jobs with cost one can occupy eight slots. Costs are operator-defined scheduling units;
choose them from measured contention or resource use. Missing costs are one;
each selected cost must be a positive integer within the budget. The sum of
active costs and the process-count limit are both enforced.

Repeated timing rows for a case are combined by summing their durations and
taking the maximum worker cost, so native runs with multiple stages can guide
case scheduling. Durations must be finite and non-negative; timing validation
finishes before the output directory is initialized.

A smaller job can start while an earlier large job waits for capacity. Each session records its
costs, budget, planned order and actual launch order. Without `--worker-budget`,
cost hints are ignored and ordinary worker-count scheduling is retained.

The timing analyzer's unconstrained scheduling estimates do not model these
optional budgets. Use actual run sessions to assess a budgeted configuration.

With the compatible pinned producer, reproduce the measured scheduler policy:

```powershell
python -m tools.run_reference_benchmark `
  --producer C:\reference-tools\producer.py `
  --out-dir C:\bench\reference-fast --workers 8 --worker-budget 8 `
  --timings benchmarks\performance-112\worker-costs.json
```

That cost file describes the frozen v3 cases on the measured host. New geometry,
windings or source pins require their own compatible references and scheduling
measurements. Readiness, metrics mode and core affinity belong to the external
producer; the generic launcher does not enable them by itself.

### Optional reuse inside an external producer

`tools.benchmark_suite.payload_reuse.reuse_full_payload(builder, raw_fields=...)`
can avoid building the same position's field payload twice. It computes the
full payload once and projects the compact payload by dropping the specified
raw fields. Enable it only after checking that both outputs exactly match the
original builder. Include the helper source hash in the producer identity.
The original builder must accept `include_raw_mesh`; inputs, options and nested
output values must remain immutable between paired calls. Create a separate
wrapper per serial case. It retains only the latest position and exposes
`counts` for proving that reuse occurred.

Field processing also supplies physical summaries such as steel RMS. A producer
that omits display work must retain the underlying numeric fields and verify
all summaries, waveforms and extraction audits. Record omitted visualization
artifacts explicitly in its identity and evidence. The public scheduler does
not enable either optimization automatically.

### Solver ownership is part of the external producer contract

Independent Python processes alone do not prove solver isolation. The Windows
FEMM bridge must create distinct ActiveX instances (for example with
`DispatchEx`), verify their distinct process IDs, and own their model/temp/cache
paths. Its lifecycle must close those instances if the worker is terminated.
For the local #112 bridge, a Windows kill-on-close Job Object owns each verified
FEMM process and its children. The public scheduler never terminates a process
by executable name.

Retain each case's original serial angle and loaded/no-load ordering initially.
The legacy adapter documents a back-EMF difference when its separate angle
parallelism changes no-load session history. That method needs its own
validation before use for reference generation.

## Resume, interruption and evidence

Repeat the command with `--resume`. Selected cases, runtime, producer and source
identities must match. Worker count and scheduling order can change between
sessions and are recorded separately. Completed, hash-verified jobs are reused.
Workers hold per-job kernel locks, so a worker that outlives its controller
blocks duplicate execution. A worker also enforces its recorded launch deadline
if the controller exits. Each restarted incomplete job uses a new attempt
directory; partial files are retained. Missing or corrupt hash-recorded results
are refused before any new solve; restore that evidence or use a new directory.

The coordinator alone updates the run manifest. An individual failed or timed-out
case leaves other jobs running; the run finishes `COMPLETE_WITH_ERRORS` and exits
non-zero. Use `--resume --retry-failed` after resolving a transient failure to
retry only failed cases, with the same registered producer/source identities.
Every earlier result keeps its original path and hash in `attempt_history`;
retries use `jobs/<case-id>/result-<attempt-id>.json`. Read result paths from the
manifest. Successful cases are reused without rewriting their measured bytes.

On controller interruption, owned workers are stopped, any already-completed
results are verified and retained, and unfinished jobs remain resumable.
Producer-owned out-of-tree solver servers must have the lifecycle described
above. The locks and identity checks remain active in serial mode as well.

This command collects measurements and execution profiles. It does not assemble
or approve a frozen reference bundle, evaluate parity gates, change qualification
or publish results. Compare serial and parallel physical arrays, summaries,
grids and gate values before adopting a parallel configuration. Keep historical
bundles and their scientific-review limitations unchanged.
