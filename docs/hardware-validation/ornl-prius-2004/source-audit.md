# ORNL 2004 Prius traction motor: Phase A source audit

This is the Phase A deliverable of [#69](https://github.com/coilemdev/coilem/issues/69): a source audit and go/no-go recommendation for an exploratory hardware correlation of coilEM against ORNL's measurements of the 2004 Toyota Prius traction motor (MG2). It contains documents and data only. No model was built, no solver was run, and no qualification wording changes.

The data files in this folder are JSON, because the public snapshot gate admits only reviewed CSV files:

- [`sources.json`](sources.json): the five ORNL reports audited, with the SHA-256 of each retrieved PDF.
- [`input-provenance.json`](input-provenance.json): one row per model input, with its value, source location and provenance class.
- [`target-back-emf.json`](target-back-emf.json): the measured no-load back-EMF table (the Phase B target).
- [`target-locked-rotor.json`](target-locked-rotor.json): the locked-rotor torque table (the Phase C target), with both of ORNL's angle conventions.
- [`rotor-pocket-measurements.json`](rotor-pocket-measurements.json): the V-pocket geometry measured from ORNL's vector lamination drawing, for all 8 poles.

Page references use the report's printed page number, followed by the PDF page: "p.21 (PDF 30)".

## Sources

All five are primary ORNL technical memoranda retrieved from OSTI on 2026-10-13. No secondary source (paper, blog, forum or software example) is used for any input or target value.

| ID | Report | Title | Date | Used for |
| --- | --- | --- | --- | --- |
| S1 | ORNL/TM-2004/185, revised May 2007 | Report on Toyota/Prius Motor Torque Capability, Torque Property, No-Load Back EMF, and Mechanical Losses | May 2007 | Back-EMF definition (line-to-line), test method, torque scaling |
| S2 | ORNL/TM-2006/423 | Evaluation of 2004 Toyota Prius Hybrid Electric Drive System | May 2006 | Back-EMF table, locked-rotor table, Ld/Lq, pole count |
| S3 | ORNL/TM-2004/247, revised FY 2007 | Evaluation of 2004 Toyota Prius Hybrid Electric Drive System Interim Report – Revised | FY 2007 | Same back-EMF table; locked-rotor angle in electrical degrees |
| S4 | ORNL/TM-2004/137 | Report on Toyota/Prius Motor Design and Manufacturing Assessment | July 2004 | Stack length, winding connection, laminations, magnet B-H figure |
| S5 | ORNL/TM-2005/33 | Report on Toyota Prius Motor Thermal Management | February 2005 | Dimensioned stator/rotor lamination drawing; slot contents |

#69 names S1 and S2 (plus the interim S3). S4 and S5 are also primary ORNL reports, found during this audit. **S5 holds the only dimensioned cross-section in the five reports**: its Fig. 21, "2004 Prius Stator Lamination", p.25 (PDF 32). None of the five reports has a table of motor dimensions.

## Findings

1. **Core geometry is stated, not guessed.** S5 Fig. 21 dimensions the stator OD (10.600 in), bore (6.375 in), rotor OD (6.314 in), rotor bore (4.356 in), slot depth (1.320 in), slot-bottom round and slot-mouth details. S4 states the stack length (3.3 in). The 48 slots and 8 poles are stated in S5 and S2.
2. **The magnet pockets are drawn but not dimensioned.** Fig. 21 is a vector (CAD) drawing, so the pocket outlines can be measured from the PDF's own path coordinates instead of being read off an image. See [Pocket measurement](#pocket-measurement). The pocket is one connected V per pole with an included angle of about 145°, a width of about 6.8 mm across each arm and magnet seats of about 18.4 mm.
3. **Turns per coil are not stated anywhere.** S4 says the 2003 and 2004 motors have the same turns per coil, but gives no number. S5's thermal model shows "Nine Bundles of Copper Wire" per slot (Fig. 24, p.27 (PDF 34)). Reading a bundle as one turn gives 9 turns per coil, which is an inference. Back-EMF scales directly with turns, so this is the dominant assumption.
4. **Magnet properties come from a figure.** S4 Fig. 14 plots the Prius magnet's demagnetization line: Br ≈ 12.3–12.4 kG (1.23–1.24 T) and Hc ≈ 11.0 kOe, which gives a recoil permeability of about 1.12. The line is extrapolated from points measured at H ≈ −7.2 to −4.7 kOe, and the test temperature is not stated. ORNL says only that the magnets "appear" sintered. NdFeB is not named.
5. **Steel grade is not stated.** S4 gives 0.014 in (0.356 mm) rotor laminations. No grade, B-H curve or stacking factor appears in the five reports.
6. **The target is well defined, except for one word.** The back-EMF table (S2 Table 3.4 = S3 Table 3.4) gives line-to-line RMS and peak voltage at 12 motor speeds from 502 to 5,998 rpm, with the oil at a nominal 25 °C. Both reports head the columns "Scaled back-emf" without defining the scaling. S1 plots the same data as "Voltage (LL)" with no scaling mentioned.
7. **No cogging target exists.** The five reports mention cogging only as a component of measured mechanical loss (S2 p.18 (PDF 27); S3 p.18 (PDF 26)). There is no cogging-torque measurement, so no Phase D is proposed.
8. **coilEM's `v_shape` rotor cannot represent this pocket** without a geometry change. `pyleecan_holem50` is meant for this shape but is outside the public Magneto2D support boundary. See [Representability](#representability-in-coilem).

## Target: no-load back-EMF

[`target-back-emf.json`](target-back-emf.json) transcribes S2 Table 3.4, p.21 (PDF 30). S3 Table 3.4, p.22 (PDF 30) is identical, and every row was checked by script against the extracted text of both reports. These are table values, so no digitization was needed.

### Conversion chain

- **Speed.** The table's motor-shaft speed is the axle speed times 4.114: the differential gears were welded, which changed the axle-to-motor ratio from 2.057:1 to 4.114:1 (S1 Appendix, p.15 (PDF 21)). The table agrees: 5,998 / 1,458 = 4.114. Use the motor-shaft speed column directly.
- **Frequency.** For 8 poles, f = n / 15. The measured frequencies are within −1.5% to +1.0% of n / 15 (for example 401.3 Hz against 399.9 Hz at 5,998 rpm). For per-hertz quantities, use the measured frequency.
- **Line-to-line, not phase.** S1 Fig. 13, p.11 (PDF 17) labels the voltage axis "Voltage (LL)". S1 Appendix II, p.15 (PDF 21) says "two of the three motor phases" were connected to the power meter. S2 p.42 (PDF 51) calls the back-EMF test relationship "1.338 Hz/VLL(rms)", which is numerically V(LL, rms) per Hz. Phase quantities are line-to-line / √3.
- **RMS and peak.** Both columns are line-to-line. Peak/RMS is 1.54–1.79, above √2, because the waveform has harmonics (S2 p.21; S1 p.10). Every peak value is a multiple of 25 V (75 V, 150 V, … 850 V), so the peak column appears to have been read to 25 V resolution: about ±12.5 V. The RMS column has 0.1 V resolution and is the better quantity to compare.
- **Voltage constant.** RMS(LL)/frequency is 1.29–1.37 V/Hz above 1,000 rpm (1.24 V/Hz at 502 rpm). S2 states 1.33 Vrms/Hz in Table 6.2, p.61 (PDF 70) and 1.338 on p.42.
- **"Scaled".** Undefined in S2 and S3. The likeliest reading is that instrument readings were scaled to terminal voltage, which S1 presents unscaled as "Voltage (LL)". Phase B needs this confirmed or explicitly accepted (see the recommendation).
- **Waveform shape.** S1 Fig. 14, p.11 (PDF 17) shows oscilloscope traces at 500, 3,000 and 5,500 rpm as images only, with no numerical data. A waveform-shape comparison would need these digitized.

### Secondary targets (not for Phase B scoring)

- No-load air-gap flux density versus slot number for 2003 and 2004 (S4 Fig. 13, p.11 (PDF 12)): about 7,500 G peak for 2004. Figure only; the probe and radius are not stated.
- Static inductances Ld = 1.92 mH and Lq = 5 mH (S2 p.42 (PDF 51)).
- A no-load motoring test at 900 rpm, supply voltage against current (S5 Table 3, p.12 (PDF 19)). This is a driven test, not back-EMF.

## Target: locked-rotor torque (Phase C, stretch)

[`target-locked-rotor.json`](target-locked-rotor.json) transcribes S2 Table 3.2, p.20 (PDF 29), and S3 Table 3.2, p.21 (PDF 29). Both list the same torques at 50–250 A, under different angle labels:

- S2 labels the angle "Motor-Shaft Angle", 90–134° in 2° steps.
- S3 labels it "Electrical Position", 0–176° in 8° steps.
- They agree if electrical position = 4 × (shaft angle − 90°), since the motor has 8 poles.

The DC excitation is Ia in phase a and −Ia/2 in phases b and c (S1 p.7 (PDF 13)). S1 measured the initial configuration at the wheel axle, with motor torque = 0.486 × axle torque. The revised configuration welded the planetary carriers and measured motor torque directly at the engine spline (S1 p.4 (PDF 10)). S2 says the tables come from the 2005 tests with the new positioning mechanism. Phase C must decide which configuration each value comes from before comparing.

## Discrepancies found

1. **#69's "≈500 V at 3,600 rpm" is a peak value.** S1 p.10 (PDF 16) says "At 3600 rpm, the back-emf reaches 500 V". The table gives 500 V **peak** at 3,501 rpm (315.7 V RMS). Phase B should use the table, not the prose.
2. **Locked-rotor maxima disagree within S2.** S2 Table 6.3, p.61 (PDF 70) gives 140, 260 and 400 Nm at 75, 150 and 250 A. S2 Table 3.2 peaks at 117.7, 229.0 and 339.0 Nm, and S1 p.7 says 250 A "produces about 340 Nm" and that about 325 A would be needed for 400 Nm. Table 6.3 is inconsistent with both, so Phase C should not use it.
3. **Fig. 3.10 differs slightly from Table 3.2** (S2 p.20). For example, Fig. 3.10 shows 221 Nm at 150 A, against a Table 3.2 maximum of 229 Nm. The text says the figure prefers August 2005 data where the June and August data differ.
4. **The locked-rotor angle labels differ** between S2 and S3, as described above.

## Pocket measurement

S5 Fig. 21 is a vector drawing: the rotor is drawn in blue paths, with dimensions in red and the stator in black. The method:

1. Extract every path segment on the page with its stroke color.
2. Fit a circle to the outermost blue points (413 points; maximum residual 0.44 pt, about 0.6 mm). Scale the drawing so this circle is the dimensioned rotor OD of 6.314 in. That gives 18.688 pt/in, or 1.359 mm per pt.
3. Check the scale against the other dimensioned features. Blue points cluster at 4.33–4.37 in diameter, against the stated ø4.356 rotor bore. The innermost stator edges sit at about 6.35 in, against the stated 6.375 in bore. The slot bottoms reach about 9.07 in, against 6.375 + 2 × 1.320 = 9.015 in.
4. For each pole, rotate the pocket into a frame with its d-axis vertical. Fit the long straight edges of each arm, then measure the arm angle, the perpendicular width between the long edges, the edge lengths, the apex depth and the minimum distance to the rotor OD.

The results for all 8 poles, both arms, are in [`rotor-pocket-measurements.json`](rotor-pocket-measurements.json):

| Quantity | Range over 16 arms | Note |
| --- | --- | --- |
| Arm angle from the tangential direction | 16.8–18.0° (mean 17.4°) | Included angle ≈ 145° |
| Pocket width across an arm | 6.67–6.85 mm | |
| Magnet seat (inner edge, between stop notches) | 18.3–18.6 mm | |
| Arm outer-edge length | 21.6–21.9 mm | |
| Apex depth below the rotor surface | 10.4–11.2 mm (mean 10.8) | The spread follows a centre offset of about 0.4 mm |
| Pocket tip to rotor OD | 0.84–1.06 mm against the nominal circle | The drawing states 0.060 in and 0.056 in (1.52 and 1.42 mm); the difference is within the 0.6 mm outline residual |

**Estimated read-off error:** about ±0.5 mm on absolute positions (apex depth, bridges), ±0.1 mm on widths and lengths, and ±0.5° on angles. The pole-to-pole scatter supports these figures. For the bridges, use the stated 0.056–0.060 in callouts.

## Representability in coilEM

coilEM's `v_shape` rotor (`backend/geometry_drawer.py`, `compute_v_shape_magnet_placements`) cannot represent this pocket, for three separate reasons:

1. **Angle range.** `RotorConfig.v_angle_deg` is limited to 0–120° by the configuration schema (`backend/models/config.py`). The measured included angle is about 145°, so the design fails validation before any geometry is built.
2. **Pocket topology.** `v_shape` places two separate rectangular slabs per pole, each in its own rectangular air pocket. A steel web of `inner_web_thickness_mm` separates them at the apex, and the geometry validator expects two pocket regions per pole. The Prius has one connected pocket per pole, with no steel web at the apex: the two magnet seats are separated only by stop notches.
3. **Flux barriers.** A `v_shape` pocket is the magnet slab plus a uniform `pocket_clearance_mm`. The Prius pocket extends beyond each magnet seat as an air flux barrier toward the q-axis, ending at the stated 0.056–0.060 in bridges. Those barriers set the magnet leakage, and leakage directly affects no-load back-EMF.

Raising the angle limit alone would still model a different rotor: separate slabs with a web, and no end barriers. A Phase B result on that geometry would be a fitted approximation, not a prediction for ORNL's motor.

`pyleecan_holem50` (Pyleecan's HoleM50 slot) is the pocket family for this shape: a connected V with end barriers, three air regions per pole. coilEM has it in the configuration model and geometry builder, but it is outside the public IPM policy. The A/B/C/D README says that "geometry helpers exist, but native meshing/field solves and matched FEMM qualification are needed before enabling public support" (`benchmarks/abcd-v1.1/README.md`). Phase A did not test whether HoleM50 meshes and solves today outside that policy. Nor did it check whether the measured pocket maps onto HoleM50's W0–W4 and H0–H4 parameters within the read-off error.

## Gap list

Sensitivities are plausible magnitudes for the no-load fundamental back-EMF, estimated from how each input enters the machine equations. They are not computed results.

| Input | Class | Plausible effect on back-EMF | How to close it |
| --- | --- | --- | --- |
| Turns per coil (9) | inferred-from-figure | Proportional: ±1 turn = ±11% | A primary source with an explicit count; otherwise accept 9 and report the ±1-turn band |
| "Scaled" back-EMF | undefined | A direct factor if it is not unity | Owner acceptance that the values are terminal LL volts, consistent with S1's "Voltage (LL)" |
| Winding layout and pitch | assumed | Single-layer full pitch with q = 2 gives kw1 ≈ 0.966; a 5/6 short pitch would lower it by about 3.4% and change the harmonics (and so the peak) | A primary source; otherwise state the assumption |
| Magnet Br (1.23–1.24 T) and temperature | inferred-from-figure | About proportional: ±1–2% from read-off; about −0.1%/K if the figure temperature differs from 25 °C | Run the source range as a band |
| Magnet dimensions | assumed, bounded by the pocket | ±2–3% | Use the measured seat; run the clearance range as a band |
| Pocket geometry (vector-measured) | inferred-from-figure | Bridges and barriers set leakage: ±1–2% for ±0.1 mm of bridge | Use the stated bridge callouts; measure the rest from the vectors |
| Steel grade and B-H | assumed | A few percent at no load, mainly through bridge saturation | Run two plausible 0.35 mm grades as a band |
| Effective stack length and end effects | 2D allowance | 1–3% | Report the 2D result at 83.82 mm and state the allowance |
| Skew | assumed none | 1–2% on the fundamental if skewed; more on the peak | Inspect S4's rotor photographs; otherwise state the assumption |
| Magnet temperature at test | assumed 25 °C (the oil temperature) | About −0.1%/K | State it |

The turn count was deliberately **not** checked against the measured back-EMF. Choosing it to match the target would make Phase B a fit, not a blind prediction.

## Existing benchmark fixture compared with the primary sources

The A/B/C/D suite carries a Prius fixture, `ornl_prius_2004_ipm` (`benchmarks/main-20261009-bad71d9/fixtures/ornl_prius_2004_ipm.json`). It is marked UNSUPPORTED and is not solved. Its origin is not documented in the repository. Against S1–S5:

| Fixture field | Fixture value | Primary source | Verdict |
| --- | --- | --- | --- |
| `stator.OD_mm` | 269.24 | 10.600 in = 269.24 mm (S5) | Matches |
| `stator.ID_mm` | 161.9 | 6.375 in = 161.93 mm (S5) | Matches |
| `rotor.OD_mm` | 160.4 | 6.314 in = 160.38 mm (S5) | Matches |
| `rotor.ID_mm` | 110.64 | 4.356 in = 110.64 mm (S5) | Matches |
| `stator.stack_length_mm` | 83.82 | 3.3 in (S4) | Matches |
| `stator.slot_count`, `rotor.pole_count` | 48, 8 | S5, S2 | Matches |
| `winding.turns_per_coil` | 9 | inferred from S5 Fig. 24 | Consistent with the inference |
| `winding.parallel_paths` | 1 | derived from S4 (series) | Matches |
| `stator.yoke_thickness_mm` | 19.37 | 20.13 mm derived from S5 | Differs by 0.76 mm |
| `stator.slot_opening_mm` | 2.0 | 0.076 in = 1.93 mm (S5) | Close |
| `stator.tooth_width_mm` | 5.6 | not dimensioned | Not traceable |
| HoleM50 pocket fields, `magnet_width_mm` 18.9, `magnet_thickness_mm` 6.5 | various | pocket measured: seat 18.3–18.6 mm, width 6.67–6.85 mm | Not traceable to S1–S5; secondary — not used |
| `materials.magnet_grade` `Prius_2004_NdFeB` | Br 1.240 T, μr 1.05 (an assumption per `MATERIALS.md`) | Br 1.23–1.24 T, μrec ≈ 1.12 from S4 Fig. 14 | Br agrees; μr differs |
| `materials.stator_steel` | M350-50A (0.50 mm) | grade not stated; 0.356 mm laminations (S4) | Assumption; thickness mismatch |

The core dimensions in the fixture trace to S5 and S4. The rotor pocket, magnet and some stator-slot fields do not trace to these sources.

## Fallback inventory

#69 asks for other ORNL-benchmarked motors whose topology is in coilEM's qualified scope (SPM, or flat-buried IPM with concentrated windings). This audit found two candidates, but **did not confirm either topology** and did no modelling:

- **2005 Honda Accord Hybrid:** ORNL/TM-2006/535, *Evaluation of 2005 Honda Accord Hybrid Electric Drive System* (Staunton, Burress, Marlino, September 2006). Its table of contents includes back-EMF and locked-rotor tests.
- **Hyundai Sonata (2011) motor:** a 2013 DOE Annual Merit Review presentation (ape006, Burress) describes 24 stator teeth and 16 rotor poles, "very similar to Honda hybrids".

Both need their rotor topology confirmed from the primary report before they could be considered.

## Recommendation: GO on sources; Phase B blocked on rotor representation

**The sources are sufficient for an exploratory Phase B.**

- The core geometry can be reconstructed from a primary ORNL drawing without guessing.
- The back-EMF target is a primary table with a documented line-to-line, RMS and peak definition.
- The remaining uncertainties can be reported as bands.

**Phase B cannot start yet.** No coilEM rotor family can currently model ORNL's pocket faithfully and solve it. Per #69 §3, that is a separate issue, not part of a validation PR.

Owner decisions needed before Phase B:

1. **Rotor representation: which route to file.** Either:
   - extend `v_shape` (included angles up to about 150°, a connected pocket with no apex web, and end barriers); or
   - make `pyleecan_holem50` mesh and solve natively for exploratory runs, after first checking that the measured pocket maps onto its parameters.

   Either route is solver/geometry work tracked outside #69. Phase B is blocked on it.
2. **Turns per coil.** Either accept 9, inferred from S5 Fig. 24, as the frozen input, with the ±1-turn (±11%) band reported up front, or require a better source first.
3. **"Scaled" back-EMF.** Accept the table values as motor-terminal line-to-line volts, consistent with S1's "Voltage (LL)" plot of the same data.

If the owner decides not to fund the rotor work, the recommendation is **NO-GO** for Phase B. The audit, the transcribed targets and the measured pocket geometry remain as the published record.
