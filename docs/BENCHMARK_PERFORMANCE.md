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

## Analyze saved measurements

```powershell
python -m tools.analyze_benchmark_runtime `
  --run C:\bench\original-run --out-dir C:\bench\runtime-analysis
```

The command reads either a native `run_manifest.json` with per-job results or
an external run's `measurements/<case-id>/measurement.json` files. It writes
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

Start with representative cases using repeated `--case <id>` arguments, then
compare serial, 2, 4 and 8 workers on the same machine. `--workers` defaults to
1 and accepts 1..16. `--timings` changes launch order only; manifest order stays
registered. Keep each case's internal pools capped and record resource use.
The default per-job timeout is four hours; change it with `--timeout-s`.

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
blocks duplicate execution. Each restarted incomplete job uses a new attempt
directory; partial files are retained. Failed or corrupt completed evidence is
retained and requires inspection and a new output directory.

The coordinator alone updates the run manifest. On failure or interruption it
stops its remaining owned worker trees, retains completed jobs and records the
interrupted state. Producer-owned out-of-tree solver servers must have the
lifecycle described above. The locks and identity checks remain active in serial
mode as well.

This command collects measurements and execution profiles. It does not assemble
or approve a frozen reference bundle, evaluate parity gates, change qualification
or publish results. Compare serial and parallel physical arrays, summaries,
grids and gate values before adopting a parallel configuration. Keep historical
bundles and their scientific-review limitations unchanged.
