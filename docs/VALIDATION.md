# Developer-preview validation

The source candidate is coilEM 0.4.0 with Magneto2D 0.3.3. The
[Windows requalification report](../benchmarks/windows-prius-requal-20261018/README.md)
at `5b6cb61` supplies development qualification for the current winding model;
see [Qualification status](#qualification-status). The
[v0.4.0 evidence report](../benchmarks/v0.4.0/README.md) retains the complete
Windows/FEMM and Pyleecan collections, their measured commits and limitations.
Final-candidate benchmarks and installed-wheel acceptance remain open in the
[release plan](RELEASE_0_4_0.md).

0.5.0 is in development. It adds performance outputs, each labelled
experimental until a reference gate passes; see
[0.5.0 performance outputs](#050-performance-outputs) for their claim
boundaries and the [0.5.0 release notes](RELEASE_0_5_0.md) for what changes.
The 0.5.0 freeze reruns A/B/C/D on macOS and Windows against protocol 1.6.0.
**TODO(freeze):** update this paragraph and the one above with the 0.5.0
record.

Historical reports v1.1 and v1.7/v1.8 measure the 0.3.x winding model and keep
their original identities. They do not measure the changed 0.4.0 application.
The macOS record predates the current physics sources and is NOT_COMPARABLE;
new macOS numerical parity needs a fresh full run. Linux and Python 3.15 full
numerical parity have not been measured. Passing hosted CI or wheel acceptance
does not establish that parity or hardware accuracy.

See [Numerical evidence](NUMERICAL_EVIDENCE.md) for measured comparisons and
[Local verification](VERIFICATION.md) for the build, browser and audit record.
These records keep their tested runtime identities explicit.

The [benchmark index](../benchmarks/README.md) identifies the latest full run,
the current selection and archived evidence. The [IPM diagnosis](IPM_BENCHMARK_DIAGNOSIS.md) explains
the fixture replacement and the solver/convergence work that remains open.

## coilEM 0.3.0 on macOS and Windows

Reports [v1.7](../benchmarks/macos-rc-20261013-1fac3a1/README.md) (macOS, Apple M4) and [v1.8](../benchmarks/windows-rc-20261013-1fac3a1/README.md)
(Windows, Ryzen 7 7700) measure the released commit
`1fac3a17fca7501d054a12b64b4a0472916ade98` (coilEM 0.3.0, Magneto2D 0.3.3) with
harness 1.2.1 and protocol 1.1.0, from the same source hash. On both platforms
all 35 supported native jobs completed, and the registered gates record 29 PASS,
the planned unsupported Prius case and 42/42 BLDC gates PASS.

Each report matches its platform's run of the earlier release candidate
`04f87a5` exactly, in every numerical value: v1.7 matches v1.5 on macOS, and v1.8
matches v1.6 on Windows. The changes since then, the 0.3 QA fixes, touch no
benchmark input or numerical path. Across the two platforms all 30 verdicts and
every gate status agree. Values differ only because Gmsh builds slightly
different meshes on each platform; candidate mean torque differs by at most
0.23% (V-shape deep apex), far inside every gate. The v1.8 run was resumed after
a host reboot, which leaves its results unchanged but makes its wall-clock time
an observation only. The generated PDFs and comparisons are committed with the
reports.

### Earlier release candidate `04f87a5`

[Report v1.5](../benchmarks/macos-rc-20261013-04f87a5/README.md) measured the earlier release
candidate `04f87a5013415997cdef96a9bfa35125ce625bc5` on macOS: all 35 supported
native jobs completed in 56.5 minutes, with 29 PASS, the same planned
unsupported Prius case and 42/42 BLDC gates PASS. A cross-platform comparison
with v1.4 is committed with the report.

All 30 verdicts and every gate status match v1.4. The values are not
bit-identical, because v1.4 ran on Windows: Gmsh builds slightly different
meshes on each platform, so element counts differ by a few to a few tens of
elements and candidate mean torque moves by at most 0.23% (V-shape deep apex),
far inside every gate. Since `02fa24b` the candidate changes no solver input or
numerical path. This record preserves the existing fixture metrics and does not
broaden the developer-preview qualification policy.

## Full Windows rerun with process-pool improvements

[Report v1.4](../benchmarks/windows-process-pools-20261012-02fa24b/README.md)
measures clean candidate `02fa24b7e9f00643d3d5931f55e79de0b623a9ec`, including
the performance changes in PRs #32, #33, #34 and #36 and the Windows process
pools in PR #37. All 35 supported native jobs completed in 44.66 minutes;
the registered gates record 29 PASS, the same planned unsupported Prius case
and 42/42 BLDC gates PASS. The generated PDF and full numerical comparison are
committed with the report.

All 30 verdicts and all reference gate values match v1.3. Registered inputs,
resolved configurations, mesh element counts and angle grids match; every
native torque, Back-EMF and phase-current waveform is exactly equal. Physical
summary values also match exactly except teeth/yoke steel RMS floating-point
accumulation differences below 6e-14 T. Before/after worker identities,
registered request/result hashes and frozen reference gates were verified.

The measured application and native solver remain coilEM 0.2.0 and Magneto2D
0.3.2; the report records the exact commit, source and binary hashes. The CLI
includes field-frame extraction and result construction but does not invoke
public HTTP playback packaging or durable UI run saving. The older run had
concurrent workloads, so the elapsed-time ratio is an observation across all
intervening changes, rather than a controlled process-pool-only A/B test. This
record preserves the existing fixture metrics and does not broaden the
developer-preview qualification policy.

## Full Windows rerun before later performance changes

[Report v1.3](../benchmarks/main-20261012-0b463b3-rerun/README.md) measures the
complete selected protocol 1.1.0 matrix at clean candidate
`0b463b31fc3479360ffaa3668731e3792c034639`: A - SPM 10 PASS, B - IPM 12 PASS,
C - Distributed Winding 4 PASS / one planned unsupported Prius fixture,
D - BLDC 3 PASS / 42 gates. All native field jobs are new; comparisons read the
frozen, data-only FEMM bundle. FEMM and its adapter were not installed or run.

This candidate predates performance PRs #32, #33 and #34, and the later main
responsiveness changes in PRs #29, #30 and #31. The report provides a recorded
numerical baseline for comparing later candidates without claiming those later
changes were measured. Its elapsed timings include concurrent workloads and
result generation, and do not benchmark browser responsiveness. A controlled
speed comparison requires comparable load and settings.

Inputs, reference arrays, material contracts, angle grids and gates are unchanged
from v1.2. The original failed low-output geometries and the scoped preview
qualification table below remain visible; this rerun does not broaden that policy.

## Next-release benchmark selection

[Baseline report v1.2](../benchmarks/release-baseline-20261011-v1.2/benchmark_report.md)
is the updated benchmark selection for the next release: A - SPM 10 PASS,
B - IPM 12 PASS, C - Distributed Winding 4 PASS / one planned coverage item (not yet supported), and
D - BLDC 3 PASS / 42 gates. Protocol 1.1.0 replaces the two low-output Phase B
cases with higher-output designs; all other inputs, saved references and gates
are unchanged. Deep apex uses 12 mm magnet legs, wide angle 10 mm. Their
fresh native/FEMM means exceed 0.5 N m and their torque/Back-EMF gates PASS.

The baseline compiles retained macOS measurements at `45e0a5c` and the new
two-case qualification at `af56962`, identifying each row's candidate and source.
It is not a complete run of a single next-release commit. The original failures
and preview qualification record below remain archived. New geometry passing
does not establish a solver fix or broaden the previous qualification claim.
V1.3 now records that full selected matrix at `0b463b3`; subsequent release
candidates still require their own run before updating a qualification claim. V1.7 (macOS)
and v1.8 (Windows) are those runs for coilEM 0.3.0 at `1fac3a1`.

Harness 1.3.0 runs [protocol 1.1.0](../benchmarks/abcd-v1.1/README.md) without FEMM
on macOS, Windows and Linux:

```sh
python -m tools.run_benchmarks --phases A B C D --out-dir ../benchmark-output/my-run --pdf
```

Harness 1.5.1 also runs from an installed coilEM, with no checkout: `coilem
benchmark` solves the current suite, grades it against the frozen FEMM v3
reference, and matches it against the [published record](../benchmarks/records/README.md)
for the platform (see [Run the benchmark yourself](#run-the-benchmark-yourself)).

Historical protocol 1.0.0 remains selectable with `--suite` and its matching
`--reference-bundle`. Changed physical inputs require new matched references;
changing only the candidate solver can reuse compatible frozen data.

### Pyleecan Prius software reference (#126)

The [versioned Prius report](benchmarks/pyleecan-prius-v1/README.md) documents the
exact pinned Pyleecan model in the normal Design/Solve workspace. Its tutorial
BEMF and loaded-torque cases retain separate temperature/speed conditions and
stable case IDs. It preserves the complete thirteen-angle upstream comparison,
including discrepancies, independently checked explicit winding extraction,
and mesh/angular controls. Software reproduction does not establish identity
with the original Yang paper or measured ORNL hardware. The legacy registered
ORNL A/B/C/D row below is unchanged and remains unsupported.

### ORNL Prius coverage deferred to v0.5.0

The planned item is ORNL Prius 2004: its HoleM50 rotor geometry is outside the
public flat-buried/V-shape IPM policy. Geometry helpers exist, but native
meshing/field solves and matched FEMM qualification are needed before enabling
public support. Numerical status remains UNSUPPORTED; no comparison was
performed. Hardware correlation #69/#82 is assigned to v0.5.0 and does not
block the 0.4.0 software-model release.

### Existing Honda Accord hardware comparison

The [real-winding comparison](hardware-validation/honda-accord-2005/real-winding-comparison/README.md)
retains its own pins: `738d951` for no-load/zero-position scans and `50fe405`
for 198 locked-rotor solves. It uses the blind N35 assumption and simplified
single-bar rotor; nothing was fitted and there is no hardware pass/fail.
Mean back-EMF error across 18 speeds is +0.6% (−2.6% to +5.4%); mean peak-torque
error across nine currents is −3.6% (−8.3% to +1.8%). Rotor approximation,
unknown magnet grade, assumed steel and angular/cogging sampling remain limits.
A fitted variant was planned but is not claimed as a completed measurement.
These historical data do not extend A/B/C/D qualification or substitute for a
final-candidate run.

## Run the benchmark yourself

An installed coilEM carries the A/B/C/D suite, its frozen FEMM v3 reference
and the [published records](../benchmarks/records/README.md), so anyone can
check their own installation:

```sh
coilem benchmark --quick    # one case per phase, about 5 minutes
coilem benchmark            # all 30 cases, about 50 minutes
coilem benchmark --list     # the cases and the record's times
```

`--phase B` runs one phase (repeatable), and `--out` names the output folder.
The command solves each case with the installed Magneto2D and grades it
against the frozen reference with the gates above. It then matches the outcome
against the record for the platform. A match needs the same verdicts and gate
statuses, and mean torque, back-EMF fundamental and back-EMF peak within
0.5%, 0.05% and 1.5% of the record. Those tolerances come from the measured
difference between macOS and Windows. The physics sources are checked by hash
first, so a release with unchanged physics is matched against a record
measured at an earlier commit.

Each case's solver files are deleted when it finishes. The run stops before a
case if the output drive has less than 3 GB free; `--resume --out <folder>`
continues it. The output folder holds the full report under `report/` and a
shareable Markdown and JSON report under `share/`. The shareable report names
no local paths and passes the publication path check.

## Qualification status

The maintainers accept the [Windows requalification report](../benchmarks/windows-prius-requal-20261018/README.md)
as the numerical qualification record for the application on `main`. It
measured commit `5b6cb61` on Windows with the Precise mesh default against the matched
[FEMM v3 references](../benchmarks/reference-baselines/ipm-high-output-v3/manifest.json),
so it covers the 0.4.0 winding model: full slot-side turns in flux linkage
(#80), tooth coils for fractional-slot concentrated windings, the current angle
measured from phase A's own axis and conformal two-layer slots (#91, #85).
Earlier reports measured the previous winding model, so their PASS results no
longer qualify these combinations; report v1.1 remains the record for coilEM
0.3.x. A combination is qualified when every registered fixture for it passes
its FEMM parity gates in the report. Failed, YELLOW and unsupported outcomes
remain visible and are not waived by the aggregate pass count.

The new run measured protocol 1.3.0 directly, including the six-step checks of
commanded currents against phase A's winding axis. Every verdict, gate and
recorded numerical value equals the [October 15 Windows v3 comparison](../benchmarks/windows-v3-20261015-738d951/README.md).
That historical comparison retains its post hoc evaluation and fixed-axis
protocol 1.1.0 golden-sequence FAILs for the 8-pole and 14-pole 12-slot fixtures.
The macOS record remains at `738d951`; its source guard reports NOT_COMPARABLE
until a new macOS run measures the changed mesh and reference-dispatch sources. Fast mesh remains
experimental. The FEMM v3 bundle keeps `REVIEW_REQUIRED` for limitations
outside these gates, such as steel-loss estimates, the Kt current base and
peak flux-density sampling. Release qualification remains a separate step.

| Rotor | Winding | Excitation | Fixtures | v3 outcome | Status |
| --- | --- | --- | --- | --- | --- |
| SPM | Single-layer concentrated | Sinusoidal | Phase A: ten operating points on 4-pole/12-slot and 8-pole/12-slot designs | 10 PASS | Qualified |
| SPM | Single-layer concentrated | Ideal six-step 120-degree wye (BLDC) | Phase D: 4-pole, 8-pole and 14-pole 12-slot designs | 3 PASS; 42/42 gates (protocol 1.3.0) | Qualified |
| SPM | Two-layer distributed, full pitch or 5/6 short pitch | Sinusoidal | Phase C: 8p/24s, 8p/48s, 8p/48s 5/6-chorded, 12p/36s | 4 PASS | Qualified |
| Flat-buried IPM | Single-layer concentrated | Sinusoidal | Phase B: six fixtures | 6 PASS | Qualified |
| V-shape IPM | Single-layer concentrated | Sinusoidal | Phase B: six fixtures | 5 PASS, 1 YELLOW | Experimental |
| Multi-layer IPM (Prius 2004 fixture) | - | - | Phase C | Rejected by the public policy | Unsupported |

The 4-pole/12-slot fixtures keep their winding layout; only their flux-linkage
credit changed. The 8-pole/12-slot, 12-slot/10-pole, 24-slot/16-pole and
14-pole/12-slot fixtures are now wound as tooth coils. The Phase C fixtures keep
their turn credit and use the conformal two-layer slots and phase-A current
angle. The v3 report re-measured every row on the changed code.

The application also accepts combinations that the benchmark did not measure.
They are experimental:

- SPM with distributed windings under ideal six-step excitation;
- SPM with single-layer distributed windings;
- two-layer concentrated windings (a coil on every tooth);
- any combination solved with the **Fast** mesh build, because the
  benchmark measured meshes built with Precise node placement;
- flat-buried or V-shape IPM with distributed windings; and
- Halbach, lessons and generic field mode, which are outside A/B/C/D.

Ideal six-step excitation is available for SPM only.

The application applies this table to every design. `backend/qualification.py`
classifies the topology, IPM rotor, winding type, layers and pitch, excitation
and steel, and returns the status with a one-sentence reason. Design health,
the Solve page and the Results page show it, and each saved run records it in
its provenance, PDF and CSV. A qualified combination using custom steel is
experimental, because qualification used the bundled M350-50A curve. A
Preview run notes that its coarse mesh was not part of qualification. Tests
check each reason against the v3 report's outcomes, and fail when a winding,
current-angle, geometry, mesh, material or native-solver source differs from
the one the report measured; a changed physics source needs a new report
before it can keep a qualified status.

Qualified means agreement with FEMM within the registered gates for the
measured fixtures, under these conditions: Magneto2D 0.3.3, native Gmsh meshes
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

The V-shape baseline's peak Back-EMF differs from FEMM by 14.78% (YELLOW;
PASS is within 10%, FAIL beyond 15%); its fundamental differs by 2.06% and its
mean torque by 5.85%. The other five V-shape fixtures pass, with mean-torque
differences of 2.5-5.9%, against 0.01-0.64% for flat-buried IPM. Treat V-shape
results as experimental until a solver change passes all six fixtures. Report
v1.1's original low-output deep-apex and wide-angle fixtures failed (36.02%
mean torque; 36.03% and 25.16% Back-EMF H1 and peak) and remain in its
archived record.

The 0.5.0 development run on macOS at `5b7cad8`
([report](../benchmarks/macos-native-20261022-5b7cad8/README.md)) records
29 PASS and the planned unsupported Prius. The V-shape baseline is PASS there,
but V-shape IPM stays experimental: the corrected nonlinear stopping test
(public issue 11) moved five V-shape Back-EMF fundamentals 4.7–6.6% away from
FEMM, to 8.1–8.6% against the 10% gate. That run is development evidence, not
release qualification. **TODO(freeze):** replace the table above with the
0.5.0 freeze report's outcomes on macOS and Windows.

## 0.5.0 performance outputs

0.5.0 adds loaded d/q flux linkage, a flux-linkage map, the torque–speed
envelope, an efficiency map, copper and iron loss, efficiency at the operating
point, magnet temperature derating and phase resistance
([public issue 143](https://github.com/coilemdev/coilem/issues/143)). This
section is the claim boundary for each of them: what is qualified and by which
gate, what is experimental and why, and what is not modelled.

**Every one of these outputs is experimental in the current source.** None has
a measured reference gate yet. Each one shows its status and the reason in the
UI, the run PDF and CSV, and the performance PDF and CSV. The reasons quoted
below are the strings the app prints, from `backend/models/performance.py`,
`backend/iron_loss.py`, `backend/loss_breakdown.py` and
`backend/drive_performance.py`. `frontend/src/public/outputStatus.ts` mirrors
the three in `backend/models/performance.py`, and `tests/test_output_status.py`
checks that they match.

[Protocol 1.6.0](../benchmarks/abcd-v1.6/README.md) registers the reference
gates for loaded λd/λq and magnet temperature. Their FEMM records arrive at the
0.5.0 freeze ([request](../benchmarks/abcd-v1.6/FEMM-REQUEST.md)). An output
becomes qualified only for the fixture combinations whose gates pass in the
freeze report, and only once the app's status for it changes. Passing a gate
does not qualify other topologies, currents or angles.

**TODO(freeze):** record each gate's outcome below. Change the status of any
output that passes in the code and in this section together.

| Output | Status now | Gate that could qualify it | Gate result |
| --- | --- | --- | --- |
| Loaded λd and λq | Experimental | Protocol 1.6.0 `lambda_d`, `lambda_q` and `reference_dq_torque`, 12 points on two fixtures | **TODO(freeze)** |
| Apparent Ld and Lq | Experimental | None; see below | — |
| Flux-linkage map | Experimental | None beyond the 12 d/q points | — |
| Torque–speed envelope | Experimental | None; hardware correlation planned | **TODO(freeze):** correlation done or deferred |
| Efficiency map | Experimental | None; hardware correlation planned | **TODO(freeze):** correlation done or deferred |
| Phase resistance | Experimental | Hand calculation, being registered | **TODO(freeze)** |
| Copper loss | Experimental | Follows phase resistance | **TODO(freeze)** |
| Iron loss, M350-50A and M400-50A | Experimental | None planned for 0.5.0 | — |
| Efficiency at the operating point | Experimental | None; it uses the iron loss | — |
| Magnet temperature derating | Experimental | Protocol 1.6.0 temperature cases, four cases on two fixtures | **TODO(freeze)** |

### Loaded d/q flux linkage, Ld and Lq

The loaded phase flux linkages and the applied currents are transformed with
the amplitude-invariant Park transform and averaged over the loaded positions.
The d-axis is placed from the no-load flux linkage, which also checks the
current angle independently. A run without a no-load sweep places it from the
commanded angle instead, and the record says so in `d_axis_source`. Apparent
Ld = (λd − λpm) / id and Lq = λq / iq are secant values at the solved point.

- **Qualified:** nothing yet. Protocol 1.6.0 compares λd and λq with FEMM at
  12 points: the 8p/12s concentrated SPM at 20 and 40 A peak and the FSAE flat
  IPM at 50 and 100 A peak (1× and 2× each fixture's baseline current), each at
  γ 0°, 30° and 60°.
  - `lambda_d` and `lambda_q` pass within 3% of the reference's |λdq|
    (YELLOW within 6%).
  - `reference_dq_torque` checks FEMM's own d/q torque against its solved
    torque, within 2% (YELLOW 5%).
  - The harness applies coilEM's transform to FEMM's raw waveforms, so the two
    cannot differ by convention.
  - If the gates pass, the qualified scope is λd and λq for SPM and flat-buried
    IPM with single-layer concentrated windings under sinusoidal current, up to
    2× the fixture current and from γ 0° to 60°. **TODO(freeze):** confirm.
- **Ld and Lq stay experimental even if the λd/λq gates pass.** The gate bounds
  λd and λq as a share of |λdq|. Ld depends on λd − λpm, and on an SPM Lq
  depends on a small λq, so a passing point can leave them tens of percent
  uncertain. At `spm_8p12s_concentrated__dq_I20_g30`, coilEM's λd is
  1.35 mWb below its γ 0° value and λq is 2.46 mWb, while the 3% band is
  0.52 mWb. **TODO(owner):** confirm this boundary.
- **Experimental because:** "Not yet compared with a reference solution: the
  benchmark measures torque and back EMF, so the design's qualification does
  not cover the d/q flux linkage or the inductances from it."
- **Consistency check, not a reference:** Torque–λdq agreement compares the
  solved torque with 1.5·P·(λd·iq − λq·id) from the same solve. In every loaded
  benchmark case at `5b7cad8` it reads 99.86–100.29%. It catches a bookkeeping
  error; it cannot show that both sides are right.
- **Not modelled:** incremental (differential) inductances. Only position
  averages are reported, not λd and λq at each rotor position. An open-circuit
  run has no current angle, inductance or torque check.

### Flux-linkage map

The map solves the design over a grid of current magnitude |I| and angle γ
from 0° to 90°: 5 currents × 7 angles on Preview, 7 × 10 on Standard. Each
point is an ordinary loaded solve over half an electrical cycle. Half-wave
symmetry completes the cycle for iron loss, and only the zero-current point
runs the no-load sweep. Each point stores torque, λd, λq and iron loss at the
design's rated speed.

- **Qualified:** nothing. The map's points use the same solve as the 12 gated
  d/q points, but the gate covers only those points. Map points above 2× the
  fixture current, at γ beyond 60°, or for other designs are not covered.
- **Development check, not a gate:** half-cycle points agree with full-cycle
  sweeps within 0.01% on torque and λd/λq and within 0.2% on iron loss
  (4p/12s and 8p/12s concentrated SPM).
- **Experimental because:** it carries the d/q reason above.
- **Not modelled:** values between grid points are interpolated, not solved.
  The map has one magnet temperature, and its largest current bounds every
  curve derived from it.

### Torque–speed envelope: MTPA, field weakening and MTPV

The envelope is interpolated from the map. The voltage limit uses the loaded
λd and λq with the phase resistance, against a peak phase voltage of
m · V_dc / 2, with m at most 2/√3, the linear limit of space-vector
modulation. Each sample is labelled MTPA, field weakening or MTPV. MTPV appears
only when a smaller current gives more torque than the current-limit circle.

- **Qualified:** nothing. Issue 143 plans a comparison with the ORNL Prius and
  Honda Accord torque–speed test data, as hardware correlation and not
  qualification. **TODO(freeze):** record that comparison, or say it is
  deferred.
- **Development checks, not gates:** against an analytic SPM with resistance,
  the curve is within 1% and the base speed matches the closed form. An
  analytic IPM reaches its MTPA torque within 0.5%.
- **Experimental because:** "Not yet compared with measured torque-speed data.
  Interpolated from the flux-linkage map with sinusoidal current; inverter
  drops and dead time are ignored." A current limit above the map's largest
  current is clamped to it, and the reason says so.
- **Not modelled:** inverter voltage drops, dead time, PWM current ripple and
  overmodulation. Current is sinusoidal and steady state. The continuous curve
  is the current limit the user enters, not a thermal rating.

### Efficiency map

The map uses MTPA control by default: the smallest current for each torque
within the voltage limit. Least-loss control, the current with the least
copper plus iron loss, is the option. Copper loss is at the winding
temperature. Iron loss is scaled from the map's reference speed, hysteresis
with frequency and eddy current with its square. The torque axis is
electromagnetic torque.

- **Qualified:** nothing. As for the envelope, a hardware correlation is
  planned, not a qualification. Issue 143 keeps iron loss and the efficiency
  map experimental unless a reference is recorded.
- **Experimental because:** "Not yet compared with measured efficiency data."
  The reason then names the control and how the losses were computed.
- **Not modelled:** the losses listed under
  [Not modelled in any 0.5.0 loss](#not-modelled-in-any-050-loss), at every
  point of the map.

### Phase resistance and copper loss

Phase resistance comes from the wire, the turns and the mean turn length. The
mean turn is two stack lengths plus two half-circle end turns, with IEC 60028
copper or IEC 60889 aluminium data; see
[Materials](../MATERIALS.md#winding-conductors). Copper loss is
3 · I_rms² · R at the winding temperature, split into the stack and end-turn
parts.

- **Qualified:** nothing yet. Issue 143 plans a gate against a hand
  calculation. **TODO(freeze):** name the registered gate and its outcome.
- **Development checks, not gates:**
  - The 2005 Honda Accord's published winding gives 9.80 mOhm at 21 °C,
    against 9.7 mOhm measured (+1.0%; ORNL/TM-2006/535, Table 2.3).
  - For the Pyleecan Prius, coilEM reproduces Pyleecan's own 35.95 mOhm when
    its end-turn arcs are removed.
- **Experimental because:** "Calculated from the wire, turns and mean turn
  length (half-circle end turns, IEC conductor data); not yet checked against a
  hand calculation or a measured winding." Copper loss carries the same status
  and reason.
- **Not modelled:**
  - AC copper loss: copper loss is DC I²R.
  - The winding temperature is an input, not computed.
  - End turns are half circles, not the real end-winding shape.
  - A design without a wire gets one derived to fill the slot, and says so.
    The Pyleecan Prius uses its machine file's published conductor instead.

### Iron loss

Stator iron loss uses the grade-limit model in
[Materials](../MATERIALS.md#core-loss). It is available for the bundled
M350-50A, and for M400-50A in the pinned Pyleecan Prius, whose imported B-H
curve is that grade. Other steels show iron loss as unavailable. The estimate
needs a nonzero speed and a loaded sweep over one electrical cycle, or half of
one, in equal steps.

- **Qualified:** nothing, and no reference is planned for 0.5.0.
- **Evidence, not a motor check:** against the M400-50A loss table in
  Pyleecan's material library, the M400-50A model is within a mean of ±8% from
  50 Hz to 1 kHz above 0.5 T. Its worst point is near 22%, and it reads about
  24% high at 2.5 kHz. The M350-50A model meets the grade's guaranteed maxima,
  so it reads high against typical sheet at 50 Hz.
- **Experimental because:** "Estimated from the M350-50A grade limits and the
  lamination eddy-current term; not checked against a measured motor." The
  Prius's reason names M400-50A.
- **Range:** results report the share of the loss from harmonics above 1 kHz
  and from flux densities above 1.5 T, outside what the grade limits cover. In
  the Prius loaded case 67% of the iron loss is above 1.5 T, so treat that
  value as an order of magnitude.
- **Not modelled:** rotor iron loss, excess loss as a separate term, and the
  extra loss from cutting and pressing.

### Efficiency at the operating point

Efficiency = P_shaft / P_in, with P_shaft = T_em · ω − P_iron − P_mech and
P_in = T_em · ω + P_copper.

- **Qualified:** nothing. It depends on the experimental iron loss.
- **Experimental because:** "Uses the experimental iron loss."
- **Unavailable:** at zero speed, for zero or negative torque, when there is no
  iron loss (another steel, or a sweep that is not a full or half cycle in
  equal steps), and when the losses exceed the electromagnetic power. The run
  says which.
- **Not modelled:** the losses listed below.

### Magnet temperature derating

Br is scaled linearly from 20 °C by the grade's reversible coefficient, from
the Arnold grade table in [Materials](../MATERIALS.md#magnet-temperature). HcJ
is derated and recorded, but the solve's straight recoil line does not use it.
Above a grade's maximum operating temperature the run carries a warning. A
temperature is refused for magnets without cited coefficients.

- **Qualified:** nothing yet. Protocol 1.6.0 adds the 8p/12s concentrated SPM
  and the FSAE flat IPM with N42 magnets at 60 °C and 100 °C (Br 1.25188 T and
  1.18876 T). They carry the usual A/B gates: mean torque within 8% (YELLOW
  15%), and Back-EMF fundamental and peak within 10% (YELLOW 15%).
  **TODO(freeze):** record the outcome.
  - FEMM models the same derated Br. The gate therefore checks the solve at a
    derated Br, not the coefficient. The coefficient is the catalogue's, and no
    reference measures it.
- **Experimental because:** "Br and HcJ derated linearly with the grade's cited
  reversible coefficients; back EMF and torque at temperature are not yet
  compared with a reference."
- **Not modelled:** irreversible demagnetisation, temperature dependence beyond
  the linear coefficient, a temperature that varies within a magnet, and magnet
  heating. The steel and winding temperatures are set separately.

### Not modelled in any 0.5.0 loss

These losses are absent from copper loss, iron loss, the efficiency at the
operating point and the efficiency map:

- magnet and rotor eddy-current loss;
- AC copper loss, from skin and proximity effects;
- inverter loss, from switching and conduction;
- mechanical loss, except as a single constant. Friction and windage is one
  value in watts, entered under Operating point, and 0 when not entered. The
  efficiency map uses the same value at every speed.

The Losses card names all four, and the run PDF the first three. Every
efficiency leaves these losses out, so none is a measured efficiency.

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
Python dependencies, lint and exported tests on Python 3.11 across Windows, macOS and Linux and on Python 3.15 on Linux,
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
- The 0.5.0 performance outputs (d/q flux linkage and inductances, the
  flux-linkage map, torque–speed and efficiency maps, losses, magnet
  temperature and phase resistance) are experimental unless
  [their own section](#050-performance-outputs) records a passing gate. Losses
  leave out magnet and rotor eddy-current loss, AC copper loss and inverter
  loss, and mechanical loss is a single entered constant.
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
