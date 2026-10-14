# A/B/C/D benchmark protocol 1.2.0

Harness **1.3.0** supports protocol **1.2.0**. The default is still [protocol 1.1.0](../abcd-v1.1/README.md) until 1.2.0 has its FEMM reference bundle.

Protocol 1.2.0 changes one request: the **ORNL 2004 Prius** (`ornl_prius_2004_ipm`, Phase C) moves from planned coverage to a measured case ([#82](https://github.com/coilemdev/coilem/issues/82)).

**Fixture.** The [corrected fixture](fixtures/ornl_prius_2004_ipm.json) follows ORNL's primary sources, as recorded in the [fixture correction](../../docs/hardware-validation/ornl-prius-2004/fixture-correction.md):
- the rotor is mapped onto HoleM50 from ORNL's lamination drawing;
- the stator slot is fitted to the same drawing;
- the magnet follows ORNL's measured demagnetization line.

**Experimental rotor.** The case is registered with `"experimental_rotor": true`. The harness passes the experimental-rotor opt-in ([#70](https://github.com/coilemdev/coilem/issues/70)) for this case only. The public application still rejects HoleM50, and the report marks the row as an experimental rotor path with no qualification claim.

**Two comparisons.**
- **FEMM parity:** the usual A/B/C gates against a matched FEMM reference set the row's verdict. That reference is the owner's next FEMM run; see the [FEMM reference spec](../../docs/hardware-validation/ornl-prius-2004/femm-reference-spec.md). Until it lands, the row is NOT_COMPARED.
- **Exploratory hardware correlation:** no pass/fail, as #69 Phase B requires. ORNL's measured no-load line-to-line Back-EMF (ORNL/TM-2006/423 Table 3.4, 12 speeds) is set against coilEM's prediction:
  - line-to-line is phase A minus phase B;
  - RMS and the sampled peak are taken over one electrical cycle;
  - the prediction scales linearly from the solved speed.

  The report shows the table and a chart. A reduced `--smoke` grid never runs this comparison.

All other 29 requests, the golden vectors and the gates are unchanged from 1.1.0. The material contract gains the ORNL magnet (Br 1.235 T, μr 1.12).

## Run it

Before the 1.2.0 bundle exists, run without FEMM parity:

```sh
python -m tools.run_benchmarks --suite benchmarks/abcd-v1.2/benchmark_spec.json \
  --phases C --case ornl_prius_2004_ipm --no-reference --out-dir ../benchmark-output/prius --pdf
```

The other options work as in 1.1.0.
