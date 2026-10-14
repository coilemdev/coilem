# 2005 Honda Accord hybrid motor: Phase A inputs (#92)

These are the frozen inputs for comparing coilEM with ORNL's measurements of the 2005 Honda Accord hybrid (IMA) motor. This commit freezes them **before any comparison**. This is an exploratory hardware correlation with no pass/fail, like #69. Any input changed after the comparison is labelled `fitted — not a prediction`.

**Disclosure.** The target tables (S1 Tables 3.1 and 3.2) were read on 2026-10-14, while judging whether the source was usable and before any input was chosen. No input here was chosen by comparing it with those tables. Every input comes from S1's design data or one of the assumptions below.

| File | What it holds |
| --- | --- |
| [`sources.json`](sources.json) | S1 (ORNL/TM-2006/535) with its SHA-256 |
| [`input-provenance.json`](input-provenance.json) | Design data as printed (Table 2.3, Fig. 2.5, Fig. 2.4 photo estimates), and what S1 doesn't publish |
| [`request.json`](request.json) | The frozen coilEM request, written by [`tools/honda_accord_request.py`](../../../tools/honda_accord_request.py) |
| [`target-back-emf.json`](target-back-emf.json), [`target-locked-rotor.json`](target-locked-rotor.json) | S1 Tables 3.1 and 3.2 |

## The motor

- **Stator:** 24 slots, segmented, with a bobbin coil on every tooth. That's a concentrated winding with q = 1/2.
- **Winding:** 52 turns per coil, 8 coils per phase all in parallel, star.
- **Rotor:** 16 poles, interior magnets just under the surface, two flat 18.45 × 4.46 mm magnets per pole with a rib between them.
- **Size:** stator OD 315.5 mm, ID 232 mm, stack 40.1 mm, airgap 1 mm.

## Owner decisions (2026-10-14)

1. **Magnets.** The blind assumption is catalog **N35** (Br 1.23 T, μr 1.05), a typical high-coercivity traction grade of the period. A second variant, Br fitted to Table 3.1 back-EMF, runs through the scratch-only Br-scale override used for the Prius, and is labelled `fitted — not a prediction`. In that variant, locked-rotor torque is the independent target.
2. **Rotor.** One flat magnet per pole, using the public `flat_buried` topology (see A2).
3. **The fitted variant keeps the scratch override.** It doesn't wait for a custom-magnet feature.

## Assumptions and residuals

- **A1, magnet grade:** N35. S1 gives no grade or Br.
- **A2, rotor representation:** each pole's two 18.45 mm magnets and the rib between them become one 36.9 mm straight bar. The magnet area is exactly the published total. Residuals:
  - the rib (~1.5 mm, photo) and its leakage are missing;
  - the bar's centre sits about 1.1 mm deeper than two separately tangent magnets would;
  - the dark gaps at the pole boundaries in Fig. 2.4d, probably end barriers, aren't drawn. The pocket clearance stays at the 0.25 mm default.
- **A3, bridge:** 1.0 mm from the pocket corner to the surface, estimated from the Fig. 2.4d photo, which is low resolution.
- **A4, steel:** M350-50A, the bundled public steel and the one the Prius fixture uses. S1 gives only the lamination thickness, 0.343 mm.
- **A5, locked-rotor currents:** (Ia, −Ia/2, −Ia/2), as in ORNL's Prius reports. S1 doesn't restate the pattern.
- **A6, stack:** 40.1 mm, the stator stack. The rotor is 41.2 mm and the magnets 40.4 mm. coilEM is 2D, so there are no end effects.

## Stator mapping

Measurements come from Fig. 2.5, scaled so that 30.6 mm equals the slot depth:
- the tooth subtends 8.884° at the top of the 20° wedge (r = 118.03 mm, slot 12.61 mm wide);
- it subtends 7.505° at the slot-bottom corners (r = 145.73 mm, slot 19.05 mm wide).

coilEM draws a linear angular taper from bore to yoke, so that line is extrapolated to:
- 18.19 mm at the bore, which makes `slot_opening_mm` = 12.178;
- 19.09 mm at the yoke (`tooth_width_mm`);
- yoke thickness (315.5 − 232)/2 − 30.6 = 11.15 mm.

The shoe leaves the published 4.75 mm mouth: overhang 3.714 mm. Its height is 1.423 mm, the same steel area as the real 0.66 mm tip plus the 20° wedge.

coilEM's slot comes out at 470 mm². Integrating Fig. 2.5 gives about 445–460 mm². Table 2.3's "slot area 307 mm²" matches neither, and is probably the bobbin's winding window. The geometry follows the drawing.

## Winding: how #91 is emulated

coilEM's concentrated map for 24s16p puts one phase in each slot (A′, B′, C′ repeating, all one direction). That isn't a tooth coil (#91). Until #91 is fixed, the real winding is reached with two exact linear transforms, the ones validated on CREATOR (#90):
- **currents in:** i′A = (iA − iC)/2;
- **flux linkage out:** λA = (λ′A − λ′B)/2.

For the locked-rotor pattern (Ia, −Ia/2, −Ia/2), that gives coilEM currents (0.75, −0.75, 0)·Ia: amplitude (√3/2)·Ia at a 60° source angle.

coilEM allows at most 6 parallel paths, so the request uses the exact field equivalent with **one path and 13 conductors per slot**:
- the real slot ampere-turns, 52·(iA − iC)/8, equal 13·i′A;
- the re-paired linkage, 8·13·L·ΔĀ/2 = 52·L·ΔĀ, is one real coil's linkage, which is the phase linkage for 8 identical coils in parallel.

The transforms keep power exactly. Torque comes straight from the field. These runs are labelled *#91 emulated*, and the case is re-run on the real fix when it lands.

## Phase B plan

- **No-load back-EMF:** one sweep of 360° electrical in 2° steps at 1000 rpm, re-paired, compared line-to-neutral with Table 3.1 by scaling with speed.
- **Locked rotor:** static solves at ORNL's DC pattern over rotor position for each current in Table 3.2, taking the peak over position. Split into magnet and reluctance parts as for the Prius.
- **Fitted variant:** Br fitted to the back-EMF; the locked-rotor torque is then re-run as the independent check.
