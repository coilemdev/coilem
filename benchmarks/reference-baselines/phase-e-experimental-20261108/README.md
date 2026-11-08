# Experimental Phase E cogging references

This protocol 1.7.0 dataset supplies the twelve retained FEMM reference
waveforms for the normal composed benchmark report. **Cogging remains
experimental and unqualified**, including cases whose numerical gates pass.
The dataset has no accepted reference review and no qualification record.

The selection is unchanged: nine original baseline references and three
previously selected half-airgap-mesh distributed-winding references. All
twelve selected references pass their period and mean self-checks. The three
original baseline self-check failures remain visible in the retained public
comparison; they were not rewritten as passing observations.

Schema `coilem.frozen_reference_bundle/v2` uses a SHA-256 dataset identifier.
`selected-waveforms.json` is the exact hash-bound dataset; each record matches
its registered case input and this dataset. `source-evidence.json` binds the
existing public waveform, result and provenance artifacts, retaining their
actual older native measurement identity. Private producer identities and
machine paths are excluded.

The retained native comparison is **10 PASS / 2 YELLOW** under unchanged
10%/20% relative gates and the registered absolute floors. This publication
does not measure the current v0.5.5 native source or qualify cogging on any
platform. New normal benchmark runs grade their actual native measurements
against these references and keep the Phase E badge experimental.

Reproduce the public projection without field solves:

```sh
python -m tools.build_phase_e_experimental_packet --check
```
