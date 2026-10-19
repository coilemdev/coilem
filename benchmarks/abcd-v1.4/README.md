# Cap-200 benchmark request registration

Protocol 1.4 retains protocol 1.3's complete matrix, winding-axis validation,
physical inputs, sampling grids and numerical gates. Its only request change is
`max_nonlinear_iterations: 100` to `200` for all three stages of these BLDC cases:

- `spm_4p12s_small`
- `spm_8p12s_reference`
- `spm_14p12s_high_pole`

The stricter Custom/Picard stopping test retains its raw mismatch tolerance of
0.001. Targeted diagnostics measured maxima of 100–109 iterations; the larger
cap supplies headroom without weakening convergence.

The nine requests are new files. The previous suite, fixtures, FEMM reference
bundle and qualification reports remain immutable. `reference_compatibility`
retains the existing winding-axis bridge and adds an iteration-cap bridge bound
to the exact protocol 1.3 suite hash. The loader verifies every changed request
against its original bytes and canonical input hash, permits only 100 to 200,
and rejects changes to geometry, excitation, tolerances, stages, protocols or
gates. Frozen reference records retain their measured input hashes. The wheel
includes the old requests needed for these checks.

This registration does not qualify the changed solver. Targeted results are
recorded separately; the full A/B/C/D qualification rerun and new published
platform records remain work for the 0.5.0 freeze. Historical reports must not be
relabelled as measurements of these requests.
