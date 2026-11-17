# #306: first matched native/FEMM rotor iron-loss comparison

Target: **0.5.9**. Status: **PILOT_NOT_QUALIFIED**.

The first corrected comparison passes the component agreement checks on the
same 96-sample full-turn grid. It supports the fixed-material native motion
implementation on this one motor. The corrected FEMM history still needs
96/192/384 angular refinement; spatial convergence and the release matrix
remain open. No public loss or efficiency calculation changes in this slice.

## Result

| Component | Native mW | FEMM mW | Native minus FEMM | Gate |
|---|---:|---:|---:|---|
| Rotor hysteresis | 16.6003793 | 16.5899343 | +0.06296% | PASS |
| Rotor lamination eddy | 47.5764436 | 47.5840162 | -0.01591% | PASS |
| Rotor iron total | 64.1768229 | 64.1739505 | +0.004476% | PASS |

Each component independently uses the predeclared max(10% of FEMM loss,
0.001 W) tolerance. A matching total cannot hide opposite component errors.
These are estimates from separately solved magnetic fields and a shared
empirical loss law; FEMM does not directly supply these rotating iron-loss
watts. Its independently exported field histories feed a separate direct DFT.

The native mesh contains 17,742 rotor iron cells; FEMM has 9,741 rotor iron
cells and 78,954 total elements. Each integrates its own domain. Rotor masses
are 0.8411630 kg and 0.8409284 kg respectively, a 0.02790% difference, with no
mass renormalization. Field values at individual points are not established
as agreeing to the much smaller integrated-loss percentages in the table.

## Matching and evidence

The case remains the 8-pole/12-slot SPM fixture, 20 A peak, 3,000 rpm,
50 mm stack, M350-50A, stacking factor 1.0 and public gamma 0 degrees
(native gamma 180 degrees). Every reference pose starts from the same
unsolved base, uses the native signed mechanical angle and audited phase
ampere-turn schedule, and independently checks actual solved coil currents.

- The independent fixture sine is `NI_phase = 240 sin(4 theta + 60 - offset)`,
  with degrees, native CCW theta and phase offsets 0/120/240 degrees.
  Density uses each FEMM coil's measured area. The largest solved current
  discrepancy is 6.54e-13 ampere-turns.
- Native Rust uses N42 remanence **1.315 T**, relative permeability **1.05**;
  the Python and frozen reference catalogs list 1.300 T. This collector
  explicitly applies the native constants to every reference magnet alias
  and audits saved materials. Catalog defaults are not accepted as matching.
  No production material constants are changed here.
- Steel B-H input bytes are identical. Winding phase/polarity and magnet
  directions are checked by spatial region matching; the largest winding
  and magnet centroid discrepancies are 0.000411 mm and 0.000386 mm.
- All 97 solves, including the independent endpoint, retain one complete
  reference mesh hash. Closure is 5.27e-11 T maximum and 1.31e-11 T RMS,
  below the registered 1e-6 T and 1e-7 T limits.
- Production sampling on the FEMM fields agrees with the independent DFT
  within 2.92e-16 W across all three components and 24/48/96 subsets.
- **186 Python rotor/loss/reference checks pass**, Ruff passes, and the
  110 sealed historical E/F source files are unchanged. Native backend,
  Rust sources and the executable are unchanged from the native history.

Coarse collection used four workers, finishing in 747.87 s after the seed
pose; summed pose wall time was 2,958.04 s. These are diagnostic timings.
The adjacent JSON binds the raw protocol, analysis, comparison and test
receipt by SHA-256. Raw evidence is retained under
`output/rotor-iron-loss-306/matched-femm-n384-v1` in the parent checkout.

## Convergence and interpretation

The 48-to-96 FEMM step changes hysteresis by 3.05%, eddy by 12.38% and total
by 9.97% of the finer result. Eddy and total therefore fail the original
max(5% of finer, 0.001 W) angular criterion on this coarse step. This is
consistent with 96 being a preliminary subset, not a converged reference.
The native 96/192/384 history already passes both successive angular steps;
the corrected FEMM insertions must establish that result independently.

At 96 samples, 9.85% of the FEMM estimate and 9.95% of the native estimate
come from frequencies above the coefficient model's 1 kHz coverage.
Grade-limit coefficients, biased/minor loops, rotating flux, excess loss,
temperature and loss-field feedback remain model limitations. Agreement
between solvers does not validate those coefficients against measured losses.
This is rotor iron loss only; magnet/component eddy loss, AC winding loss
and full motor efficiency remain separate features.

The older 47.707 mW trajectory remains ineligible because its excitation
does not match this operating point. The earlier corrected three-pose
anchors also used the 1.300 T catalog value and are not a fully matched
material reference. Their original evidence remains unchanged.

## Reproduction and next bounded step

Use the isolated pinned FEMM environment for collection and a fresh native
development process for reporting. Prepare a single zero pose before shards:

```powershell
python -m tools.femm_reference.rotor_matched_history --native-history OUTPUT/native --out OUTPUT/matched --stride 4 --limit 1
# Separate workers: --shard 0/4, 1/4, 2/4 and 3/4.
python -m tools.femm_reference.rotor_matched_history --native-history OUTPUT/native --out OUTPUT/matched --stride 4 --resume --shard 0/4
python -m tools.rotor_matched_report OUTPUT/matched OUTPUT/native --stride 4
```

The protocol registers 384 samples from the start. After reviewing this
result, the next bounded step is to resume this same dataset with stride 2,
then stride 1, retaining every existing pose and the same fixed mesh,
sources and material assumptions. Reports then use the matching stride.
Two successive 96-to-192 and 192-to-384 component convergence checks must
pass before calling the corrected reference angularly converged. Native
and reference spatial refinement, full-versus-sector validation and release
qualification remain separate gates; the full matrix has not started.

The inherited E-adapter identity describes the frozen baseline. The matched
protocol's explicit material and excitation overrides define this study.
Native request, analysis status, source properties, region geometry and
excitation metadata are read for audits; native field values are never used
to generate or postprocess the FEMM fields.

FEMM references: [sliding air-gap motion](https://www.femm.info/doku/doku.php?id=RotorMotion)
and the [manual](https://www.femm.info/Archives/doc/manual.pdf), including
`mo_blockintegral(5)` for area and `(7)` for total current.
