# SPM 6p/36s

Open **Design file menu → Examples → SPM 6p/36s** and run the saved
Custom analysis settings. This teaching motor has six surface-magnet poles,
36 stator teeth, and a balanced three-phase,
two-layer, full-pitch distributed winding. Each pole spans six slots; there
are two slots per pole per phase.

## What to follow

1. In **Solve → Field solution**, expand the view and select **Stator only**.
   Let the separate stator-current field solve finish.
2. Show **Field lines**, hide **Flux density** and **PM reference**, and use
   Medium line density. Follow one of the six field lobes near the airgap and
   its return path through the stator yoke.
3. Play at **3 RPM**. The three north–south pairs move together around the
   airgap, clockwise in the public view.
4. Select **PM only** and show **Magnets** and **Pole labels** to connect the
   repeated field pattern to the six alternating rotor poles.
5. Select **Resultant** to inspect the field with magnets and current active.
   Show the heatmap when exploring how individual teeth carry flux.

The mechanical and electrical angles differ: with three pole pairs,
**360° electrical = 120° mechanical**. The saved 72-position sweep covers
one electrical cycle at 5° electrical steps, or about 1.67° mechanical per
frame. Three electrical cycles correspond to one mechanical revolution.
Identical pole pairs make the field pattern repeat at the electrical-cycle
boundary; this does not mean the rotor made a complete mechanical turn.

## Geometry and operating point

- Stator: 250 mm OD, 166 mm bore, 36 slots, 50 mm stack, 24 mm return yoke,
  2 mm slot openings.
- Rotor: 157 mm steel OD, 35 mm shaft hole, six 3 mm thick surface magnets.
- Physical airgap: 1.5 mm, the top of the app's practical range (0.5–1.5 mm).
  Each magnet covers 87% of its pole pitch.
- Winding: 20 turns per coil, two coil sides per slot, one parallel path,
  full pitch.
- Excitation: sinusoidal, 20 A peak phase current, 300 RPM operating speed.
  The separate 3 RPM playback setting slows the display for learning.
- Materials: nonlinear M350-50A steel and N42 magnets.

The design file is
[`rotating_field_6p36s.coilem`](../frontend/src/public/examples/rotating_field_6p36s.coilem).

## Visual selection

The native field study compared 4p/24s and 6p/36s distributed-winding motors.
The six-pole design retained six distinct flux lobes with a dense tooth
layout. The study's drafts used a 4–5 mm airgap to make the rotor/stator
separation easier to see; the bundled design uses a realistic 1.5 mm. The final pass refines the mesh and reduces the
angular step from 30° to 5°, retaining the PM-only no-load field as well.

## Smooth torque

The geometry is tuned for a steady torque curve. At the bundled operating point
the first draft (80% magnet arc, 3 mm slot openings, 18 mm yoke) rippled 21%
peak to peak. Three changes bring it to 6.6% on the bundled 5° grid, and 7.5%
when the same design is re-solved at 2.5°, at 29.4 N·m mean torque:

- **An 87% magnet arc** places the magnet edges where their slotting
  (cogging) forces largely cancel for six slots per pole.
- **2 mm slot openings**, the narrowest the app accepts, weaken the slot
  modulation of the airgap field.
- **A 24 mm yoke** keeps the return path out of the steel's saturation knee
  (peak yoke B about 1.37 T, down from about 1.6 T). Saturation added its own
  ripple, which is why thicker magnets made the ripple worse, not better.

Most of the remaining ripple is sixth-order torque from the back EMF's 5th and
7th harmonics. A 5/6 short-pitch winding would cut it further (about 4% on the
5° grid in a direct solve), but the app does not yet keep a coil span when it
loads a design file, so the bundled design stays full pitch.

All three sources are separate nonlinear Magneto2D solutions. Their arithmetic
sum is not assumed to equal the combined field. This is a numerical teaching
design, not a hardware-validated motor or a torque-ripple qualification.
