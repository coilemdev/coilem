# Open and reproduce the frozen outrunner reference

This source-checkout experiment uses a separate frozen-reference `.coilem` envelope. The file embeds the complete audited geometry, source material points, signed winding map, source identities and analysis settings. Loading it does not construct an inner-rotor MotorConfig or apply ordinary motor defaults. Edited fixture data or incompatible identities are rejected explicitly.

The fixed-current benchmark file is [lrk_12s14p.coilem](../../../frontend/src/public/outrunner/lrk_12s14p.coilem). The ordinary example in the UI uses the same frozen geometry with ideal six-step excitation by default. The backend asset remains independently hash-checked. Analysis settings record excitation mode, current units/magnitude/angle/advance, gap target, mesh-policy version, nonlinear tolerance, material-law version, speed, phase currents and angular sample count. Legacy files missing the new excitation fields retain fixed-current benchmark behavior.

## Start the local experiment

Use this experimental worktree, `C:/bench/coilem-outrunner-v051-20261105`, branch **codex/v055-outrunner**. It is rebased onto current main and targets **v0.5.5** for review. See [V055-REVIEW.md](V055-REVIEW.md) for the implemented scope and remaining publication/numerical decisions.

Build the normal UI with `npm run build` first if checking the release boundary. To build the opt-in local UI:

```powershell
Set-Location C:/bench/coilem-outrunner-v051-20261105/frontend
$env:VITE_COILEM_EXPERIMENTAL_OUTRUNNER = '1'
npx vite build --config vite.public.config.ts
```

Then start the source-checkout server in a separate terminal:

```powershell
Set-Location C:/bench/coilem-outrunner-v051-20261105
$env:COILEM_EXPERIMENTAL_OUTRUNNER = '1'
python -m tools.experimental.serve_outrunner
```

Open `http://127.0.0.1:58151`. In **Design file menu → Examples**, choose **LRK outrunner 14p / 12s** for the six-step default. Choose **LRK fixed-current benchmark**, or use **Open design file** with the file above, to reproduce the original FEMM comparison.

The standard **Design → Solve → Results** header and workspace frame are shared with the inrunners. In **Design**, **Rotor arrangement** sits above the SPM/IPM magnet topology. Selecting **Outrunner** opens this frozen SPM fixture; selecting **Inrunner** returns to the current editable inrunner. This does not reinterpret the inrunner dimensions as outer-rotor dimensions.

Both the local UI build flag and source-checkout backend flag are required. Ordinary release builds exclude the fixture/workspace chunks, and ordinary backend launches do not register the experimental routes. No version bump or release publishing is part of this workstream.

## What to review

The geometry preview uses the same exact curve/region IR as the Gmsh solver adapter, rendered through the existing motor canvas and reference 3D renderer. The 2D view uses the common phase palette, pole labels, zoom/pan and component selection. For outer magnets, the labelled air-gap face has an inward-facing normal. The 3D view extrudes the exact source contours, including the bore hole, and supports orbit and part visibility. **Exploded** and its 0–100% slider separate the stator, windings, magnets and rotor; the camera fits the separated assembly. Materials and Winding views expose the fixed source definitions. The rotor-position control moves only the outer body; its preview angle is clockwise, matching inrunners, and is separate from the analysis request.

In Solve, the shared accordion order is **Operating point → Analysis → Accuracy plan → Advanced options**, with one open section at a time. **Ideal six-step (120°)** is the normal RC-style example default: use plateau phase current and optional commutation advance. **Sinusoidal** supports RMS/peak current and a current-angle control. These modes change the commanded currents with rotor position; displayed running angle and torque are CW-positive. They are ideal current excitations, without PWM, switching ripple or voltage limits. **Fixed-current benchmark** preserves explicit A/B/C = 0/4/−4 A, an adjustable equal-and-opposite B/C current, and the original CCW-positive source angle/torque convention. Choose **Single operating point (0°)** (running modes) or **Original operating point only** (benchmark) for a short fresh native solve, or select **Torque** and/or **Back EMF**. Back-EMF always uses a separate zero-current sweep.

