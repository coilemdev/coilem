# Material Models and Provenance

coilEM's launch solver uses a deliberately limited material model. These values
are engineering inputs for simulation; they are not certificates, purchase
specifications, or guarantees for material supplied by any manufacturer.

## Permanent magnets

Except for the N35 validation preset described below, the NdFeB remanence values are the typical room-temperature values in the
Arnold Magnetic Technologies grade table, converted from millitesla to tesla.
Arnold notes that properties vary with alignment, geometry, and grade-specific
conditions.

Source: [Arnold Magnetic Technologies — Neodymium Iron Boron Magnets](https://www.arnoldmagnetics.com/products/neodymium-iron-boron-magnets/)

| Public motor grade | Br (T) | Relative permeability |
| --- | ---: | ---: |
| N35 | 1.230 | 1.05 |
| N42 | 1.315 | 1.05 |
| N48 | 1.400 | 1.05 |
| N48SH | 1.390 | 1.05 |
| N52 | 1.450 | 1.05 |

N35 retains the source catalog's Br = 1.230 T and relative permeability = 1.05
used by the validated BLDC/FEMM comparison. This is a coilEM modeling preset,
not Arnold's typical N35 value (1.210 T). Exporting the application must not
silently replace that validated material. The shared N35 numerical contract
is included in the public package and checked by its Python and Rust tests.

The relative-permeability value is a coilEM straight-line approximation for
fully dense anisotropic permanent magnets. Arnold's educational material gives
approximately 1.05 for ferrite, SmCo, and NdFeB recoil permeability:
[The Elements of Magnetics](https://www.arnoldmagnetics.com/wp-content/uploads/2017/10/Elements-of-Magnetics-Constantinides-CWRU-2013-psn-lo-res.pdf).

`Ferrite_Y30` uses a coilEM nominal assumption of Br = 0.400 T and relative
permeability = 1.05. `Prius_2004_NdFeB` uses a benchmark assumption of Br =
1.240 T and relative permeability = 1.05. Those two names are modeling presets,
not claims that a particular vendor or vehicle contains material with exactly
those properties.

`ORNL_Prius_2004_NdFeB` follows the 2004 Prius magnet's demagnetization line in
[ORNL/TM-2004/137](https://www.osti.gov/servlets/purl/885676) Fig. 14: Br =
1.235 T (the figure gives 12.3–12.4 kG) and relative permeability 1.12, from
Br / (μ0 Hc) with a normal coercivity of 11.0 kOe. The values are read from a
figure, extrapolated from points measured at H ≈ −7.2 to −4.7 kOe; ORNL states
no test temperature and says only that the magnets appear sintered. The grade
exists for the ORNL Prius benchmark case.

### Magnet temperature

A motor solve can set a magnet temperature (Solve → Operating point → Magnet
temp). Br is scaled linearly from 20 °C by the grade's reversible temperature
coefficient, which lowers the magnet flux, back EMF and torque. Intrinsic
coercivity HcJ is derated and recorded with the run for a later
demagnetisation check; the solve's straight recoil line does not use it.
At 20 °C, or with no temperature set, nothing changes.

The coefficients are the reversible temperature coefficients in the same
Arnold grade table as the room-temperature Br values, read 2026-10-21:
[Arnold Magnetic Technologies — Neodymium Iron Boron Magnets](https://www.arnoldmagnetics.com/products/neodymium-iron-boron-magnets/).

| Grade | Br %/°C | HcJ %/°C | HcJ min at 20 °C (kA/m) | Max operating temperature | Accepted range |
| --- | --- | --- | --- | --- | --- |
| N35 | −0.12 | −0.618 | 955 | 80 °C | −40 to 141 °C |
| N42 | −0.12 | −0.75 | 955 | 80 °C | −40 to 120 °C |
| N48 | −0.12 | −0.75 | 955 | 80 °C | −40 to 120 °C |
| N52 | −0.12 | −0.75 | 876 | 60 °C | −40 to 120 °C |
| N48SH | −0.12 | −0.535 | 1512 | 150 °C | −40 to 160 °C |

The accepted range ends where the linear model would take HcJ below a quarter
of its 20 °C value; past that the coefficients no longer describe the magnet.
Above a grade's maximum operating temperature the run carries a warning: the
magnet risks irreversible demagnetisation, which coilEM does not model.
Ferrite_Y30, Prius_2004_NdFeB and ORNL_Prius_2004_NdFeB have no cited
coefficients, so a magnet temperature is refused for them. The pinned Prius
reference keeps its published 20 and 60 °C cases and their own Br factor.

### Halbach coercivity and temperature policy

Cylindrical and linear Halbach workspaces resolve magnets from the legacy
`backend/material_catalog.py` table. The optional Elmer case builder also uses
that table. These inputs differ from the public Magneto2D motor catalog above:

| Grade | Public motor Br (T) / relative permeability | Legacy Br (T) / relative permeability |
| --- | --- | --- |
| N42 | 1.315 / 1.05 | 1.300 / 1.05 |
| N52 | 1.450 / 1.05 | 1.470 / 1.05 |
| N48SH | 1.390 / 1.05 | 1.380 / 1.05 |
| Ferrite_Y30 | 0.400 / 1.05 | 0.390 / 1.10 |

N35, N48, Prius_2004_NdFeB and ORNL_Prius_2004_NdFeB have matching Br and
relative permeability in both tables. Halbach Br(T) and Hcj(T) temperature coefficients are independent
records with explicit reference temperatures and provenance. Compare the
resolved material inputs, not only grade names, when comparing workflows.

The legacy magnet catalog's coercivity field does not unambiguously identify
normal versus intrinsic coercivity. Every current selectable catalog row is
therefore audited as `unknown`: the value remains visible as metadata but is
ineligible for a demagnetization margin. Only a custom material's explicit
positive `intrinsic_coercivity_a_per_m` may drive that screening margin.
Reverse-field results are a mesh-sensitive screening diagnostic, not a
demagnetization certificate.

## Electrical steel

coilEM distributes one nonlinear reference model: `M350-50A`. The checked-in
table is generated by `tools/generate_m350_50a_bh.py` from the parameters and
approximation function in the Modelica Standard Library. The source model is
BSD-3-Clause licensed; its notice is reproduced in `THIRD_PARTY_NOTICES.md`.

Source model: [Modelica Standard Library `M350_50A`](https://github.com/modelica/ModelicaStandardLibrary/blob/master/Modelica/Magnetic/FluxTubes/Material/SoftMagnetic/ElectricSheet/M350_50A.mo)

Source approximation: [Modelica Standard Library `mu_rApprox`](https://github.com/modelica/ModelicaStandardLibrary/blob/master/Modelica/Magnetic/FluxTubes/Material/SoftMagnetic/mu_rApprox.mo)

The source record identifies the material as M350-50A (1.0810) at 50 Hz, with a
sheet-strip sample measured in an Epstein frame. Its fit parameters are
`mu_i = 1210`, `B_myMax = 1.16 T`, `c_a = 24630`, `c_b = 2.44`, and `n = 14`.
For normalized flux density `B_N = |B / B_myMax|`, the generated curve uses:

```text
mu_r(B) = 1 + (mu_i - 1 + c_a B_N) / (1 + c_b B_N + B_N^n)
H(B)    = B / (mu_0 mu_r(B))
```

The generated table lives at
`materials/electrical-steel/M350-50A.csv`. It spans 0 to 2.5 T, so Magneto2D
uses the nonlinear saturation knee instead of silently substituting a constant
relative permeability. Run `python tools/generate_m350_50a_bh.py --check` to
verify that the committed table exactly matches the reviewed model.

This is an open reference model, not a manufacturer certificate or a claim
that M350-50A is interchangeable with M19. Production work should replace it
with measured supplier data for the actual lamination grade, thickness,
processing, and operating conditions.

The following source datasets remain deliberately excluded:

- The M19 curve previously used during private development was derived from a
  third-party solver library and is not distributed.
- The M27, M36, NO20, NO27, and 1018 steel curves used during private
  development lacked sufficient item-level provenance and are not distributed.

## Import your own steel

In Design → Materials, choose **Import steel material**. Select a UTF-8 CSV,
enter its name and source/measurement conditions, and optionally record the
lamination thickness. Choose **Validate curve**, review the B-H plot, and assign
the material to the stator, rotor, or both. Save the `.coilem` project to preserve
its exact curve and assignments; no shared material database is modified.

The CSV header must be `B_T,H_A_per_m` or `H_A_per_m,B_T`. Values use tesla and
amperes per metre. Blank lines and lines starting with `#` are ignored. The
import requires 3–4096 finite numeric points, beginning at `(0,0)`, with strictly
increasing B and H. B must be within 0–5 T, H within 0–10,000,000 A/m, and secant
relative permeability within 1–1,000,000. Files are limited to 512 KiB. These are
format and solver-consistency checks, not verification of the measured data.

Each material has a content-derived identity and a curve checksum. Two records
with the same display name but different data have different identities. Edits
to a saved material must be reimported so they cannot silently change an existing
identity. Saved solve records and exports retain that identity and source.

Use **Download sample curve** in the importer, or
[`sample-custom-steel.csv`](frontend/public/materials/sample-custom-steel.csv),
to try the feature. It is a synthetic demonstration curve, not a measured grade
or a substitute for supplier data.

Custom steel currently uses Magneto2D's static isotropic nonlinear B-H model.
Above the final B value, the solver extrapolates the last segment. Lamination
thickness is recorded as metadata; it does not add a lamination-loss model.
Core-loss, hysteresis, temperature dependence and measurement certification are
not provided by this import. Optional Elmer execution rejects custom steels.

## Core loss

Stator iron loss is an experimental estimate for M350-50A, and for M400-50A in
the pinned Pyleecan Prius, whose imported B-H curve is that grade. Per kilogram,
each electrical harmonic h of an element's flux density contributes

```text
p_h = kh · f_h · B_h^alpha + kc · f_h^2 · B_h^2
```

The coefficients come from published facts, not from a fitted loss table:

- `kc` is the classical lamination eddy-current term, pi^2 · d^2 / (6 · rho_el · rho_m),
  with d = 0.50 mm, rho_m = 7650 kg/m^3 (the density coilEM uses for M350-50A)
  and rho_el = 42.2e-8 Ohm·m, the typical value in SIJ Acroni's SIWATT M350-50A
  technical data sheet (SIWATT M350-50A-1/1-2023-EN).
- `kh` and `alpha` meet the EN 10106 maximum specific losses for M350-50A at
  50 Hz, 1.50 W/kg at 1.0 T and 3.50 W/kg at 1.5 T, exactly. Real sheet is
  usually below these limits, so the estimate reads high at 50 Hz.

The Pyleecan Prius's M400-50A is built the same way:

- `kh` and `alpha` meet 1.70 W/kg at 1.0 T and 4.00 W/kg at 1.5 T, 50 Hz, the
  DIN EN 10106 values in Waelzholz's grade table, which also gives the
  7700 kg/m^3 density. The standard does not make the 1.0 T value obligatory.
- `kc` uses d = 0.50 mm and rho_el = 33.4e-8 Ohm·m, the typical value in SIJ
  Acroni's SIWATT M400-50A HP technical data sheet (SIWATT M400-50A HP-1/7-2024-EN).

Excess loss is not modelled separately. Against the M400-50A loss table in
Pyleecan's material library (`M400-50A.json` at Pyleecan `cbfe7be3`, whose
50 Hz values match a Tata Steel typical-data sheet), the M400-50A model stays
within a mean of ±8 % at each frequency from 50 Hz to 1 kHz above 0.5 T, with a
worst point near 22 %, and reads about 24 % high at 2.5 kHz. coilEM does not
ship that table.

The estimate needs a nonzero speed and a loaded sweep over one full electrical
cycle, or half of one, in equal steps. Half-wave symmetry, B(θ + 180°) = −B(θ),
completes a half cycle. It follows each stator element's flux-density waveform
over the cycle, and results report the share of the loss that comes from harmonics
above 1 kHz or flux densities above 1.5 T, outside the range the two grade
limits cover. Rotor, magnet and stray losses are not included, and cutting and
pressing usually raise a real core's loss above sheet data. Other steels show
iron loss as unavailable until cited loss data exist for them. The native
solver's own core-loss fields stay zero; coilEM computes the estimate from the
stored field frames.

## Winding conductors

Phase resistance uses IEC 60028 annealed copper (1/58 Ohm·mm^2/m and
0.00393 /K at 20 °C) or IEC 60889 hard-drawn aluminium (0.028264 Ohm·mm^2/m and
0.00403 /K). The mean turn length is two stack lengths plus two end turns,
each a half circle across the arc between the coil's two sides, and copper
fill is bare copper over the gross slot polygon. With the 2005 Honda Accord's
published winding (1.55 mm wire, 52 turns per coil, 8 parallel circuits) the
model gives 9.80 mOhm at 21 °C against 9.7 mOhm measured (ORNL/TM-2006/535,
Table 2.3).


## Steady-state lumped thermal estimates (0.6.0 M1)

`backend/thermal_network.py` is a backend building block, not a public thermal
rating or a change to electromagnetic physics. No thermal output is qualified.
The core nodes are active winding, both end windings together, stator teeth,
stator yoke, housing and a fixed ambient/coolant boundary. Rotor, magnets,
air gap, end-space air and bearings are experimental auxiliary nodes. These
are node-average temperatures, not hotspots. The network solves the steady
balance `sum_j (T_i - T_j)/R_ij = Q_i`; all nodes must connect to a boundary,
and rejected heat must equal total assigned heat within numerical tolerance.
The hand-calculation tests verify this balance, not the physical motor model.

### Geometry and heat paths: stated assumptions

The network has two layouts. For an inner rotor the stator yoke faces a housing,
as the list below describes. For an outer rotor the stator sits on a hub inside
the rotor shell, and the same inputs are read as follows. Each is a stated
assumption, not a correlation.

- **Yoke to hub.** The entered contact resistance acts over the hub-side face of
  the yoke, `2*pi*r_hub*L`. The yoke slab uses that same face, the smaller one,
  so its resistance is not understated.
- **Hub to surroundings.** One entered resistance, `mount_to_ambient_K_W`, covers
  the hub, the mount and whatever the motor is bolted to. It is required.
- **Rotor shell to surroundings.** The entered outside coefficient acts over the
  shell's outer cylinder, taken over the stack length, plus one closed end:
  `2*pi*r_o*L + pi*r_o^2`, in series with conduction through the shell at the
  steel conductivity. No speed or propeller-wash correlation is applied. A shell
  longer than the stack would shed more.
- **Air inside the rotor.** One mixed node. It exchanges heat with the end
  windings, with the closed end of the shell (`pi*r_i^2`) and with the stator
  carrier face on the mount side (the stator's end annulus), all at the entered
  end-space coefficient. No air exchange through openings in the shell is
  assumed, so an open rotor runs cooler than the estimate.
- **Air gap and magnets.** The gap couples the tooth tips to the magnet faces at
  the entered per-surface coefficient. Magnets pass their heat to the shell.
- **Bearings.** They connect the rotor to the mount through the two entered
  resistances. The housing thickness is unused. A mechanical-loss share assigned
  to the housing heats the mount.

Two hand checks bound the outer layout (`tests/test_thermal_network.py`): with
the mount path blocked, every watt leaves by the shell's stated area and
coefficient; with the shell blocked, every watt crosses the mount resistance.
The inner layout's numbers are unchanged.

Lengths are in metres, areas in square metres, conductivity in W/(m K), and
thermal resistance in K/W. IR region areas supply total winding, tooth, yoke
and magnet cross-sections. For a reference with one stator region, the nominal
yoke annulus partitions its steel into tooth/yoke areas; this is an assumed
partition, not reconstructed reference teeth. The following reductions are
engineering assumptions, exposed through the recorded network's links:

- Slot depth is `(OD-ID)/2 - yoke thickness`; slot width is gross slot area
  divided by depth. Winding-to-tooth conduction uses a uniform-generation mean reduction across a rectangular
  slot width through homogenized winding, then one liner. Aggregate wall area
  is two slot-depth walls times slot count times stack length. The slot's
  transverse conductivity is the series mixture
  `1/k = fill/k_conductor + (1-fill)/k_impregnation`. This is explicitly the
  series lower bound, not an empirical prediction of an impregnated winding.
  Select the user model and supply a conductivity and source to replace it. Round strands, enamel,
  voids and individual slot contacts are not spatially resolved. Liner
  thickness must leave positive winding width.
- Tooth and yoke paths use planar slab means and distinct bore/interface/outer
  surfaces, as described below. Contact and cylindrical housing conduction join
  the outer stator surface to a housing outer-surface proxy.
- Active-to-end-winding conduction includes both aggregate mean-to-junction drops:
  `R=(L_active+L_end_arc)/(12*k_conductor*total_slot_copper_area)`.
  This assumes a symmetric coil and distributed side heat exchange in each part.
- End-winding gross square area is total slot area divided by twice the actual
  coil count. The same fill/transverse conductivity as the active slots is an
  explicit assumption. Conduction and convection are solved together with the
  uniform-net-source square Robin solution. Exposure uniformly reduces h; it
  does not shrink the bundle or resolve localized shielding. End-space-to-housing
  convection retains two annular faces and an entered coefficient.
- Gap coefficients are **per surface**: total resistance is
  `1/(h_gap*2*pi*r_bore*L) + 1/(h_gap*2*pi*r_rotor*L)` across the air-gap node. The coefficient is entered for the operating point;
  **no rotating-gap correlation or speed scaling is silently selected**.
- Magnet-to-rotor conduction uses the uniformly heated, one-cooled-face mean
  resistance `thickness/(3*k*face_area)`, with an insulated outer face. Adhesive, barriers and pocket contacts are not
  resolved. Shaft/bearing-to-housing resistances are explicit inputs.
- Exterior convection uses the cylindrical housing and two annular end faces.
  Radiation is not modelled separately; any effective coefficient that
  includes radiation must say so in its source description.

### Inputs and unresolved owner decisions

The Solve thermal setup offers an illustrative still-air starter (v1), with
ambient 25 C, class F insulation, housing/end-space/gap coefficients 10/10/20
W/(m2 K), housing/liner thickness 3/0.1 mm, stator contact resistance 0.001
m2 K/W, bearing-to-housing/rotor-to-bearing resistance 2/3 K/W and hotspot
allowance 15 K. These are explicit example assumptions for exploring the UI,
not sourced motor properties, measured cooling, or guaranteed conservative
bounds. Review them for the actual motor. The source label and actual values
are recorded with each result and in reports. The owner requested this starter
to make the thermal setup accessible; it does not change model qualification.

Existing browser drafts are preserved. New designs begin with the starter;
the starter button replaces a draft explicitly. Changing cooling mode clears
the three coefficients and their source: forced air and liquid jacket require
installation-specific inputs. Mechanical heat allocation, aluminium conductor
conductivity remain explicit inputs. Rotor/magnet additional heat is an optional
scenario input; a user-declared frequency no longer establishes availability.
Settings are shared between Solve and Results for the same design in the same
browser; they are separate from the electromagnetic design file and solver.
Thermal calculations still run explicitly from Results after an EM solve.

The input help quotes textbook ranges for the surface coefficients: 2 to 25
W/(m2 K) for free convection in gases, 25 to 250 for forced convection in
gases and 100 to 20,000 for forced convection in liquids (Incropera, DeWitt,
Bergman and Lavine, *Fundamentals of Heat and Mass Transfer*, 6th ed., Wiley,
2007, Table 1.1). They bound a first guess for a surface in air or coolant.
They are not specific to motors, and no range is quoted for the air gap, the
mount or the contact, which depend on the build.

Editable initial conductivity **assumptions**, not sourced grade properties,
are steel 20, conductor 385, housing 205, magnet 8, impregnation 0.2 and liner
0.2 W/(m K). The conductor default assumes copper; an aluminium design must
name its conductor conductivity, and the app, `coilem thermal` and the Python
client fill in 235 W/(m K) for one where none is given. These values are not fitted
or bench-qualified and the complete inputs travel with the result.

Insulation classes A/B/F/H use 105/130/155/180 C (IEC 60085 thermal-class
labels), reduced by the recorded, editable hotspot allowance before
comparison with winding node averages. A class label alone does not establish
a motor insulation system's allowable operating temperature. Magnet limits
come from the existing cited grade table where available.

### Temperature units in the app

The estimate works in degrees Celsius. In the app every thermal temperature is
shown in one unit, Celsius by default, and a margin to a limit or an allowance
uses that same unit rather than kelvin. The Thermal setup can switch the unit
to Fahrenheit or kelvin; the choice is kept in the browser, applies to what is
typed as well as what is shown, and does not change any stored value. Reports,
the command line, the Python client and messages from the solver stay in
degrees Celsius.

### Independent conduction check

The slot, tooth and yoke paths are compared with a resolved finite-element
solution of the same isolated cross-section, for inner and outer rotors (the
results are kept in the private repository). The reference is
`backend/benchmark_suite/thermal_fe.py`: linear triangles on the design's own
mesh, checked against the closed-form heated ring, sharing only the geometry
with the network. It shows where the network's reduction departs from a
resolved solution: the network's teeth read low, and its winding reads high on
a wide-slot inner stator, because the network takes winding heat out through
the slot walls only and not through the slot bottom. This is a code-to-code
check of conduction. It does not cover convection, contacts, end windings or
the rotor.

### FEMM comparison

FEMM 5.0 heat flow was run on the same designs (the results are kept in the
private repository). For the stator on its own, FEMM is set beside the
finite-element reference above, so that differences there can be attributed to
the network, and the six registered cases are graded against their bands. For
the whole cross-section with air cooling (air gap, magnets, rotor and the
cooled surfaces included, the network's end-winding, end-space, bearing and
liner paths closed) every part is compared, for inner and outer rotors, and so
is the split of heat between an outer rotor's mount and shell. Both codes are
given the same cooling coefficients, so this checks conduction and how the heat
divides, not the coefficients. FEMM solves a flat cross-section: end windings
and the air around them are not covered. The network's rotor temperature
assumes the whole rotor surface exchanges heat with the gap; with still air
between the magnets FEMM's inner rotors run hotter.

### Benchmark Phase H

[Phase H](benchmarks/h-v1.0/README.md) turns the comparisons above into a
standing benchmark: 42 thermal problems with every input fixed, coilEM's
answer to each, and a format for another tool's answer. Each design is run
with still air, with strong air cooling and with a liquid jacket or a cooled
mount, because conduction inside the motor only shows once the outside surface
is cooled well. The 21 cases a flat cross-section can represent are graded
against FEMM 5.0; those grades are kept in the private repository. The 21
full-scope cases, with end windings, wait for a reference from a
three-dimensional or lumped tool.

### Published measurement check

The network is compared with a published test of the 2004 Prius traction
motor (ORNL/TM-2005/33), which gives the losses, the casing temperature and
the measured end-turn temperature at four coolant temperatures
(`python -m tools.check_thermal_published`; the results are kept in the private
repository). Given the report's losses, conductivities and casing temperatures,
the network's end-turn temperature is set beside the measured end-turn average
and the report's own three-dimensional model. The network has no oil cooling,
so it reads warm. The stator-to-housing contact resistance is not in the report
as a number and is set once from the report's model. The result depends
strongly on that contact and on the steel conductivity: the default steel value
of 20 W/(m K), instead of the report's 51.9, makes the network read much warmer
on this motor. This checks conduction to a housing of known temperature. It
does not cover cooling by air, the outer-rotor layout,
the rotor or coilEM's own losses. No published temperatures were found for an
outer-rotor motor already modelled.

### Heat accounting, calibration and claim boundaries

Copper active and end-turn losses heat their respective nodes. Iron heats
teeth and yoke using the recorded split, or an area-weighted split assuming
uniform density when only a total exists. An unavailable iron loss makes the
estimate unavailable. Mechanical heat requires an explicit split summing to
one between bearings, housing and rotor; no default split is chosen pending
the owner's decision. Extra rotor heat is an optional sensitivity input, and
the result also records the solution without that extra input. An explicit
magnet fraction can put this sensitivity heat in magnets rather than rotor
steel. Area-weighted iron loss assumes uniform density; actual tooth loss
density is commonly higher, so this split is an approximation.

Magnet/rotor eddy-current heat, AC copper and inverter heat are not calculated.
All connected nodes now show experimental heat-transfer temperatures when an
equilibrium exists. With no heat assigned to rotor/magnets, their values describe
warming through other components. Additional heat and mechanical heat assigned
to the rotor are recorded separately in `rotor_heating`; nonzero supplied heat
changes the label to heat transfer plus supplied heat. Zero input omits a source;
it does not establish zero physical loss. Bearing friction is only included via
explicit mechanical heat allocation. Missing losses can affect every node and
reduce the predicted margins/rating. These are scenario results, not safe limits.
The legacy `magnet_frequency_limit_Hz` input remains readable but is ignored in
new calculations. There is no validated universal frequency cutoff, and no
speed-dependent thermal qualification follows from entering a gap coefficient.
Historical records retain their original values and availability until recomputed.

One per-design multiplier scales all thermal resistances. Changing it requires
measurement, operating-point and cooling provenance; calibration never promotes
an output to qualified. One multiplier cannot identify several uncertain
paths. Independent bench validation (#24) is separate from calibration and
from the pending FEMM conduction comparison (#20). The public results and
report surfaces are delivered separately in M4 (#23).

### Generated-heat mean correction (PR 28 review)

The isolated uniformly heated slab gives mean rise g*L^2/(12*k) with two
cooled faces and g*L^2/(3*k) with one cooled face and the other insulated.
Thus the mean source-to-boundary resistances are L/(12*k*A) and L/(3*k*A),
respectively. The winding transverse reduction is w/(6*k*A_wall), with both
walls included in A_wall. Liner/contact/housing/convection resistances receive
no generation correction. Tests independently verify the slab Poisson
solution, the unheated cylinder log formula, the end-turn surface, and both
gap surfaces.

These are **reduced, uniform-generation mean-resistance assumptions** inspired
by the T-equivalent treatment of distributed heat (Mellor, Roberts and Turner,
1991, DOI 10.1049/ip-b.1991.0025). They are not the full three-terminal
T-equivalent for arbitrary imposed gradients or multidimensional heat flow.
The original tooth/yoke one-face chain has been replaced as described below;
the square-bundle mean path and other reduced paths remain experimental until
the conduction comparison and bench evidence exist. Do not use a fitted multiplier
to conceal geometry-model discrepancies. Rotor/magnet losses remain a model gap;
a declared frequency cannot resolve it.

The separate [analytical protocol](benchmarks/thermal-v0.6/ANALYTICAL_PROTOCOL.md)
now tests these source-mean primitives and explicit idealized extensions against
independent 1D solutions. Its initial result exposed the layered-chain reduction
and an unequal-face slab diagnostic whose boundary-flux split was wrong despite
a correct mean temperature and total balance. These diagnostics apply to the
simplified fixtures, not the real motor or the complete geometry-derived network.
That original failed evidence is preserved in the private repository. The
subsequent `surface_mean_v2` correction is checked against the same registered
cases with unchanged inputs, independent references and tolerances. Production
tooth/yoke paths now use complete planar
three-terminal slab elements, with distinct mean, bore, shared interface and
outer-surface temperatures. Bore convection and outer contact attach to the
surfaces. Internal surface ports are not reported as component averages.
Winding-side heat is still distributed at the tooth mean, and aggregate planar
geometry, axial/end paths, cooling and homogenization remain assumptions.
See the [derivation and scope](benchmarks/thermal-v0.6/ANALYTICAL_REDUCTION_FIX.md).
Cooling inputs and all frozen acceptance bands remain unchanged. Physical
temperature qualification still requires independent evidence.

The hottest-node headline compares winding, end winding, teeth, yoke, housing,
rotor and magnets only. Air-gap, end-space air and the reduced bearing-path node
remain in the detailed node table. Removing the former frequency reporting gate
does not alter any heat source, resistance or energy balance. Unavailable source
data, invalid inputs and unstable copper equilibria still withhold temperatures.

### Copper-temperature feedback for a thermal point

“Compute thermal point” holds phase RMS current, speed, supplied stator iron
loss, mechanical/extra rotor heat and all thermal paths fixed. Active and end
winding heat use their own node-average temperatures:
`Q_active(T) = Q_active,20 * (1 + alpha * (T_active - 20))`, with the same
relation independently for the end winding. `Q20 = 3 * I_rms^2 * R_phase,20`
is split by the winding record's active length fraction. The coefficient is
that of the configured conductor (copper or aluminium). This always starts
from the 20 C resistance, so a warm source EM run cannot apply the correction
twice. Zero current still permits iron/mechanical heating but adds no copper heat.

The present network and resistance law are linear. Let `G` be the conductance
matrix for unfixed nodes and `D = diag(alpha * Q20)` at the two copper nodes.
The equilibrium is solved directly as `(G-D)*T = b - 20*D*1`, rather than
stopping an iteration at an arbitrary count. A stable equilibrium requires
`rho(sqrt(D)*inverse(G)*sqrt(D)) < 1`. This is equivalent to `G-D` being
positive definite for this passive network; any positive thermal capacitances
give decaying temperature perturbations. Critical/unstable feedback, singular
or nonphysical solutions return unavailable with no partial temperatures.
The singular boundary has a 1e-12 numerical guard; this is not a qualification
band. A second fixed-heat solve checks temperature consistency within 1e-6 K
and the existing heat-balance check still applies. Stable roots outside the
existing winding-resistance record domain (-50 to 250 C) are unavailable;
mathematical equilibrium does not extend the conductor model's usable range.

The result freezes the method version, conductor coefficient, reference and
resolved copper losses, effective phase resistance, loop gain, residual and
wire source. These resolved losses are separate from the original EM run's
loss/efficiency summary, which is retained as source provenance. There is no
new EM solve, magnet-temperature correction, voltage-feasibility check or
radiation model. Any zero-extra-rotor-heat sensitivity independently recomputes
the feedback. Temperature and loss outputs remain experimental. Existing saved
fixed-loss records retain their original numbers and are labelled for recompute.
The separate coupled rating keeps its existing map/temperature iteration;
its native evidence and frozen comparison bands are unchanged by this fix.

### Thermal result diagram

The thermal cross-section uses the current solved electromagnetic mesh,
retaining its actual slots, teeth, magnets, rotor cavities and shaft hole. It
maps stator yoke, stator teeth, slot winding, rotor core, magnet and air-gap
regions to their corresponding thermal nodes. Pocket air, flux barriers, shafts
and unrecognised regions remain neutral; they do not inherit neighbouring
temperatures. The drawing carries no numbers. A table beside it lists every
node, including end windings, bearings, end-space air and housing, which are
absent from the radial EM mesh. Each row gives the node's temperature, a bar
running from the coolant temperature, a tick at the node's recorded limit and
its margin. Missing or incomplete mesh data shows an explicit message and the
table alone, without substituting a generic motor drawing. Each mapped
component has a flat colour from its recorded node-average temperature. The
scale spans only available node temperatures in the current result (including
ambient); it is not a safety scale and cannot be compared across separately
scaled results without reading the endpoints. There is no spatial
thermal-field interpolation. Unavailable nodes use grey hatching and show no
temperature or computed margin. A negative recorded margin reads "above limit"
in the table and in the key numbers; winding limits already include the
entered hotspot allowance. Selecting a row or a region shows that node's
status, reason, assigned heat and recorded limit. The unchanged PDF/CSV
numerical exports remain available for audit.

### Remaining-path audit and rating consistency

The path audit (`backend/benchmark_suite/thermal_path_audit.py`; its write-up is
kept in the private repository) supersedes the
historical axial/end-bundle/magnet approximations above. It provides derivations,
additional checks and recomputed point, native-propagation and rating evidence.
Housing is an outer-surface proxy, not a resolved shell mean under internal heat.
The coupled rating and its direct check now resolve active/end copper feedback
separately and use the resulting effective phase resistance for voltage. The
outer magnet-temperature loop retains its explicit convergence tolerance. At
prescribed measured heat, global resistance scaling remains linear for bench
fitting; fixed-current feedback predictions must not be scaled as if heat were
fixed. There are no physical calibration measurements to refit.
