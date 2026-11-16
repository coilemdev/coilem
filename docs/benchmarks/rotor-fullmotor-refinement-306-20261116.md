# #306: full-motor refinement checkpoint

Target **0.5.9, full-motor rotor iron loss**. Status **PILOT_NOT_QUALIFIED**.
Sector rotor-loss work is deferred to #319; the existing limited sector
functionality remains in 0.5.9. No public rotor-loss result is enabled yet.

## Matched FEMM angular refinement

The same fixed-mesh, matched-excitation SPM history now has 192 samples plus
the independently solved endpoint. All old 96-grid poses are retained.

| Component | Native at 192, mW | FEMM at 192, mW | Native minus FEMM |
|---|---:|---:|---:|
| Rotor hysteresis | 16.5984039 | 16.5923311 | +0.03660% |
| Rotor lamination eddy | 47.9783767 | 48.0055546 | -0.05661% |
| Rotor iron total | 64.5767805 | 64.5978858 | -0.03267% |

All three max(10% of FEMM, 0.001 W) agreement checks pass. From 96 to 192,
FEMM changes by 0.01445% hysteresis, 0.87810% eddy and 0.65627% total, each
relative to the finer result. Both the production sampling and independent
DFT pass the max(5% of finer, 0.001 W) step. The second required step,
192 to 384, is running; this is not yet angular qualification.

Collection and reporting of this baseline continue in the frozen checkout
at `205db73c`. The registered protocol and all source hashes remain unchanged.
The adjacent JSON binds the intermediate raw analyses and comparison receipts.

## Native spatial design preflights

More cells alone do not establish refinement. The standard fine preflight
has 19,034 rotor cells but increases maximum rotor-cell area from 0.66808 to
0.74550 mm2; it is not used as one of the declared refinement steps. The
standard very-fine preflight has 574,154 total cells and took 16.03 s for one
solve/export. Both development preflights are retained without qualifying them.

The bounded study instead uses explicit targets in an owned validation driver:

| Level | Gmsh base target, mm | Rotor iron cells | Maximum rotor cell, mm2 | Total cells | Gap angular divisions / layers |
|---|---:|---:|---:|---:|---|
| Registered normal | 1.17 | 17,742 | 0.6680812 | 89,160 | 1,536 / 4 |
| Intermediate 1 | 0.94 | 27,374 | 0.4324237 | 140,102 | 2,304 / 5 |
| Intermediate 2 | 0.75 | 41,318 | 0.3226264 | 219,210 | 3,072 / 6 |

The two new zero poses took 3.29 s and 5.04 s for solve/export. These are
preflight observations under concurrent reference collection, not performance
qualification. Full histories and their component convergence checks remain
required. Each history must retain its own material template through the turn.

`tools.rotor_native_mesh_refinement` confines its temporary size override to
the owned collector process, records the target and driver SHA in source
identity, and restores the mesher function even if collection fails. It does
not change production mesher defaults, material assumptions or native solver
settings. The saved template's actual target and geometry are audited.

```powershell
python -m tools.rotor_native_mesh_refinement --base-lc-mm 0.94 --positions 384 --mesh normal --airgap-divisions 2304 --airgap-layers 5 --limit 1 --out OUTPUT/native-h094 --binary PATH/magneto2d.exe
python -m tools.rotor_native_mesh_refinement --base-lc-mm 0.75 --positions 384 --mesh normal --airgap-divisions 3072 --airgap-layers 6 --limit 1 --out OUTPUT/native-h075 --binary PATH/magneto2d.exe
# Resume disjoint shards only after the authoritative template exists.
```

## Matched reference spatial controls

The matched FEMM collector now accepts explicit bulk preset, air-gap target
and moving-band arc segmentation. Planned reference targets retain the earlier
bounded spatial study's controls: normal/0.125 mm/0.25 degrees,
fine/0.100 mm/0.20 degrees and very-fine/0.080 mm/0.16 degrees. Fresh preflights
must verify actual mesh refinement and runtime before full histories start.

This is a new collection-source version: it does not resume or relabel the
registered baseline using a different collector hash. The baseline stays in
the frozen `205db73c` checkout; new spatial histories bind the new collector
and unchanged sealed E/F source, binaries, excitation, steel and magnet
assumptions. Any comparison across collector versions must audit both source
snapshots and the explicit mesh-control-only change. Original raw evidence
and protocols are preserved.

Verification: **282 rotor/loss/reference/sector checks pass** in 61.39 s,
including invalid-control rejection and restoration/provenance checks. The
33 directly affected tests also pass; Ruff passes. Backend/Rust sources and
the 110 sealed historical reference files remain unchanged.

The [full-motor landing plan](../ROTOR_IRON_LOSS_59_LANDING_PLAN.md) still
requires reference and native spatial convergence, supported full-motor
fixture coverage, exact-once product integration and release qualification.