Accuracy presets change the actual native mesh, angular grid and nonlinear tolerance together:

| Plan | Unique angles / electrical period | Gap target | Bulk target | Newton tolerance | Zero-angle elements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Preview | 24 | 0.10 mm | 0.50 mm | 1e−5 | 75,866 |
| Standard | 48 | 0.05 mm | 0.25 mm | 1e−5 | 174,508 |
| High accuracy | 96 | 0.025 mm | 0.25 mm | 1e−6 | 425,228 |

Every sweep includes a separately solved endpoint. Each preset automatically selects **Mesh** and clears the old preview while the new mesh prepares. The zero-angle preview and zero-angle solve share the same mesh cache identity. Other angles use actual remeshed geometry. **Custom…** changes the angular grid; Advanced options expose gap/bulk targets and nonlinear tolerance. Older files keep their explicit numerical settings and are labelled Standard or Custom as appropriate. Preview is for iteration; the numerical review remains the basis for qualification.

The run plan and footer show a duration range calibrated from completed local points with matching mesh and tolerance; the fallback is a broad measured-profile estimate. Running jobs show their stage, elapsed time, completed positions, partial torque curve, and remaining-time range based on recent points. Larger grids and finer meshes can take many minutes. A closed/restarted backend marks an unfinished job interrupted; reopening the same design offers **Resume saved analysis**. Completed cases can only be reused after exact request, binary, fixture and raw-evidence checks.

Design has **2D / 3D / Mesh / Materials / Winding** views. Play/pause, reset, preview RPM and a full-turn rotor slider move only the outer body. Solve has the same **Geometry / Mesh / Field solution** view choices as inrunners. Mesh supports region colours, triangle quality, weak elements, edges, and zoom/pan. Its element counts and quality distribution come from the actual native mesh.

The 2D preview in Design and Solve Geometry also has the shared **Phases** and **Tooth poles** toggles. Phases shows the selected excitation's actual current traces and winding intensity. Sinusoidal traces vary smoothly and six-step traces switch sectors as the rotor moves. Fixed benchmark traces remain flat. Tooth poles is a qualitative current-driven MMF display derived from the exact signed winding map, with the correct outward-facing stator convention. It preserves the exact steel/slot/bore contours. Use Field solution for the actual solved magnetic field.

**Field solution** in Solve and Results shows the actual retained nodal Az solution and per-angle mesh, using the common field renderer and a fixed 0–2 T scale with over-range magenta. Play steps through separately solved fields; it does not rotate a single heatmap or interpolate unsolved angles. Playback defaults to **Clockwise**, matching inrunners: running-mode frames advance in their stored order; positive-CCW benchmark frames play in reverse. A direction selector also permits Counterclockwise playback. Actual source angles and A/B/C currents remain inspectable; playback does not change the saved numerical values. Loaded and no-load families have separate timelines. The repeated endpoint is available for scrubbing but skipped during looping playback. Pausing loads the exact numerical frame for element probes and zoom. Legacy completed runs can generate these views from their retained fields without solving again. Image preparation may briefly buffer on first viewing; the browser retains at most six decoded frames, while all numerical evidence stays on disk.

**Design file menu → Save design file (.coilem)** preserves the complete inputs. **Export results and design** in Results downloads the measured result payload with those inputs. A design file starts a new fresh analysis when requested; it does not silently turn stored curves into a new solve. Generic editable outrunner dimensions remain future work; this published reference keeps its exact source geometry and materials.

Experimental runs are stored under the normal user-data root in `experimental/femm-outrunner/`, separate from ordinary motor runs. `COILEM_USER_DATA_ROOT` can select an isolated review directory. Run raw fields are compressed and retained; cancelling stops the owned native process and leaves completed evidence resumable.

Use the [measured-results review](INITIAL-RESULTS.md) for comparison limits and remaining numerical qualifications. UI availability is not a hardware-accuracy or full-qualification claim.
