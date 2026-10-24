# Phase resistance against a hand calculation (protocol 1.6.0 gate)

Public issue 143 puts "phase resistance vs a hand calculation" in the 0.5.0 qualification scope. This file is that hand calculation. It is written out step by step so a reviewer can redo it with a calculator.

The phase resistance is a closed-form result of the winding's geometry, its wire and the conductor's data, so this gate needs no field solve and no FEMM. Its parts:

- **The registration:** [`phase_resistance_gate.json`](phase_resistance_gate.json) holds the cases, their declared inputs and the hand results below.
- **The gate:** [`backend/benchmark_suite/resistance_metrics.py`](../../backend/benchmark_suite/resistance_metrics.py) compares coilEM's `phase_resistance_ohm` with the hand value.
  - **PASS** ≤ 1%, **YELLOW** ≤ 3%, else **FAIL**.
- **The test:** [`tests/test_phase_resistance_gate.py`](../../tests/test_phase_resistance_gate.py) runs the gate. It also re-derives every registered hand value from the fixture's raw parameters with the formulas below, so the registration and this file cannot drift apart.

## What coilEM's resistance includes

`backend/winding_resistance.py` (the `WindingResistance` record, public issue 136) computes the DC resistance of one phase from:

| Term | Source |
| --- | --- |
| Strand diameter and strands in hand | `winding.wire` |
| Series turns per phase | `slot_count · turns_per_coil / 6`. `turns_per_coil` is coilEM's conductor count of one slot. |
| Parallel paths `a` | `winding.parallel_paths`. Each path has N/a turns, and the paths are in parallel: R = ρ·N·MLT / (A·a²). |
| Stack length | `stator.stack_length_mm`. It gives the two active legs of each turn. |
| Half-circle end turn | At each end, a half circle whose diameter is the arc between the coil's two coil sides. The arc is taken at the mean radius of their area centroids. A tooth coil's sides are the slot halves next to its tooth. A distributed coil's sides are the whole slots, a coil span apart. |
| Straight extension | `wire.end_turn_extension_mm`: straight out of the slot and back, at both ends. That is 4 lengths per turn. |
| Resistivity and its temperature coefficient | IEC 60028 annealed copper or IEC 60889 hard-drawn aluminium, at 20 °C (below). |
| Winding temperature | `solve_params.winding_temperature_C`; 20 °C when unset. R(T) = R20 · (1 + α·(T − 20)). |

**The pinned Prius.** A pinned reference design without a wire of its own uses its published conductor. The Pyleecan Toyota Prius has 13 strands in hand of 0.912 mm and a 19.366 mm straight overhang. This is the same calculation with a specified wire: strands in hand, the straight extension and the half-circle arc. Only the source of the wire differs (`REFERENCE_WIRES` in `backend/winding_resistance.py`).

`tests/test_winding_resistance.py` already checks the Prius's straight part against Pyleecan's own formula, which leaves the arc out.

**Not included.** These are outside the calculation and outside this gate:
- AC effects: skin and proximity.
- Lead and coil-to-coil connection lengths.
- Any end-turn shape other than the half circle.

**A design without a wire** gets a wire sized to fill the slot to its fill limit (45% by default). That value is an estimate, not the resistance of a real winding. Its record therefore stays experimental, with its own reason; the gate covers designs with a wire.

## Conductor data

| Conductor | Standard | ρ at 20 °C | α at 20 °C |
| --- | --- | --- | --- |
| Annealed copper | IEC 60028 | 1/58 Ω·mm²/m = 0.0172414 Ω·mm²/m | 0.00393 /K |
| Hard-drawn aluminium | IEC 60889 | 0.028264 Ω·mm²/m | 0.00403 /K |

With ρ in Ω·mm²/m, a length in metres and an area in mm², R comes out in ohms.

## The gate cases

Two registered suite fixtures, one concentrated and one distributed. The distributed one is run once in copper and once in aluminium, so both conductors are covered. Both fixtures are pinned by SHA-256 in the registration, as the suite pins them.

The fixtures are field-solve requests, so they carry no wire and no winding temperature. Each case therefore declares only these:
- the wire;
- the conductor;
- the winding temperature.

Everything else comes from the fixture unchanged: slots, bore, yoke, teeth, slot opening, stack, conductors per slot, parallel paths, winding type, layers and coil span.

The declared values are chosen to exercise every term at once:
- several strands in hand;
- a nonzero straight extension;
- a winding temperature well above 20 °C.

