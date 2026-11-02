# Protocol 1.6 reference review status

Status: **REVIEW_REQUIRED**. This document inventories completed checks and
open scientific review; it is not an independent approval of the producer.
The measured records, reference manifest and registered gates are unchanged.

| Completed check | Evidence | Result |
| --- | --- | --- |
| All 46 supported requests at one sealed producer identity | [manifest](reference-bundle/manifest.json), [publication](publication.json) | Complete; before/after identity checks retained in the local capsule |
| All 54 registered native physics sources match candidate `88aae101` | [native manifest](native/run_manifest.json) | Match |
| Original native request/result hashes and frozen record hashes | [integrity check](final-integrity-check.json), [publication](publication.json) | PASS; the copied artifact hashes are unchanged |
| All 29 legacy reference cases reproduce the retained v3 numerical data | [reproduction audit](legacy-reference-reproduction-check.json) | Exact checked torque, EMF, flux, waveforms and mesh fields |
| All 172 retained adapter/material/runtime files match the prepared seal | [source audit](retained-adapter-source-audit.json), [archive provenance](../reference-adapters/windows-femm42-v3-20261102/provenance.json) | Match |
| Twelve raw-waveform d/q torque self-checks | [self-checks](reference-dq-self-checks.json) | All PASS; maximum 1.14247% error, 2% green limit |
| Baseline V-shape comparison with a separately refined reference | [diagnostic](vshape-convergence-control.json), [saved-model audit](vshape-control-model-audit.json) | Six comparison gates PASS; all 96 saved refined models audited |

Review still needs to accept the declared measurement roles within the intended
qualification scope. Legacy cases use retained v3 density sources and slot-flux
reduction; the shoed and loaded d/q cases use explicit series phase circuits.
The [same-input pairs](reference-bundle/source-method-review.json) retain both
methods: circuit-versus-density mean-torque shifts are approximately -0.3974%
for SPM and -0.1911% for flat IPM. Their integrated source differences and flux
extraction policies must be considered, rather than changing a reference or a
gate to obtain a preferred verdict.

The V-shape review must retain the mixed change from v0.4.0 and the differing
mesh recipes of the two reference diagnostics. The single refinement control
does not establish spatial convergence. V-shape can remain experimental without
turning an unresolved discrepancy into a claim of validated accuracy.

When review is complete, record the reviewer, scope and accepted limitations in
a new review artifact. Any reviewed bundle must have a new identity and its
comparison must be reproduced from the retained native fields. Preserve this
unreviewed manifest and its original hashes. This publication does not change
the active bundle, platform records, application qualification or release gate.
