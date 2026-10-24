# coilEM v0.5.0 release notes and plan

Draft of October 23, 2026, written at the top of the 0.5.0 development stack
(`5d23b47`), which builds on the published v0.4.0 (`2ede4e8`). The source still
identifies as coilEM 0.4.0 with Magneto2D 0.3.3; the version bump happens at
the freeze. This draft does not mark v0.5.0 as frozen, measured or released.
Every number marked **TODO(freeze)** comes from the freeze rerun, and every
**TODO(owner)** is a decision for the owner.

0.5.0 is the performance release
([public issue 143](https://github.com/coilemdev/coilem/issues/143)). It answers
"does this motor meet my spec across its operating range?" with torque–speed,
losses and efficiency. Every new number either passes a reference gate or is
labelled experimental with its reason. In this draft all of them are
experimental; [Validation](VALIDATION.md#050-performance-outputs) gives each
one's claim boundary.

## Current evidence

| Item | Recorded result | Remaining work |
| --- | --- | --- |
| macOS native A/B/C/D, protocol 1.4.0 | [29 PASS and the planned unsupported Prius](../benchmarks/macos-native-20261022-5b7cad8/README.md) at `5b7cad8`, against the frozen FEMM v3 bundle | Development evidence. Rerun at the frozen candidate. **TODO(freeze):** commit, outcome |
| Windows native A/B/C/D | Last full record is v0.4.0's, [28 PASS, 1 YELLOW](../benchmarks/windows-prius-requal-20261018/README.md) at `5b6cb61`. The convergence fix has [targeted Windows checks](NONLINEAR_CONVERGENCE_CAP200_WINDOWS.md), not a full rerun | Full rerun at the frozen candidate. **TODO(freeze):** commit, outcome |
| Protocol 1.6.0 FEMM records | [Requested](../benchmarks/abcd-v1.6/FEMM-REQUEST.md): one bundle of 46 records at one adapter commit. None recorded yet | Owner's Windows FEMM run. **TODO(freeze):** bundle commit and hash |
| Protocol 1.6.0 native values | coilEM's values for the 17 new cases at `f6c9fbb`, run with `--no-reference` | Grade against the FEMM bundle at the freeze |
| Physics hash guards | 21 tests fail by design: the stack changes hash-guarded physics sources | Re-pin the hashes at the freeze, after the rerun |
| Pyleecan Prius collection | v0.4.0's record at `d993d76`. The loaded case was solved again with losses, torque unchanged at 353.95 N·m | Full collection at the frozen candidate. **TODO(freeze):** commit, outcome |
| Phase-resistance gate | Planned against a hand calculation; being registered | **TODO(freeze):** gate name and outcome |
| Hardware correlation | ORNL Prius and Honda Accord torque–speed comparison planned in issue 143. [#69](https://github.com/coilemdev/coilem/issues/69) and [#82](https://github.com/coilemdev/coilem/issues/82) are in the 0.5.0 milestone and not in this stack | **TODO(owner):** ship in 0.5.0 or move |
| Wheels and TestPyPI | v0.4.0's rehearsal passed | Rehearse the 0.5.0 candidate on all four wheel targets |

## 1. What changes for users

### Torque–speed and efficiency (public issues 139–142)

- Results has a **Torque–speed** tab. It solves a flux-linkage map over current
  magnitude and current angle (0° to 90°): 5 × 7 points on Preview, 7 × 10 on
  Standard. Each point is a loaded solve over half an electrical cycle.
  - The map shows its progress and time left, and Cancel stops it.
  - Finished points are kept per design, so a cancelled map resumes, and a map
    is reused for a lower peak current.
- From the map, the tab draws peak and continuous **torque–speed and
  power–speed curves** for the entered DC bus, peak and continuous current and
  top speed. Each sample is labelled MTPA, field weakening or MTPV, and the
  solved operating point is marked.
- An **efficiency map** over the torque–speed plane. MTPA control is the
  default and least-loss control is the option. Hovering shows the current and
  angle at each point.
- Apparent Ld and Lq against current, and the MTPA trajectory.

### Loaded d/q flux linkage (public issue 113)

- A d/q card in Results gives Ld, Lq, the saliency Lq/Ld and the
  characteristic current λpm/Ld, then the torque cross-check. The other values
  are under "Show all".
- **Torque–λdq agreement** compares the solved torque with
  1.5·P·(λd·iq − λq·id), which includes reluctance torque. The Solve page shows
  it too.
- An open-circuit run shows λpm and says there is no current angle, inductance
  or torque check for it.
- The Motor constants card's Torque–EMF consistency now reads "not applicable"
  more than 5° off the q-axis, where it would wrongly flag reluctance torque. It
  points to Torque–λdq agreement instead.
- The Stator + PM field view labels the magnet axis d and draws the q axis.

### Winding, losses and efficiency (public issues 136 and 138)

- Design takes a wire size, strands in hand, an end-turn extension and a winding
  temperature. It shows the phase resistance, the mean turn length and the slot
  fill. A design without a wire gets one derived to fill 45% of the slot, and
  says so.
- A **Losses** card in Results gives copper loss (stack and end turns), stator
  iron loss (hysteresis and eddy current, teeth and yoke) and efficiency at the
  solved point.
  - Iron loss is available for M350-50A, and for M400-50A in the pinned
    Pyleecan Prius. Other steels show it as unavailable, with the reason.
  - "Where the loss is" maps iron loss (total, hysteresis or eddy current) or
    copper loss over the motor. Rotor and magnets are hatched and labelled
    not modelled.
- Solve → Operating point takes a **mechanical loss** in watts. It lowers the
  shaft power and efficiency; the solved torque is unchanged.

### Magnet temperature (public issue 137)

- Solve → Operating point takes a **magnet temperature**. Br and HcJ are derated
  linearly from 20 °C with the grade's cited coefficients, for N35, N42, N48,
  N52 and N48SH.
- Above a grade's maximum operating temperature the run carries a warning.
  Magnets without cited coefficients refuse a temperature. At 20 °C, or with no
  temperature set, results are unchanged.

### Exports

- The Torque–speed tab downloads a **performance PDF** (curves, the peak curve at
  12 speeds, the efficiency map, MTPA and Ld/Lq, and notes), a **performance
  CSV** with every number and sample, an **id/iq table CSV** (λd, λq and torque
  on a 21 × 21 grid) and the **map points CSV**. They carry the values the tab
  shows.
- The run PDF and CSV add the d/q record, losses, efficiency, winding and magnet
  temperature.
- Every new output carries its status (experimental) and the reason in the UI,
  the PDFs and the CSVs. The run PDF has a "Status of the performance outputs"
  table, and the run CSV a `status` section.

### Smaller changes

- Kt is labelled per peak or per rms ampere everywhere: the run CSV gives both,
  the run PDF shows N·m/A rms, and Compare runs uses Results' value
  ([#153](https://github.com/coilemdev/coilem/issues/153)).
- The Pyleecan Prius's tooth and yoke widths display rounded; the stored values
  are unchanged ([#154](https://github.com/coilemdev/coilem/issues/154)).
- The Pyleecan Prius loaded case now records the currents its explicit source
  applies, so its d/q record has a current angle (50.0°) and a Torque–λdq
  agreement (99.96%). Its torque, λd and λq are unchanged.

### Solver convergence (public issues 11 and 12)

- The nonlinear stopping test now measures the actual permeability mismatch
  ([public PR 155](https://github.com/coilemdev/coilem/pull/155)). This changes
  some qualified numbers; see section 2.
- Each motor result records its nonlinear convergence per position: method,
  iterations, residuals and stopping test
  ([Nonlinear convergence](NONLINEAR_CONVERGENCE.md)).
- The BLDC benchmark requests raise their iteration cap from 100 to 200
  ([protocol 1.4](../benchmarks/abcd-v1.4/README.md)); no gate changes.
- **TODO(owner):** showing convergence in Results, PDF and CSV (#12) is not in
  this stack. Ship it, or keep #12 open for a later release.

## 2. Changes to qualified numbers

Two fixes change numbers that 0.4.0 qualified. The figures are from the macOS
development run at `5b7cad8` against the v0.4.0 Windows record at `5b6cb61`
([full comparison](../benchmarks/macos-native-20261022-5b7cad8/comparison-vs-v0.4.0-windows-5b6cb61.md)).
The macOS record at `738d951` in the same comparison shows that platform
differences are at most about 0.1%. **TODO(freeze):** replace these with the
freeze report's macOS and Windows numbers.

| Group | Cases | Mean torque error vs FEMM | Worst torque error | Mean back-EMF error |
| --- | ---: | --- | --- | --- |
| A, SPM | 8 | 0.27% → 0.33% | 0.48% → 0.63% | 0.07% → 0.08% |
| B, flat IPM | 6 | 0.34% → 0.31% | 0.64% → 0.66% | 0.33% → 0.30% |
| B, V-shape IPM | 6 | 4.55% → 5.13% | 5.90% → 7.05% | 2.39% → 6.50% |
| C, distributed | 4 | 2.67% → 2.87% | 4.90% → 5.20% | 0.18% → 0.23% |

**Slot current from each coil side's meshed area.** Slot current density used
to be each slot's ampere-turns over a nominal trapezoid. Now each coil side
carries its share of N·I/paths over its own meshed area.

- **Plain slots** used to receive slightly more than N·I/paths. Their loaded
  torque falls by 0.02% to 0.65%. The two 8p/48s cases move −0.01% and +0.14%,
  within the platform difference. Back-EMF is unchanged.
- Torque–λdq agreement now reads 99.86–100.29% in every loaded case.
- **Shoed slots** were under-driven, and no registered case had them. The app's
  example 8p/12s SPM at 30 A rms and γ 30° rises from 9.233 to 9.660 N·m
  (+4.62%), and the Honda Accord 24s/16p at 30 A rms from 24.052 to 24.632 N·m
  (+2.41%). Protocol 1.6.0 adds the shoed example as a case.

**Corrected nonlinear stopping test (public issue 11).** The weak-flux V-shape
IPMs converge further than before.

- Their back-EMF rises 4.7–6.6% and their torque 0.2–1.1%, both away from FEMM.
- Five V-shape cases now sit 8.1–8.6% from FEMM on the back-EMF fundamental and
  9.0–9.6% on the peak, against 10% gates.
- `ipm_vshape_8p12s_baseline_contract` changes from YELLOW to PASS: its
  converged peak error falls from 14.8% to 9.0%.
- V-shape IPM stays experimental. The FEMM request asks for a check of FEMM's
  own convergence on these bridges. **TODO(freeze):** record that check.

The Phase D BLDC gates are unchanged.

## 3. Benchmark protocol 1.6.0

[Protocol 1.6.0](../benchmarks/abcd-v1.6/README.md) (harness 1.8.0) keeps every
protocol 1.4.0 request, golden vector and gate. It adds 17 cases derived from
registered requests:

| Cases | Phase | What it checks |
| --- | --- | --- |
| `spm_8p12s_example_shoed` | A | The slot-current fix, on the app's shoed example |
| `spm_8p12s_concentrated__magnet_{60,100}C` | A | Br derating, N42 at 60 °C and 100 °C |
| `ipm_flat_8p12s_fsae_contract__magnet_{60,100}C` | B | The same, on the FSAE flat IPM |
| `spm_8p12s_concentrated__dq_I{20,40}_g{0,30,60}` | A | Loaded λd and λq at 1× and 2× current, γ 0°, 30° and 60° |
| `ipm_flat_8p12s_fsae_contract__dq_I{50,100}_g{0,30,60}` | B | The same, on the FSAE flat IPM |

- Every new case has the usual A/B gates: mean torque within 8%, and Back-EMF
  fundamental and peak within 10%.
- The 12 d/q points add `lambda_d` and `lambda_q`, within 3% of the
  reference's |λdq| (YELLOW 6%), and `reference_dq_torque`, FEMM's own d/q
  torque against its solved torque, within 2% (YELLOW 5%).
- The harness computes FEMM's λd and λq from its raw waveforms with coilEM's
  own transform, so the two sides cannot differ by convention.

There is no FEMM record yet for any new case, so protocol 1.4.0 stays the
default. At the freeze the owner's protocol 1.6.0 bundle arrives and 1.6.0
becomes the default suite.

**TODO(freeze):**

- the FEMM bundle's reference commit and manifest hash;
- the 17 new cases' outcomes on macOS and Windows;
- the published platform records that `coilem benchmark` matches under 1.6.0.

## 4. Pyleecan Prius losses

The pinned Pyleecan Prius now has an experimental iron loss and a copper loss
from its own conductor ([details](benchmarks/pyleecan-prius-v1/README.md#losses-in-the-app)).

- **Iron loss** uses an M400-50A grade-limit model, because the imported B-H
  curve is Pyleecan's M400-50A. It is built like the M350-50A model; see
  [Materials](../MATERIALS.md#core-loss).
- **Copper loss** uses the machine file's conductor, since the pinned design
  sets no wire: 13 strands of 0.912 mm copper, 9 turns per coil, one path and a
  19.366 mm straight overhang. coilEM adds its half-circle end turn to that
  overhang. Pyleecan's own formula counts the straight overhang only; with the
  arcs removed coilEM reproduces its 35.95 mOhm.

The loaded case (250 A peak at Φ0 140°, 2,000 rpm, 32 positions over one
electrical cycle) on macOS arm64:

| Output | Value |
| --- | ---: |
| Torque | 353.95 N·m, unchanged |
| Phase resistance at 20 °C | 71.7 mOhm (was 47.6 mOhm with a derived wire) |
| Copper loss | 6.72 kW (was 4.46 kW) |
| Iron loss, hysteresis + eddy | 612 W (274 W + 338 W), at 133 Hz |
| Share of iron loss above 1.5 T / above 1 kHz | 67% / 4.6% |
| Efficiency, no mechanical loss | 90.9% |

Most of the iron loss comes from flux densities above 1.5 T, outside the range
the grade limits cover, so treat it as an order of magnitude. The reference
draws its stator as one region, so there is no teeth and yoke split. Pyleecan's
own Prius loss test is skipped at the pinned commit, so there is no Pyleecan
loss value to compare with. The benchmark itself still checks torque, back-EMF
and flux linkage only. **TODO(freeze):** confirm these values in the freeze's
Prius collection.

## 5. Known limitations

- **Every 0.5.0 output is experimental** until its gate passes at the freeze:
  loaded λd/λq, Ld/Lq, the flux-linkage map, the torque–speed envelope, the
  efficiency map, copper and iron loss, efficiency, magnet temperature derating
  and phase resistance. Ld and Lq stay experimental even if λd/λq pass, because
  the gate does not bound them tightly (**TODO(owner):** confirm).
- **Losses not modelled:** magnet and rotor eddy-current loss; AC copper loss
  (skin and proximity effects); inverter loss. Mechanical loss is a single
  constant the user enters, the same at every speed.
- **Iron loss** comes from guaranteed grade limits and the lamination eddy-current
  term. It is not fitted to measured sheet or checked against a measured motor.
  It covers the stator only, does not model excess loss separately or the
  effect of cutting and pressing, and is unavailable for other steels.
- **Torque–speed** assumes sinusoidal steady-state current. It ignores inverter
  drops, dead time, PWM ripple and overmodulation. The continuous curve is a
  current limit, not a thermal rating, and there is no thermal model: winding
  and magnet temperatures are inputs.
- **Magnet temperature** derates Br linearly and records HcJ. It does not model
  irreversible demagnetisation.
- **Phase resistance** uses half-circle end turns and DC resistance.
- **V-shape IPM** stays experimental; its back-EMF margin to the 10% gate is now
  1.4–1.9 points.
- **Convergence display** in Results, PDF and CSV (#12) is not in this stack.
- **Hardware correlation** (ORNL Prius, Honda Accord) is not a qualification.
  It is not done in this stack (**TODO(owner)**).
- The 0.4.0 limits still apply: qualification is agreement with FEMM on the
  measured fixtures, not a hardware measurement; six-step is an ideal
  current-commanded model; motor results are 2D estimates. See the
  [0.4.0 release notes](../RELEASE_NOTES.md#qualification-and-remaining-limits).

## 6. Freeze and release

- [ ] Merge the whole 0.5.0 stack. All results-changing work must be in before
  the freeze.
- [ ] Receive the protocol 1.6.0 FEMM bundle, with the V-shape convergence
  check.
- [ ] Freeze one clean candidate commit and record it before collection.
- [ ] Rerun A/B/C/D on macOS and Windows with protocol 1.6.0, and the full
  Pyleecan Prius collection. Publish the reports and records.
- [ ] Re-pin the physics hashes from that report, so the hash-guard tests pass
  again.
- [ ] Change the status of each output whose gate passed, in the code and in
  [Validation](VALIDATION.md#050-performance-outputs) together. Do not relax a
  gate or relabel an output to get a green report.
- [ ] Bump `backend/__init__.py`, `frontend/package.json`, both versions in
  `frontend/package-lock.json` and the design-file writer to **0.5.0**.
  **TODO(owner):** decide whether Magneto2D moves from 0.3.3, since the
  convergence fix changes its sources.
- [ ] Rewrite `RELEASE_NOTES.md` from this draft, and fill every TODO here, in
  the README and in Validation.
- [ ] Pass the snapshot and publication checks, tests, lint, audits, the
  frontend build and the browser workflows on the candidate.
- [ ] Run the wheel workflow with `publish=none`, then the TestPyPI rehearsal
  and its install acceptance.
- [ ] Owner accepts the scope, discrepancies and notes; tag `v0.5.0`; publish to
  PyPI and check the published wheels.