| Case | Suite fixture | Wire | Conductor | T |
| --- | --- | --- | --- | --- |
| `spm_8p12s_concentrated__copper_80C` | `spm_8p12s_concentrated__baseline` | 2 × 1.25 mm, 5 mm extension | copper | 80 °C |
| `spm_8p24s_distributed__copper_120C` | `spm_8p24s_distributed_femm_validation` | 4 × 1.6 mm, 15 mm extension | copper | 120 °C |
| `spm_8p24s_distributed__aluminum_120C` | `spm_8p24s_distributed_femm_validation` | 4 × 1.6 mm, 15 mm extension | aluminium | 120 °C |

## Method

The hand calculation uses only the fixture's parameters and closed-form geometry, with exact arcs. It does not use coilEM's geometry, its tessellated slot regions or its coil list.

1. **Series turns.** Count the conductors of one phase from the winding layout, then halve them, since a turn has two coil sides.
2. **Turn copper area.** A = strands · π·d²/4.
3. **The slot.** With the tooth shoes off, coilEM draws each slot (`backend/geometry_drawer.py`, `_slot_body_width_mm` and `_slot_mouth_width_mm`) as:
   - **at the bore**, radius r_b = ID/2, a mouth of `slot_opening_mm` of arc, so its half-angle is θ_m = (opening/2) / r_b;
   - **at the slot bottom**, radius r_s = OD/2 − yoke, the pitch arc 2π·r_s/Q less `tooth_width_mm`, so the tooth body is `tooth_width_mm` there and the slot's half-angle is θ_s = (2π·r_s/Q − tooth width) / (2·r_s);
   - **straight sides** joining the mouth corners to the bottom corners.

   Put the slot's centre line on the x axis. The area and the centroid then follow from three closed-form pieces:
   - **Trapezoid** between the two chords. The chords are a = 2·r_b·sin θ_m at x₁ = r_b·cos θ_m, and b = 2·r_s·sin θ_s at x₂ = r_s·cos θ_s. With h = x₂ − x₁:
     - A_T = h·(a + b)/2;
     - x̄_T = x₁ + h·(a + 2b) / (3·(a + b)).
   - **Outer circular segment**, added, since the bottom arc bulges away from the bore:
     - A_o = r_s²·(θ_s − sin θ_s·cos θ_s);
     - x̄_o = 4·r_s·sin³θ_s / (3·(2θ_s − sin 2θ_s)).
   - **Inner circular segment**, subtracted, since the mouth arc bulges into the slot. Its A_i and x̄_i use the same formulas with r_b and θ_m.

   The slot area is A_slot = A_T + A_o − A_i. Its centroid lies on the centre line at radius r_c = (A_T·x̄_T + A_o·x̄_o − A_i·x̄_i) / A_slot.
4. **Coil-side angle.** Δφ = span · 360°/Q, with the span in slots.
5. **Mean turn length.**
   - Each end turn is a half circle across the arc s = Δφ·r_c, so its length is (π/2)·s.
   - Add 2 extensions per end, out of the slot and back in.
   - MLT = 2·L + 2·((π/2)·s + 2·e).
6. **R at 20 °C.** R20 = ρ·N·MLT / (A·a²).
7. **R at the winding temperature.** R(T) = R20 · (1 + α·(T − 20)).

## Case 1: concentrated, `spm_8p12s_concentrated__baseline`, copper at 80 °C

**From the fixture.**
- 12 slots, 8 poles.
- ID 60 mm, OD 100 mm, yoke 8 mm.
- Slot opening 2.0 mm, tooth width 9.0 mm, tooth shoes off.
- Stack 50 mm.
- Concentrated winding, 1 layer.
- 12 conductors per slot, 1 parallel path.

**Declared.**
- Wire: 2 strands in hand of 1.25 mm.
- Extension 5 mm.
- Copper at 80 °C.

**1. Series turns.**
- A single-layer tooth winding on 12 slots has a coil on every other tooth: 6 coils, 2 per phase.
- Each slot holds one coil side of 12 conductors, so each coil has 12 turns.
- N = 2 × 12 = **24 turns**.
- Check: a phase has 12/3 = 4 slots × 12 = 48 conductors, and 48/2 = 24. coilEM's 12 · 12/6 gives the same.

**2. Turn copper area.** A = 2 × π × 1.25²/4 = 2 × 1.227185 = **2.454369 mm²**.

