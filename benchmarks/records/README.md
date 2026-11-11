# Published benchmark records

`coilem benchmark` matches [protocol 1.10.0](../af-v1.10/README.md) against these
platform records. They bind the full A-F selection, the frozen reviewed
reference components, measured physics, gate statuses, numerical values and
per-case times. Phase E records peak-to-peak cogging and its first harmonic;
F uses the existing torque and back-EMF gates.

| Record | Measured at | Outcome |
| --- | --- | --- |
| [Windows x86-64](windows-x86_64.json) | `70c5e34` | 68 PASS, 468 gates, one planned unsupported |
| [macOS arm64](macos-arm64.json) | `70c5e34` | 68 PASS, 468 gates, one planned unsupported |

[Full measured reports and Prius evidence](../qualification-70c5e3404c19/README.md)
retain the source identities and verification receipts. The
[previous A-D records](../records-historical/protocol19-20261110/) remain
byte-for-byte available. A Linux run can compare to the closest record; a
cross-platform match is not a Linux qualification.

## Matching a record

The command hashes the installed physics sources and compares them with the
record. A wheel includes the corresponding native source hashes with its
solver executable. A changed source yields **NOT_COMPARABLE**; the
reference gates still run.

A comparable case must keep its verdict and each gate status. Numeric replay
tolerances use the greater of the relative limit and absolute floor:

| Metric | Relative limit | Absolute floor |
| --- | ---: | ---: |
| Mean torque | 0.5% | 0.001 N·m |
| Back-EMF fundamental | 0.05% | 0.001 V |
| Back-EMF peak | 1.5% | 0.001 V |
| Cogging peak-to-peak and first harmonic | 0.5% each | 0.0001 N·m each |

The command reports **MATCH** when every selected case agrees, and **DIFFERS**
with the affected cases and values otherwise. The [registered FEMM
gates](../af-v1.10/README.md) are separate from these replay tolerances.

## Reproduce the selection

```sh
coilem benchmark --list
coilem benchmark --quick    # six cases, one complete-grid case per phase
coilem benchmark            # all 69 registered cases
coilem benchmark --phase E --phase F
```

The command records each job and writes full and shareable reports. The
times listed by the command come from the platform record. The hosted
collection runs shards in parallel, so its elapsed span differs from the
sum of case times and from a local run. Platform records are built from
verified measured artifacts. The historical reports keep their original
source identities and reference cohorts.
