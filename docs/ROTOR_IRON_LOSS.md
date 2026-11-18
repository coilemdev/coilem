# Experimental rotor iron loss

Rotor iron loss is an explicit option under **Losses & efficiency** in 0.5.9.
It defaults off. The Python/CLI analysis name is `rotor_loss`; the solve-options field is
`rotor_iron_loss`. Enabling it adds 384 full-turn poses and a fresh closure
solve, so it can substantially increase run time. In the app the option is
disabled, with the reason, for a design it does not support; `coilem check`
and `coilem.check` give the same reason as a warning before any solve.

The supported calculation follows fixed rotor steel cells through a complete
mechanical turn and transforms the magnetic field into rotor coordinates.
It estimates rotor hysteresis and classical **lamination** eddy loss using the
bundled M350-50A empirical coefficients. Both components and their total are
reported separately, with method, material, sampling and frequency-coverage
provenance. Completed requested rotor loss enters the operating-point and map
loss balances exactly once. An unavailable requested term is not silently zero;
incomplete loss accounting withholds efficiency.

## Supported requests and limits

- Full-motor models (`symmetry: full`) of inner SPM or flat-buried IPM rotors.
- Sinusoidal excitation, positive mechanical speed and M350-50A rotor loss data.
- Imported reference geometries, V-shape IPM, outer rotors, sector solves,
  unsupported steels and other excitation modes return an unavailable status.

**All rotor-loss results remain experimental.** Completed FEMM comparisons
test the field-history calculation against an independently processed numerical
reference with matched loss coefficients. They do not validate those coefficients
against a measured motor. Reported loss above the coefficients' 1 kHz or 1.5 T
coverage is extrapolation, even when numerical convergence passes.

This model does not include magnet or other conducting-component eddy currents,
AC winding skin/proximity loss, a separate excess-loss term, minor-loop or
rotating-flux corrections, manufacturing effects, or loss feedback into the
magnetic solve. Magnet/component eddy loss is #307; AC winding loss is #308.
Classical eddy loss in the laminated rotor steel is included in this feature.

Sector validation is deferred beyond 0.5.9. Existing limited sector solves
remain experimental, and sector rotor loss stays unavailable pending
[#319](https://github.com/coilemdev/coilem/issues/319).

## Numerical evidence

Status at the 2026-11-17 release-integration decision:

| Full-motor condition | Native/FEMM total difference, 1500 / 3000 rpm | Completed checks |
|---|---:|---|
| Loaded SPM 8p/12s, 20 A peak | +0.373% / +0.384% | Angular, independent native/FEMM spatial refinement, closure and component agreement |
| No-load SPM 8p/12s | -0.169% / -0.117% | Angular, closure and component agreement on the established SPM mesh |
| Loaded flat-IPM 8p/12s FSAE, 50 A peak, working mesh | +1.064% / +1.171% | Angular, closure and component agreement; FEMM finer-mesh check incomplete |

Native field collection for the reduced matrix is complete. The FEMM
loaded-flat finer history and flat no-load reference remain outstanding at
this checkpoint. No-load rows do not claim an independent spatial study at
each load point. Passing existing rows does not qualify the unfinished matrix.

The [public-path rehearsal](benchmarks/rotor-public-integration-306-20261116.md)
reproduced the internal loaded-SPM native result; analytical and integration
tests cover frame conventions, DC/sinusoidal controls, speed scaling,
unavailable states, saved results, maps and exports. Full assembled-release
loss qualification on Windows and macOS remains deferred.

## 0.5.9 release boundary

The [completed stator/DC-copper FEMM record](qualification/stator-copper-femm-20261117/README.md)
supplies Phase G of the A–G benchmark. It excludes rotor loss and does not close
the deferred rotor-history, material-accuracy or sector qualification work.

The release owner approved landing the physics implementation while retaining
experimental status. Remaining rotor-loss qualification is a future-release
follow-up, [#330](https://github.com/coilemdev/coilem/issues/330). The immediate 0.5.9 validation priority is
full-motor A–F/Prius regression against frozen FEMM references and published
0.5.8 evidence, using the exact assembled release candidate on both platforms.
That run does not qualify the new opt-in rotor-loss calculation. The
[landing plan](ROTOR_IRON_LOSS_59_LANDING_PLAN.md) records the revised gates.