As a side check, the copper fill is 12 × 2.454369 / 90.32 = 32.6%, inside the 45% limit, so the wire fits.

**3. The slot.**

| Quantity | Value |
| --- | --- |
| r_b, θ_m | 30 mm; 1.0/30 = 0.0333333 rad (1.90986°) |
| r_s | 50 − 8 = 42 mm |
| Pitch arc at r_s | 2π × 42/12 = 21.99115 mm |
| Slot arc at r_s | 21.99115 − 9.0 = 12.99115 mm |
| θ_s | 12.99115 / 84 = 0.154657 rad (8.86117°) |
| Mouth chord a at x₁ | 1.999630 mm at 29.98333 mm |
| Bottom chord b at x₂ | 12.93942 mm at 41.49871 mm |
| h | 11.51537 mm |
| A_T, x̄_T | 86.01438 mm², 37.14646 mm |
| A_o, x̄_o | 42² × 0.002454346 = 4.329466 mm², 41.69933 mm |
| A_i, x̄_i | 30² × 2.468587·10⁻⁵ = 0.022217 mm², 29.99000 mm |
| A_slot | 86.01438 + 4.329466 − 0.022217 = **90.32163 mm²** |
| r_c | (3195.130 + 180.5358 − 0.6663) / 90.32163 = **37.36646 mm** |

**4. Coil-side angle.**
- A tooth coil's two sides are the two slots beside its tooth.
- With a single layer, each side is a whole slot.
- Δφ = 360°/12 = **30°** = 0.523599 rad.

**5. Mean turn length.**
- s = 0.523599 × 37.36646 = 19.56503 mm.
- Half circle = π/2 × 19.56503 = **30.73268 mm**.
- End turn at each end = 30.73268 + 2 × 5 = 40.73268 mm.
- MLT = 2 × 50 + 2 × 40.73268 = **181.4654 mm**.

**6. R at 20 °C.** R20 = (1/58) × 24 × 0.1814654 / (2.454369 × 1²) = **0.03059406 Ω** (30.594 mΩ).

**7. R at 80 °C.** R80 = 0.03059406 × (1 + 0.00393 × 60) = 0.03059406 × 1.2358 = **0.03780814 Ω** (37.808 mΩ).

## Case 2: distributed, `spm_8p24s_distributed_femm_validation`, copper and aluminium at 120 °C

**From the fixture.**
- 24 slots, 8 poles.
- ID 161 mm, OD 269 mm, yoke 24 mm.
- Slot opening 2.5 mm, tooth width 12.4 mm, tooth shoes off.
- Stack 135 mm.
- Distributed winding, 2 layers, coil span unset (full pitch).
- 12 conductors per slot, 2 parallel paths.

**Declared.**
- Wire: 4 strands in hand of 1.6 mm.
- Extension 15 mm.
- 120 °C, once in copper and once in aluminium.

**1. Series turns.**
- q = 24/(8 × 3) = 1 slot per pole per phase.
- Full pitch is 24/8 = 3 slots.
- A two-layer winding has one coil per slot: 24 coils, 8 per phase.
- Each layer holds one coil side of 12/2 = 6 conductors, so each coil has 6 turns.
- N = 8 × 6 = **48 turns**, split over 2 paths of 24 turns each.
- Check: a phase has 8 slots × 12 = 96 conductors, and 96/2 = 48. coilEM's 24 · 12/6 gives the same.

**2. Turn copper area.** A = 4 × π × 1.6²/4 = 4 × 2.010619 = **8.042477 mm²**.

As a side check, the copper fill is 12 × 8.042477 / 285.74 = 33.8%, inside the 45% limit.

**3. The slot.**

| Quantity | Value |
| --- | --- |
| r_b, θ_m | 80.5 mm; 1.25/80.5 = 0.0155280 rad (0.889686°) |
| r_s | 134.5 − 24 = 110.5 mm |
| Pitch arc at r_s | 2π × 110.5/24 = 28.92883 mm |
| Slot arc at r_s | 28.92883 − 12.4 = 16.52883 mm |
| θ_s | 16.52883 / 221 = 0.0747911 rad (4.28521°) |
| Mouth chord a at x₁ | 2.499900 mm at 80.49030 mm |
| Bottom chord b at x₂ | 16.51343 mm at 110.19109 mm |
| h | 29.70080 mm |
| A_T, x̄_T | 282.3555 mm², 98.98913 mm |
| A_o, x̄_o | 110.5² × 2.785945·10⁻⁴ = 3.401709 mm², 110.31467 mm |
| A_i, x̄_i | 80.5² × 2.495917·10⁻⁶ = 0.016174 mm², 80.49418 mm |
| A_slot | 282.3555 + 3.401709 − 0.016174 = **285.7410 mm²** |
| r_c | (27950.12 + 375.2584 − 1.3019) / 285.7410 = **99.12500 mm** |

