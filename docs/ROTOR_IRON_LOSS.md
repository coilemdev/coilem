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

**Rotor iron loss is experimental.** The material coefficients cover up to 1 kHz and 1.5 T. Results beyond that range use extrapolation.

This model does not include magnet or other conducting-component eddy currents,
AC winding skin/proximity loss, a separate excess-loss term, minor-loop or
rotating-flux corrections, manufacturing effects, or loss feedback into the
magnetic solve. Magnet/component eddy loss is #307; AC winding loss is #308.
Classical eddy loss in the laminated rotor steel is included in this feature.

Sector validation is deferred beyond 0.5.9. Existing limited sector solves
remain experimental, and sector rotor loss stays unavailable pending
[#319](https://github.com/coilemdev/coilem/issues/319).
