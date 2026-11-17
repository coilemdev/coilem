# Full-motor rotor iron loss: public-path rehearsal for #306

Target: 0.5.9. **PILOT_NOT_QUALIFIED.** This is the same loaded SPM motor;
the broader FEMM release matrix has not started. Sector rotor loss remains
deferred to #319.

The normal public orchestration (`Magneto2DSolver(launch_surface=True)`) ran
the existing electrical sweep and a separate opt-in 384-position mechanical
turn plus an independently solved endpoint. It produced exactly the same
rotor watts as the internal fixed-material native pilot:

| Component | Public native | Internal native difference |
|---|---:|---:|
| Rotor hysteresis | 16.5971897705 mW | 0 W |
| Rotor lamination eddy | 47.9662636078 mW | 0 W |
| Rotor total | 64.5634533782 mW | 0 W |

Endpoint maximum component difference is 1.04e-13 T; RMS is 2.59e-14 T.
Input minus shaft power minus total loss is 2.84e-14 W. Runtime was 420.49 s
on the shared Windows host while the two FEMM spatial histories were active;
this is not a performance guarantee.

The [receipt](rotor-public-integration-306-20261116.json) records the material,
history identity and the exact source hashes used for this run. Later
postprocessing validation added stricter endpoint/history metadata checks and
an unsupported-domain guard; replay of the saved field reports still produces
the same rotor record and complete loss breakdown without new field solves.
Replaying it as a sector request reports rotor loss unavailable and withholds
efficiency. CSV retains the separate components and history provenance. The
PDF's loss table, rotor components, density-map scope and frequency-coverage
note were rendered and visually inspected.

## Product contract

- `solve_options.rotor_iron_loss` defaults off. Disabled serialization leaves
  existing requests unchanged. The option requires `losses_efficiency`.
- The UI provides an explicit option and explains the additional 385 solves.
  Python/CLI analysis name `rotor_loss` also selects its loss dependency.
- The first implementation supports full inner-rotor SPM and flat-IPM models,
  sinusoidal excitation, positive speed and M350-50A rotor steel. Imported
  reference geometries and sector requests report explicit unavailable values.
- Hysteresis, lamination eddy and total remain separate from stator loss.
  Accounting includes rotor watts once; requested unavailable rotor loss
  withholds efficiency rather than substituting zero.
- Map cache identities distinguish the opt-in. Each selected map point has
  its own full mechanical history; speed scaling uses hysteresis proportional
  to speed and eddy loss proportional to its square. Point material, history
  and availability records are retained. Missing requested rotor data makes
  map efficiency unavailable.
- A real coarse flat-IPM mesh passes a prescribed static-material-field
  motion test with effectively zero false loss. This is an analytical geometry
  control, not an additional FEMM qualification case.

The model remains experimental: 10.54% of this rotor estimate comes from
frequencies above the material model's 1 kHz coverage. Numerical solver parity
does not establish measured motor-loss accuracy. DC-bias/minor-loop,
rotating-flux, excess, magnet/component eddy, AC winding and inverter loss
corrections are outside this rotor-iron-loss slice.

## Qualification boundaries

Both native and matched FEMM angular refinements (96/192/384) pass on this
motor. Native spatial refinement passes both steps, with totals
64.56345, 64.36554 and 64.20315 mW. Matched FEMM spatial histories are being
collected with unchanged sources and one fixed mesh per history. Their loss
and convergence verdicts remain open.

The full SPM/flat-IPM load/speed matrix follows review of that bounded spatial
result. The PR stays draft. Existing release-source qualification remains
pending: the Python client's qualification assertion also fails on the
unchanged release-based checkout, which reports experimental rather than
qualified. Historical qualification records and expectations were not
rewritten to make that assertion pass.

The cost plan has four distinct field-history conditions: two geometries,
each at no load and loaded. In this magnetostatic model, the second speed is
an independent loss-postprocessing check on the same field histories. Each
qualified condition must still meet the registered angular and two-step
spatial convergence criteria; this SPM result does not establish convergence
for another geometry or load. Preflight timings will determine the remaining
campaign before it starts. Routine regression can use retained converged
references.

The optional-flag config change has a separate measured geometry renewal:
all three reviewed cogging fixtures have identical default config, geometry
IR and full-motor zero-pose mesh hashes before and after. The
[equality receipt](rotor-default-geometry-renewal-306-20261116.json) and
`tools/rotor_default_geometry_proof.py` make this source-only renewal
reproducible; it does not carry forward a new numerical qualification verdict.
