# Large-model throughput and core affinity (#112)

Large models contend more than the eight small A/B/D cases in the
[matched scaling comparison](scaling.md). A preliminary full eight-worker
trial was intentionally interrupted after 629.26s, before any whole case
completed, when a large distributed-model analysis took about 80s versus
about 18s in the archived serial log. Its partial artifacts were retained;
the coordinator joined its owned workers and no FEMM processes remained.

A separate probe then solved independent copies of one retained 129,548-triangle
input. This measures solver throughput, not a complete registered case/suite.
Every probe produced exactly the same nodes, triangles and nodal potentials.

| Workers | Affinity | Probe wall time, s | Solves/s |
| ---: | --- | ---: | ---: |
| 1 | Unbound | 22.191 | 0.04506 |
| 2 | Unbound | 28.055 | 0.07129 |
| 4 | Unbound | 56.743 | 0.07049 |
| 8 | Unbound | 87.733 | 0.09119 |
| 1 | Distinct physical cores | 24.203 | 0.04132 |
| 2 | Distinct physical cores | 27.446 | 0.07287 |
| 4 | Distinct physical cores | 42.963 | 0.09310 |
| 8 | Distinct physical cores | 72.189 | 0.11082 |

Binding eight workers to distinct physical cores reduced this probe wall time by
**17.72%** and improved throughput by
**1.215x**. Eight was the highest-throughput
setting tested. The serial pinned sample was slower than unbound, so this
result supports the measured parallel configuration rather than universal pinning.

The pinned four-worker probe also lowers individual solve latency. The selected
full-suite policy therefore uses [explicit worker costs](worker-costs.json):
the four models above 100,000 archived mesh elements cost two units, other
models cost one, and a budget of eight permits up to four largest jobs or
eight smaller jobs. This is a candidate mixed-workload policy; a completed
full-suite comparison against unbudgeted eight workers is not available.
A second partial trial was stopped to finish the affinity matrix; neither
interrupted trial counts as a full benchmark result.

The private bridge reads [Windows core topology](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getlogicalprocessorinformation),
leases one logical CPU from each physical core using per-run kernel mutexes,
and applies affinity to each verified FEMM Job Object and its children.
Two overlapping real FEMM probes verified distinct leases, masks and cleanup.

The subsequent [full 29-case run](full-suite.md) completed in **1h52m02s** using
this configuration, with exact physical outputs and audits. It retains the
original grids, physics, tolerances and loaded/no-load sequence. These tuning
measurements have one observation per setting and do not represent an idle-host
repeat study.

[Raw timing summaries and integrity hashes](large-model-summary.json)

The later [mixed retained-model contention controls](contention.md) compare the
existing cost-two policy against cost three (two large plus two small jobs).
Two runs per policy show 25.69% lower large-model analysis latency but 18.13%
longer workload wall time with cost three. Keep the existing policy; these
retained inputs do not establish a new full-case or full-suite runtime.
