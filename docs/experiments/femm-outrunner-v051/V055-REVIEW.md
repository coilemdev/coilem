# Outrunner support — v0.5.5 review scope

Target release: **v0.5.5**. Status: local experimental implementation for developer review. Intended branch: `codex/v055-outrunner`, based on current public `main`. The directory name records the original v0.5.1 validation baseline. Product and native-solver version numbers have not been bumped.

## User-visible behavior

- Inrunner / Outrunner selection above SPM / IPM, with the normal Design → Solve → Results workflow.
- Exact published LRK 12-slot / 14-pole reference geometry, source steel curves, magnet definitions and signed winding map. The geometry remains a frozen reference, rather than a generic editable outrunner generator.
- The ordinary LRK example defaults to **Ideal six-step (120°)** at 4 A plateau. This is a basic ESC-style current-command baseline for the RC use case; rotor topology does not require a particular drive method.
- **Sinusoidal** supports RMS or peak phase-current units and a current-angle control. **Six-step** exposes conducting current and commutation advance. These are ideal current excitations; PWM, voltage limits, switching ripple and controller dynamics are not simulated.
- **Fixed-current benchmark** retains the original 0 / +4 / −4 A sweep. A separate **LRK fixed-current benchmark** example and the original `lrk_12s14p.coilem` explicitly preserve this mode. Legacy files/requests missing operating-mode fields normalize to fixed current, never to the new running default.
- Shared Phases / Tooth poles previews, clockwise animation, actual native mesh/quality views and actual per-angle solved-field playback. The 3D view includes exploded toggle/slider, part visibility and camera framing for the separated assembly.
- Portable files save the selected excitation, current units, magnitude, angle/advance, speed and numerical controls. Resume checks retain exact request, binary, fixture and raw-field identities.

## Conventions reviewers should check

The frozen source remains CCW-positive. Fixed-current benchmark rows and curves retain their original signs and positive-angle grid. Running modes solve negative source angles so that samples advance clockwise; displayed angle, torque and EMF use that clockwise coordinate. Retained raw case rows still report the actual source angle, A/B/C circuit currents and outer-body CCW torque. Playback reads the actual frame ordering for either convention and skips the repeated endpoint.

The source winding axes are derived from geometry: slot centres are `15 + 30*k` mechanical degrees and each source side has its signed 15 turns. Their order-7 winding phasors have arguments A=−90°, B=150°, C=30°; the gap-facing rotor north axis is at 0°. Adapting the shared public excitation profile therefore uses a 90° electrical axis offset and source channel order A/C/B. These conventions are fixed from geometry, without fitting torque or EMF. The benchmark path retains its direct source A/B/C currents. Physical winding connection and a hardware terminal Kv are unspecified by the published model.

## Verification and limits

- The measured fixed-current comparison remains documented in [INITIAL-RESULTS.md](INITIAL-RESULTS.md): source torque error 0.033%, loaded torque RMS difference / FEMM peak 0.471%, refined back-EMF fundamental amplitude difference 0.340–0.361%. Small-torque/reference spatial convergence and steel interpolation-law parity remain open. This does not claim full numerical or hardware qualification.
- Seven excitation tests cover geometry-derived axes, all six sectors/boundaries, advance, current-angle shift, RMS/peak conversion, zero-current isolation, legacy preservation, curve/EMF signs and the existing inrunner golden vectors. Frontend preview matches 39 backend vectors.
- Actual independent native Preview solves at 0°, 60° and 120° CW electrical verify changing source currents and positive clockwise motoring torque. Six-step 4 A plateau: 55.364 / 55.437 / 55.393 mN·m. Sinusoidal 4 A peak: 47.963 / 48.037 / 47.993 mN·m. These selected points verify the adapters; a complete numerical commutated-waveform qualification is not claimed.
- Real-browser checks cover defaults and all choices, save/reopen, fresh solves in both running modes, fixed benchmark preservation, source-point reproduction, 2D/3D selection, actual mesh/field views and exploded assembly controls. The source fixed-current Standard point still reproduces −55.4093 mN·m.
- Windows progress persistence has coordinated readers/writers, unique atomic files, bounded sharing retries and active-job cleanup. A real Windows sharing-handle test and recovery of both interrupted user runs passed; prior raw hashes remain intact.

Raw local receipts live under `output/femm-outrunner-review/` (untracked), particularly `operating-modes-native-check-v2`, `operating-modes-browser`, `ui-workflow-smoke`, `ui-parity-smoke`, and `lock-fix-recovery`. Checked-in tests and this review scope accompany the implementation; generated runs are not source changes.

## Release decision

The UI build flag and source-checkout backend flag still gate the experimental fixture. Ordinary release bundles exclude the fixture/workspace chunks, and ordinary backend launches omit its routes. Before v0.5.5 publication, developer review must decide the distribution/attribution of the source fixture, experimental availability policy, and which open numerical gates are required. No PR, push, release publication or default release enablement has occurred as part of this local work.
