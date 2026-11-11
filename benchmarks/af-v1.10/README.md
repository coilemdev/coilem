# Protocol 1.10.0: combined A-F benchmark

`coilem benchmark` now selects all six phases. Harness 1.12.0 runs **69 cases,
75 jobs**, with **68 frozen reference records** and the existing planned
unsupported Prius suite row. The separate Prius software qualification remains
in the release collection and is not replaced by that unsupported row.

| Phase | Coverage | Cases |
| --- | --- | ---: |
| A | SPM | 19 |
| B | IPM | 20 |
| C | Distributed winding, including the planned unsupported Prius row | 5 |
| D | BLDC | 3 |
| E | Cogging | 12 |
| F | Outrunner | 10 |

## Physical and reference contracts

A-D requests are exactly the protocol 1.9.0 requests. Nine E requests retain
their current normal native meshes; the three distributed E requests are
exactly the registered protocol 1.7.1 `very_fine` requests. F requests retain
their current native mesh and Newton settings. Angle grids, materials, floors,
limits and extraction methods are unchanged. The expected full passing gate
count is 468: 336 A-D, 72 E and 60 F.

The registry composes five explicitly hash-bound components:

- A-D, reusing the reviewed protocol 1.6.0 reference bundle through its existing
  protocol 1.9.0 native Newton bridge.
- Nine normal E references, at original source commit `341cd093`.
- Three refined E references, through the existing reviewed protocol 1.7.1
  mesh-only bridge, also at original source commit `341cd093`.
- Nine original F references, at original source commit `7d9445c7`.
- The separate F hub reference, at source commit `5291451c`, preserving its
  explicit 0.5 mm bulk / 0.15 mm magnet-and-pocket / 0.125 mm airgap recipe.

No record is restamped to a fictitious shared reference commit. The combined
manifest has `reference_commit: null`, lists all four original commits, and
binds every original record through its component. The E/F measured request
bytes are preserved in `measured-fixtures`. The only permitted component-to-
current request change is an explicitly declared native Picard-to-Newton
change; other physical changes fail closed.

E review recomputes the complete period, independent reference closure and
zero mean against each original case floor. F review validates the full grids,
extraction policy, phase balance, source ledger and original output payloads.
The [F source policy](phase-f-source-policy.json) retains the November 8 scoped
owner review, both historical LRK failures and the two source cohorts. No
uncertainty bound is claimed and no old gate is waived.

## Run and reproduce

```sh
coilem benchmark --list
coilem benchmark --quick --out ../benchmark-output/af-quick
coilem benchmark --phase E --phase F --out ../benchmark-output/ef
coilem benchmark --out ../benchmark-output/af-full
coilem benchmark --resume --out ../benchmark-output/af-full
```

Quick mode selects one complete-grid request per phase. It does not reduce
angle grids or numerical gates. Old A-D platform records are retained as their
original evidence; they cannot claim coverage of a new full A-F selection.
Native runtime estimates are shown only when the selected record covers all
selected cases. Fresh FEMM collection is separate: routine candidate runs read
the frozen references and collect Magneto2D.

`python -m tools.make_combined_protocol` reproduces the registered suite and
new E/F bundle bytes from the committed collection results, measured requests,
source policy and existing reviewed bundles. The loader verifies complete,
nonoverlapping coverage, every dependency hash, each physical request and all
component reviews. Installed wheels carry this entire data dependency closure;
they need no Git checkout, FEMM installation or external adapter repository.

The release numerical workflow's normal `registered` collection now measures
A-F plus the separate complete Prius software collection. It builds and pins
one immutable candidate independently on Windows and macOS, verifies each
shard and joins the original measurements without new solves.

Reference registration and successful tests do not themselves qualify a new
native candidate. Full platform measurements and their reviewed records remain
the basis for that claim. Application capability qualifications retain their
existing scope; this protocol change does not automatically promote arbitrary
outer-rotor or cogging requests.

## Initial measured qualification

[Windows and macOS qualification](../qualification-70c5e3404c19/README.md)
passed at candidate `70c5e34`: 68 supported cases and all 468 gates on
each platform, plus the planned unsupported Prius row. The separate Prius
collection passes all ten software checks on both platforms. The current
[platform records](../records/README.md) now cover the complete selection.
