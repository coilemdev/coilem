# Windows FEMM adapter provenance and v0.4 / v0.5 comparison

This index identifies the recovered adapter actually used on the original Windows host. The private source and installed binaries are archived locally under:

    %USERPROFILE%/Documents/coilem-benchmark-archives/femm42-pr100-v3-and-protocol16-20261102

The capsule is separate from temporary benchmark folders. Its README, verification script, per-file manifest and source-path map accompany the archives. This directory contains public-safe provenance and numerical summaries; private adapter code and executables remain in the private capsule. No remote backup or upload was performed.

## Direct version comparison

The [full per-case comparison](version-comparison.txt) and [machine-readable results](version-comparison.json) compare:

| Evidence | Native source | Protocol | Native jobs | Cases |
| --- | --- | --- | ---: | --- |
| v0.4 report | `5b6cb61e65a219ab92a742ac49c37433f53418fb` | 1.3.0 | 35 supported | 28 PASS, 1 YELLOW, 1 planned unsupported |
| v0.5 current Windows run | `88aae101fd487795e7fe5300737679f4133790fd` | 1.6.0 | 52 supported | 46 PASS, 1 planned unsupported |
| v0.5 earlier Windows VM | `bb3d8aff93dd2b2c2900ac1b9c65729a939874f6` | 1.4.0 | 35 supported | 29 PASS, 1 planned unsupported against frozen v3 |

The old report is the release evidence linked from [v0.4.0](../../v0.4.0/README.md). It retains its measured pin; it is not restamped as a new final-tag collection. The prior release audit records that its 53 physics-source hashes match release `2ede4e8`.

There are 29 common supported cases and 35 common native jobs. The checked FEMM reference signatures are exactly equal in every common case: ABC mean torque, H1/peak/flux values where present, torque/EMF waveforms and mesh counts; D compact numerical/source fields. Timing and path metadata are outside that equality claim. The A/B/C evaluator AST is identical; 8% torque and 10% fundamental/peak green gates were not relaxed. Protocol 1.6 adds 17 cases; their PASS outcomes must be distinguished from changes to the old cases.

The V-shape baseline is the one shared verdict change, YELLOW to PASS:

| Error versus unchanged FEMM reference | v0.4 | v0.5 |
| --- | ---: | ---: |
| Mean torque | 5.8454% | 7.0224% |
| EMF fundamental | 2.0563% | 8.2864% |
| EMF peak | 14.7787% | 9.0128% |

The peak passes the same 10% gate. Mean fundamental error across all six V-shape cases grows from **2.3866% to 6.5029%**. Corrected native Newton stopping changes these weak-flux results; improved equation convergence does not establish improved FEMM or hardware agreement. V-shape accuracy remains experimental. Loaded ABC mean-torque changes have median magnitude 0.1907%, with the largest +1.1120% on the baseline V-shape. This is a numerical version comparison, not a controlled speed comparison.

## Why the VM report differed

The [published VM record](https://github.com/coilemdev/coilem/blob/88aae101fd487795e7fe5300737679f4133790fd/benchmarks/windows-v050-20261029-bb3d8af/README.md) explicitly distinguishes frozen v3 references from newly reconstructed references. On the **same native fields**, swapping the reference changes pocket-offset peak-EMF error from **9.8069% to 10.3835%**, crossing the unchanged 10% green line. Its diagnostic becomes 28 PASS / 1 YELLOW / 1 unsupported. No additional native field solves were made for that comparison. Across the 35 shared native jobs, the largest relative mean-torque shift from the VM to this host is about 0.000063% after excluding near-zero means. This demonstrates a reference-substitution effect on the verdict; the published package does not contain the VM's private adapter bytes needed to identify the exact source-level numerical cause.

The later [VM V-shape study](https://github.com/coilemdev/coilem/blob/88aae101fd487795e7fe5300737679f4133790fd/docs/VSHAPE_EMF_AUDIT_20261030.md) is another distinct diagnostic. It uses the reconstructed reference model and refines 32 outer bridge/pocket segments to 0.2 mm while leaving the rotor interior automatic. That normal-mesh native candidate becomes YELLOW at 10.0841% peak error. The new local control refines rotor straight segments more broadly and also limits rotor arcs to 0.5 degrees; it passes. The two controls use different reference bases and mesh recipes. They must not be presented as identical reproductions or as evidence that either reference is spatially converged.

## Which adapter to preserve

The private adapter base commit `8b95decda27d475ddbb75e99d92744ebc8e53b28` alone is insufficient identification. The actual v3 adapter includes six shared PR100 modules plus FEMM-specific lowering/extraction in `v3_adapter.py` and compatibility helpers. All **172 retained source/material/runtime files** match the original prepared seal; all **29 legacy cases** have been remeasured with exact checked reference results on this host.

The new protocol 1.6 bridge has separate identity `faced858937e93740ddf7f6f3583a3ad5ec35646`. Historical cases retain v3 density/flux extraction; the shoed and 12 d/q cases use predeclared explicit phase circuits; the four temperature cases use registered Br values. Preserve both identities and these measurement roles.

[provenance.json](provenance.json) binds the private archive manifest and six archive components to SHA-256. The capsule contains exact adapter/runtime sources, full FEMM installation, the measured native executable, dependency inventory, two private bridge Git bundles, three public source snapshots, frozen reference/evaluation evidence and a verifier. Its integrity check passed for **5,623 ZIP entries and 1,025 retained/recovered payload sources**. Public-worktree files missing at their old paths were recovered only when public Git bytes matched the original prepared seal; these recoveries are explicitly identified. The private adapter itself was not reconstructed.

On a VM, verify executable hashes and the COM registration target, source/normalizer hashes, winding-source policy, material curves/Br, grids, mesh and precision settings. The captured 32-bit COM target is `c:/femm42/bin/femm.exe`. Product version `4.2` alone does not distinguish installed builds or guarantee which executable COM starts.

The historical scripts contain fixed paths. The capsule documents relocation requirements and is **not yet validated as a one-command VM replay**. The archived Python launcher is not a complete Python installation. All fresh references remain **REVIEW_REQUIRED**; this provenance work makes no release-qualification promotion.
