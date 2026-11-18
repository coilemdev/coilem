# 5.9 stator iron and DC copper qualification

The [final Windows results](../../docs/qualification/stator-copper-femm-20261117/README.md)
pass the declared integrated-loss gates for all eight full-motor fixture/load
conditions at both speeds. The frozen FEMM values now supply
[Phase G of the default A–G benchmark](../ag-v1.12/README.md).
Regular G runs use one qualified 96-position request per operating point;
the 24/48/96 refinements and independent endpoints belong to this retained
qualification campaign. Rotor loss remains experimental and excluded.

Owner decision: prioritize the dominant stator/DC-copper terms for 5.9. Rotor
iron loss remains experimental and its qualification is deferred. The original
384-pose histories, failed gates and references are retained unchanged.

The separate `stator-copper-59.json` registration covers the same four full-motor
fixtures and loaded/no-load points, M350-50A, specified wire at 20 C, public gamma
zero and sinusoidal excitation. It measures one electrical cycle, 96 half-open
poses plus a reference endpoint. For an 8-pole motor this is 90 mechanical degrees.
The outer 10-pole fixture uses 72 mechanical degrees. Mechanical and electrical
angles are recorded separately; the electrical frequency is rpm times pole pairs
divided by 60. Sector losses remain outside scope.

Native results come from the production `Magneto2DSolver(launch_surface=True)`
API, with loss enabled and rotor loss explicitly off. Actual 24/48/96-position
requests at 1500/3000 rpm test the public sampling and integration path. Retained
full field artifacts reproduce the public stator result, within a 1e-5 relative
or 1e-6 W archive-only tolerance for their float32 serialization. The original
1-ppm check stopped the distributed acquisition on a 3.5-ppm difference; that
failure and the unmodified API results remain retained. The archive tolerance
is separate from the unchanged component gates. Exact predecessor acquisitions
can resume with their original producer identities; the new archive processor
has its own hashes in the completion receipt. Convergence metadata,
requests, source identities and result hashes are retained.

The FEMM reference uses the frozen E/F adapters and an independent direct DFT.
Verified existing reference poses may be projected onto the electrical grid;
their original protocols/checkpoint/answer identities are retained. Only missing
poses are solved. Base mesh geometry may be reused across load points only when
geometry, winding, magnets and materials match; currents are independently reset
and audited at every new pose. Reference losses never use native B fields.

The integrated-loss gates are registered separately in
`stator-copper-loss-gates-59.json`, version 2. The acquisition profile and all
original point-field diagnostic results are retained. The live production
preflight showed that slot-pitch mesh reuse changes the stator triangulation at
equivalent positions: comparing it with a separately meshed endpoint measures
spatial interpolation/discretization as well as physical repeatability. It is
not a same-cell rotor-history closure test. Version 2 therefore qualifies the
integrated-loss quantity and treats the failed version-1 point-field check as a
diagnostic. This policy revision does not relabel the original failed verdict;
its acquisition profile, data and failed results remain retained.

Independent component loss gates:

- Stator hysteresis, lamination eddy and total: 10% of FEMM or 0.001 W.
- Both 24-to-48 and 48-to-96 angular steps: 5% or 0.001 W, each term and speed.
- DC phase resistance and nonzero-current copper watts: 1%. Zero-load points
  still check resistance. FEMM winding geometry feeds the independent conductor,
  turns and end-turn calculation; it is not a FEMM AC-winding eddy-current solve.
- Stator loss-cycle repeatability: at most 1% or 0.001 W change in each loss
  term under a diagnostic linear endpoint-drift sensitivity calculation. This
  loss-sensitivity budget was registered before the live production preflight.

The acquisition profile's 0.1% area-weighted field-RMS check and the original
rotor-material history's 1e-6/1e-7 T pointwise closure check are reported as
diagnostics, including failures. They do not qualify the integrated loss across
different triangulations. The 1% loss-sensitivity, 5% sampling and 10% reference
gates stay unchanged. **Unmodified
fields always produce the reported loss**; the sensitivity calculation never
repairs a history or replaces its reference value. The original full-turn
closure failures retain their original failed verdicts.

The resulting claim is numerical reference qualification of these components
within this declared scope. Empirical material accuracy, magnet/component eddy
losses, AC winding losses, mechanical losses and complete motor efficiency remain
experimental or excluded. The product's rotor and iron-model statuses are not
promoted by this tooling change.

Run from a clean committed checkout, with output outside source:

```powershell
python -m tools.phase_g_loss.stator59 --out ../stator-run-v1 --legacy ../run-v1 --binary <magneto2d.exe> --femm-python <pinned-python.exe>
```

All native conditions finish first. Then two FEMM workers per condition collect
two conditions concurrently, with four FEMM instances maximum. Completed raw
fields are retained on interruption. Unexpected worker/source/integrity failures
stop the run. Failed numerical gates remain visible in the component report.