**4. Coil-side angle.**
- A coil of a two-layer winding has one side in each layer, a coil span apart.
- coilEM draws the two layers with equal area: each layer region is 142.87 mm², half the slot.
- So the mean radius of a coil's two sides is the whole slot's centroid radius r_c.
- Δφ = 3 × 360°/24 = **45°** = 0.785398 rad.

**5. Mean turn length.**
- s = 0.785398 × 99.12500 = 77.85259 mm.
- Half circle = π/2 × 77.85259 = **122.2906 mm**.
- End turn at each end = 122.2906 + 2 × 15 = 152.2906 mm.
- MLT = 2 × 135 + 2 × 152.2906 = **574.5811 mm**.

**6. R at 20 °C.** First the common factor: N·MLT / (A·a²) = 48 × 0.5745811 / (8.042477 × 2²) = 27.57989 / 32.16991 = 0.857320 m/mm².
- Copper: R20 = 0.857320 / 58 = **0.01478137 Ω** (14.781 mΩ).
- Aluminium: R20 = 0.857320 × 0.028264 = **0.02423128 Ω** (24.231 mΩ).

**7. R at 120 °C.**
- Copper: R120 = 0.01478137 × (1 + 0.00393 × 100) = 0.01478137 × 1.393 = **0.02059045 Ω** (20.590 mΩ).
- Aluminium: R120 = 0.02423128 × (1 + 0.00403 × 100) = 0.02423128 × 1.403 = **0.03399649 Ω** (33.996 mΩ).

## Gate result

These are coilEM's values on the commit that registered the gate. The test re-runs the gate on every change.

| Case | Hand R(T) | coilEM R(T) | Error | Status |
| --- | --- | --- | --- | --- |
| `spm_8p12s_concentrated__copper_80C` | 37.8081 mΩ | 37.8079 mΩ | 0.0007% | PASS |
| `spm_8p24s_distributed__copper_120C` | 20.5905 mΩ | 20.5903 mΩ | 0.0008% | PASS |
| `spm_8p24s_distributed__aluminum_120C` | 33.9965 mΩ | 33.9962 mΩ | 0.0008% | PASS |

**Where the small residual comes from.** coilEM finds the coil-side centroids on tessellated slot polygons, whose arcs are chords:
- its slot areas are 90.3096 and 285.7030 mm², against the exact 90.3216 and 285.7410 mm²;
- so its end-turn arcs come out 0.002% short.

Every other term agrees exactly: turns, strand area, paths, stack, extension, ρ and α.

**Why 1% and 3%.** The calculation is closed-form, so tessellation is the only expected difference, at about 0.002%. A 1% band leaves room for tessellation on more curved slots. It still catches every real slip:

| Slip | Error it causes |
| --- | --- |
| Paths not squared | ×2 on case 2 |
| Strands in hand dropped | ×2 on case 1, ×4 on case 2 |
| Extension counted twice per turn instead of four times | 5.5% on case 1, 5.2% on case 2 |
| End-turn arc left out | 34% on case 1, 43% on case 2 |
| Aluminium's resistivity used for copper | 64% |
| Temperature correction left out | 19% on case 1, 28% to 29% on case 2 |

## What the gate does and does not cover

**It covers** the calculation from the design's inputs to its resistance:
- the turn count and the parallel paths;
- the strands in hand;
- the end-turn geometry read off the slot, for a tooth coil and for a distributed coil;
- the straight extension;
- both conductors' data and the temperature correction.

**It does not cover:**
- **A measured winding.** `tests/test_winding_resistance.py` checks the Accord's as-built winding against its measured 0.0097 Ω at 21 °C (ORNL/TM-2006/535, Table 2.3) within 2%. That is a regression test, not a registered gate.
- **AC resistance.**
- **Real end-turn shapes.**
- **A design without a wire.** Its wire is an assumption, so its record stays experimental.
