# ORNL 2004 Prius rotor: HoleM50 mapping

This is step 1 of [#70](https://github.com/coilemdev/coilem/issues/70). The [Phase A source audit](source-audit.md) measured the 2004 Prius rotor pocket from ORNL's vector lamination drawing (S5, ORNL/TM-2005/33 Fig. 21, p.25 (PDF 32)). It found that only coilEM's `pyleecan_holem50` rotor family has this shape: one connected V per pole, with stop notches and end flux barriers. This page fits HoleM50's parameters to the drawn pocket and records the residuals.

The fit data is in [`holem50-mapping.json`](holem50-mapping.json). [`tools/fit_ornl_prius_holem50.py`](../../../tools/fit_ornl_prius_holem50.py) regenerates it from the S5 PDF, about a minute:

```sh
python tools/fit_ornl_prius_holem50.py osti-885987.pdf docs/hardware-validation/ornl-prius-2004/holem50-mapping.json
```

Download S5 from [OSTI](https://www.osti.gov/servlets/purl/885987). The tool refuses any file whose SHA-256 differs from [`sources.json`](sources.json). It needs pypdf, a development dependency.

Nothing here is compared with ORNL's measurements. The back-EMF comparison is #69 Phase B, which stays blind.

## Result

**HoleM50 represents the ORNL pocket within Phase A's read-off error** (±0.5 mm on positions). Across all 8 poles, the drawn outline lies on average 0.11 mm from the HoleM50 hole that coilEM meshes, and 95% of it lies within 0.24 mm. The worst points, up to 0.67 mm, are on the pocket tips, whose shape HoleM50 can't express (see below).

The recommended parameters fix the outer bridge at the drawing's stated callouts. The others are fitted, rounded to 0.01 mm:

| Parameter | What it sets | Mapped (mm) | Existing fixture (mm) | Phase A direct measurement |
| --- | --- | --- | --- | --- |
| H0 | Depth of the V apex (outer edge) below the rotor surface | 10.71 | 10.96 | 10.4–11.2, mean 10.8 |
| H1 | Outer bridge, between the pocket tips and the rotor surface | 1.47 (stated) | 1.50 | Callouts 0.056 and 0.060 in (1.42, 1.52) |
| H2 | Stop-notch height | 1.75 | 1.00 | Not measured |
| H3 | Pocket width across an arm; the magnet thickness | 6.81 | 6.50 | 6.67–6.85 |
| W0 | Chord between the two arm tips on the bridge arc | 41.70 | 42.00 | Not measured |
| W3 | Web between the pockets of adjacent poles | 13.68 | 14.00 | Not measured |
| W4 | Magnet seat between the stop notches; the magnet length | 19.30 | 18.90 | Straight seat edge 18.3–18.6 |
| W1, W2, H4 | Centre post, magnet offset from the apex, radial bridge | 0 | 0 | None drawn |

The rotor OD and ID are the dimensioned 6.314 in and 4.356 in: 160.38 mm and 110.64 mm. The existing `ornl_prius_2004_ipm` fixture uses Pyleecan's published Toyota_Prius values, which Phase A could not trace to ORNL. #82 corrects the fixture; this page only supplies the rotor values.

Fit quality of each variant, as distance from the drawn outline to the HoleM50 outline:

| Variant | RMS (mm) | 95th percentile (mm) | Max (mm) |
| --- | --- | --- | --- |
| A: Pyleecan Toyota_Prius values (existing fixture) | 0.26 | 0.46 | 1.05 |
| B: all eight parameters fitted | 0.10 | 0.22 | 0.57 |
| C: as B, with H1 at the stated callouts | 0.11 | 0.24 | 0.66 |
| Recommended: C rounded to 0.01 mm | 0.11 | 0.24 | 0.67 |

Each pole fits equally well: per-pole RMS is 0.108–0.116 mm for the recommended set.

## Residuals by pocket feature

Positive values mean the drawn pocket is larger than the HoleM50 pocket there.

| Feature | Existing fixture: mean (max) | Recommended: mean | Recommended: RMS | Recommended: max |
| --- | --- | --- | --- | --- |
| Outer edge (H0, W0) | +0.17 (0.28) | −0.01 | 0.04 | 0.16 |
| Magnet seat (W4) | +0.13 (0.57) | +0.01 | 0.07 | 0.38 |
| Stop notch, tip side (H2) | +0.37 (0.56) | −0.01 | 0.04 | 0.20 |
| Stop notch, apex side (H2) | −0.25 (0.94) | −0.03 | 0.06 | 0.25 |
| Apex inner edges | −0.80 (1.05) | −0.20 | 0.21 | 0.37 |
| Barrier inner edge | −0.25 (0.54) | +0.17 | 0.17 | 0.28 |
| Tip edge facing the q-axis | +0.12 (0.55) | 0.00 | 0.20 | 0.67 |
| Tip arc (bridge H1) | −0.21 (0.56) | −0.23 | 0.29 | 0.63 |

The existing fixture's apex sits 0.8 mm too deep, and its notches are too shallow.

## What HoleM50 can't express

- **Pocket tips.** ORNL's tips are chamfered polygons; HoleM50 closes each tip with an arc concentric with the rotor surface and a sharp corner. This leaves up to 0.67 mm locally at the tip corners. With H1 fixed at the stated 1.47 mm, the drawn tips sit 0.23 mm deeper on average. Fitting H1 freely (variant B) gives 1.68 mm, within the ±0.5 mm read-off error of the callouts. The stated value is used, as Phase A recommends for the bridges.
- **Apex.** The drawn apex inner edges lie 0.20 mm inside HoleM50's V on average (0.37 mm at most).

Everything else agrees within 0.17 mm on average.

## Magnet length

HoleM50 ends each magnet at the stop-notch steps, so the 2D magnet length is W4 = 19.30 mm. Phase A's 18.3–18.6 mm is the straight part of the seat edge, which excludes the notch transitions. ORNL states neither, and the two differ by about 4.5% in magnet volume. Phase B should carry the magnet length as a band, as the audit's gap list already does for the magnet dimensions.

## Drawing calibration

Phase A scaled the drawing from its rotor OD circle. The fit also solves for the drawing's centre offset, rotation and plot stretch, which are common to all 8 poles.

The drawing is **stretched 1.19% in x relative to y**. An ellipse fitted independently to the drawn rotor OD gives the same 1.19%, and the drawn bore gives 0.6% in the same direction. The fitted centre offset (+0.05, −0.09 mm) matches the ellipse centre.

The stretch explains two Phase A observations:
- The apex depth varies from pole to pole (10.4–11.2 mm): poles near the drawing's x-axis read shallow and poles near its y-axis read deep.
- The drawn OD dips up to 1.1 mm inside the nominal circle.

After correction, the poles agree.

## Experimental solves

Public requests still reject HoleM50 with the existing message, and the A/B/C/D suite still records the Prius fixture as UNSUPPORTED.

For research, [`tools/experimental_solve.py`](../../../tools/experimental_solve.py) solves a HoleM50 design natively with Magneto2D:

```sh
python -m tools.experimental_solve --config design.json --output result.json --no-load
```

What the tool does:
- It applies every other public request check, accepts only the experimental rotor families, and refuses supported designs.
- It labels its output experimental, with no qualification claim.
- No HTTP route reaches it.

To build the ORNL design, merge `recommended.rotor` from `holem50-mapping.json` into a Prius design's rotor block. The mapped rotor meshes with Gmsh (about 34,000 elements at coarse density) and solves at no load and on load.
