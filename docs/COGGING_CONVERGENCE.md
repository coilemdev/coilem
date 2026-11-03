# Cogging torque: method and step convergence (#185)

[Public issue 185](https://github.com/coilemdev/coilem/issues/185) asks for the
cogging torque method and angular step to be chosen from evidence, not by
default. Cogging is a small difference of large stress contributions, and
coilEM meshes every rotor position on its own, without a sliding band, so
remesh noise is the main risk. This study measures it on the 8p/12s example
and fixes the defaults:

- **Method: weighted stress tensor (WST)**, whatever the loaded sweep uses.
- **Positions per cogging period: 12 (Preview), 24 (Standard), 48 (High
  accuracy)**, plus the repeated end.

The data is in [COGGING_CONVERGENCE.json](COGGING_CONVERGENCE.json): every
run's per-method numbers and its WST and contour waveforms.

## Setup

- **Design:** the app's 8p/12s example,
  `benchmarks/abcd-v1.5/fixtures/spm_8p12s_example_shoed.json`: shoed slots,
  1 mm air gap, N42, 100 mm stack. Its cogging period is 60° electrical, 15°
  mechanical, 24 cycles per mechanical revolution.
- **Default preset:** Standard, as the app sets it: normal mesh (29,088
  elements), corner refinement on, Precise mesh build, 30 A rms loaded sweep
  for the share of loaded torque (11.15 N·m mean).
- **Pipeline:** the public Magneto2D path (launch surface, isolated runtime)
  with Cogging torque on. Every run records all four torque extractions from
  the same field solutions, so the methods are compared on identical meshes.
- **Build:** Magneto2D sources identical to `a25aa4b`, macOS arm64, November 3,
  2026. Torques are in the public clockwise direction.
- **Noise measures.** An exact solve averages to zero over a period and
  repeats at its end. The mean over the period, and the end mismatch
  |T(60°) − T(0°)| between two separately meshed copies of the same position,
  measure how far the per-position meshes are from that.

## Angular step

Normal mesh, 12 to 96 positions per period:

| Positions | Method | Peak-to-peak (N·m) | First harmonic, 24/rev (N·m) | Mean (N·m) | End mismatch (N·m) |
| ---: | --- | ---: | ---: | ---: | ---: |
| 12 | **WST** | 1.3341 | 0.3636 | −0.0015 | 0.0057 |
| 24 | **WST** | 1.3341 | 0.3422 | −0.0021 | 0.0057 |
| 48 | **WST** | 1.3341 | 0.3345 | −0.0025 | 0.0057 |
| 96 | **WST** | 1.3341 | 0.3336 | −0.0026 | 0.0057 |
| 12 | Contour MST | 1.2623 | 0.3490 | +0.0127 | 0.0138 |
| 24 | Contour MST | 1.2623 | 0.3785 | +0.0118 | 0.0138 |
| 48 | Contour MST | 1.3683 | 0.3738 | +0.0111 | 0.0138 |
| 96 | Contour MST | 1.5698 | 0.3722 | +0.0114 | 0.0138 |
| 12 | Arkkio | 1.9675 | 0.3965 | +0.0530 | 0.3080 |
| 24 | Arkkio | 2.2295 | 0.4005 | −0.0263 | 0.3080 |
| 48 | Arkkio | 2.2721 | 0.4482 | +0.0316 | 0.3080 |
| 96 | Arkkio | 2.5567 | 0.4585 | +0.0293 | 0.3080 |

WST harmonics, cycles per mechanical revolution (N·m):

| Positions | 24 | 48 | 72 | 96 | 120 | 144 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | 0.3636 | 0.0390 | 0.2053 | 0.2351 | 0.1330 | (Nyquist) |
| 24 | 0.3422 | 0.0395 | 0.1985 | 0.2343 | 0.1442 | 0.0611 |
| 48 | 0.3345 | 0.0422 | 0.1977 | 0.2323 | 0.1438 | 0.0607 |
| 96 | 0.3336 | 0.0425 | 0.1998 | 0.2311 | 0.1442 | 0.0612 |

What the table shows:

- **WST is the only method that converges.** Its peak-to-peak is the same at
  every step: the peak and trough sit at 50° and 10° electrical, which every
  grid solves. Its harmonics settle by 24 positions: the fundamental is 2.6%
  above the 96-position value, the small second harmonic 7% below (0.040
  against 0.043 N·m) and the next four within 1.4%. Its mean and end mismatch
  are 0.2% and 0.4% of the peak-to-peak.
- **Contour MST carries remesh noise.** Its peak-to-peak grows as positions
  are added (1.26 to 1.57 N·m), because each new mesh adds its own jitter, of
  about ±0.2 N·m position to position. Its 144/rev harmonic reads 0.249 N·m at
  24 positions against WST's 0.061: that is noise, not cogging.
- **Arkkio is unusable for cogging here.** The two copies of the same
  position differ by 0.31 N·m, 23% of the WST peak-to-peak, and its
  peak-to-peak grows from 1.97 to 2.56 N·m. Its volume integral over the gap
  follows each remeshed gap layer.
- **Area MST is not usable as is.** It reads 0.022 N·m peak-to-peak with the
  same harmonic shape as WST, about 1/60 of the others; its scaling for a
  zero-current solve needs a separate look.

**Step chosen.** 24 positions per period for Standard: the peak-to-peak is
exact and the fundamental within 2.6% of 96 positions, at 25 field solves.
High accuracy's 48 brings the fundamental within 0.3%. Preview's 12 is within
9% on the fundamental and keeps the peak-to-peak here, but it resolves only
up to the fifth harmonic, so it is for iteration.

## Mesh

24 positions per period, WST, at each preset's mesh density:

| Mesh | Corner refinement | Elements | Peak-to-peak (N·m) | First harmonic (N·m) | Mean (N·m) | End mismatch (N·m) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Coarse (Preview's) | on | 13,996 | 1.5046 | 0.3852 | +0.0086 | 0.0209 |
| **Normal (Standard's)** | on | 29,088 | 1.3341 | 0.3422 | −0.0021 | 0.0057 |
| Fine (High accuracy's) | on | 29,820 | 1.3437 | 0.3430 | +0.0013 | 0.0037 |
| Normal | **off** | 83,200 | 1.2567 | 0.3415 | −0.0086 | 0.1230 |

What the table shows:

- **Normal and fine agree:** the peak-to-peak within 0.7% and the first
  harmonic within 0.2%. This design's fine mesh is only 2.5% larger than its
  normal one (their size factors in `backend/gmsh_solver.py` are 0.78 and 0.75
  of the base length), so this is a weak refinement. The very fine mesh, about six times the
  elements, was stopped for lack of disk space and is still to run.
- **The coarse mesh reads about 13% high** on both the peak-to-peak and the
  first harmonic. On Preview, the mesh, not the 12-position step, sets the
  error; Preview is for iteration.
- **Corner refinement controls the noise.** With it off, the air gap gets more
  elements but the magnet and slot-opening corners fewer, and the end mismatch
  rises from 0.4% to 9.8% of the peak-to-peak. The first harmonic hardly moves
  (0.3415 against 0.3422 N·m); the peak-to-peak drops 5.8%. Standard and High
  accuracy keep corner refinement on. The Solve page warns when Cogging torque
  is on and corner refinement off, and the
  [benchmark proposal](COGGING_BENCHMARK_PROPOSAL.md) turns it on for its cases.
- **The first harmonic is the steadier number.** Across normal, fine and
  corners off it spans 0.5%; the peak-to-peak, set by two single positions,
  spans 7%. That is why the proposal gates both.

Contour MST and Arkkio at the same meshes are in the JSON. Contour's end
mismatch falls without corner refinement (0.0008 N·m) while its peak-to-peak
rises to 1.47 N·m; Arkkio's end mismatch stays 0.31–0.90 N·m everywhere.

Wall times in the JSON are not comparable: the 24-position Standard run used
eight workers, the other angular runs three and the mesh runs two, to keep
memory down on a nearly full disk.

## Native values for the proposed cases

| Case | Peak-to-peak (N·m) | First harmonic (N·m) | Note |
| --- | ---: | ---: | --- |
| `spm_8p12s_example_shoed__cogging`, corner refinement on | 1.3341 | 0.3422 | The Standard run above |
| The same, as registered (corner refinement off) | 1.2567 | 0.3415 | End mismatch 9.8% |
| The other 11 Phase E cases | — | — | Still to run: the first was stopped at 4.5 GB free |

## Not covered

One design, one platform (macOS), and no very fine mesh yet. The other
topologies in the proposal have their own slot openings and pockets; their
FEMM comparison is what would qualify the method beyond this example.
