# Open and reproduce the frozen outrunner reference

This source-checkout experiment uses a separate frozen-reference `.coilem` envelope. The file embeds the complete audited geometry, source material points, signed winding map, source identities and analysis settings. Loading it does not construct an inner-rotor MotorConfig or apply ordinary motor defaults. Edited fixture data or incompatible identities are rejected explicitly.

The example is [lrk_12s14p.coilem](../../../frontend/src/public/outrunner/lrk_12s14p.coilem). The backend asset remains independently hash-checked. Analysis settings record the gap target, mesh-policy version, nonlinear tolerance, material-law version, speed, phase currents and angular sample count.

## Start the local experiment

Use this experimental worktree, `C:/bench/coilem-outrunner-v051-20261105`.

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
& 'C:/Users/14845/Documents/GitHub/coilem-launch/.venv/Scripts/python.exe' -m tools.experimental.serve_outrunner
```

Open `http://127.0.0.1:58151`. In **Design file menu → Examples**, choose **LRK outrunner 14p / 12s**. Alternatively use **Open design file** to open the example above.

The standard **Design → Solve → Results** header and workspace frame are shared with the inrunners. In **Design**, **Rotor arrangement** sits above the SPM/IPM magnet topology. Selecting **Outrunner** opens this frozen SPM fixture; selecting **Inrunner** returns to the current editable inrunner. This does not reinterpret the inrunner dimensions as outer-rotor dimensions.

Both the local UI build flag and source-checkout backend flag are required. Ordinary release builds exclude the fixture/workspace chunks, and ordinary backend launches do not register the experimental routes. No version bump or release publishing is part of this workstream.

## What to review

The geometry preview uses the same exact curve/region IR as the Gmsh solver adapter, rendered through the existing motor canvas and reference 3D renderer. The 2D view uses the common phase palette, pole labels, zoom/pan and component selection. For outer magnets, the labelled air-gap face has an inward-facing normal. The 3D view extrudes the exact source contours, including the bore hole, and supports orbit and part visibility. Materials and Winding views expose the fixed source definitions. The rotor-position control moves only the outer body; its preview angle is CCW and is separate from the analysis request.

In Solve, the shared accordion order is **Operating point → Analysis → Accuracy plan → Advanced options**, with one open section at a time. The fixture uses explicit fixed phase currents, initially A/B/C = 0/4/−4 A. The conducting-current control keeps B and C equal and opposite. This is a fixed-current angle sweep, rather than a sinusoidal commutated operating point. Choose **Original operating point only** for a short fresh native solve, or select **Torque** and/or **Back EMF**. Back-EMF always runs a separate zero-current sweep. Positive angle and outer-body torque are CCW.

Accuracy presets change the actual native mesh, angular grid and nonlinear tolerance together:

| Plan | Unique angles / electrical period | Gap target | Bulk target | Newton tolerance | Zero-angle elements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Preview | 24 | 0.10 mm | 0.50 mm | 1e−5 | 75,866 |
| Standard | 48 | 0.05 mm | 0.25 mm | 1e−5 | 174,508 |
| High accuracy | 96 | 0.025 mm | 0.25 mm | 1e−6 | 425,228 |

Every sweep includes a separately solved endpoint. Each preset automatically selects **Mesh** and clears the old preview while the new mesh prepares. The zero-angle preview and zero-angle solve share the same mesh cache identity. Other angles use actual remeshed geometry. **Custom…** changes the angular grid; Advanced options expose gap/bulk targets and nonlinear tolerance. Older files keep their explicit numerical settings and are labelled Standard or Custom as appropriate. Preview is for iteration; the numerical review remains the basis for qualification.

The run plan and footer show a duration range calibrated from completed local points with matching mesh and tolerance; the fallback is a broad measured-profile estimate. Running jobs show their stage, elapsed time, completed positions, partial torque curve, and remaining-time range based on recent points. Larger grids and finer meshes can take many minutes. A closed/restarted backend marks an unfinished job interrupted; reopening the same design offers **Resume saved analysis**. Completed cases can only be reused after exact request, binary, fixture and raw-evidence checks.

Design has **2D / 3D / Mesh / Materials / Winding** views. Play/pause, reset, preview RPM and a full-turn rotor slider move only the outer body. Solve has the same **Geometry / Mesh / Field solution** view choices as inrunners. Mesh supports region colours, triangle quality, weak elements, edges, and zoom/pan. Its element counts and quality distribution come from the actual native mesh.

**Field solution** in Solve and Results shows the actual retained nodal Az solution and per-angle mesh, using the common field renderer and a fixed 0–2 T scale with over-range magenta. Play steps through separately solved fields; it does not rotate a single heatmap or interpolate unsolved angles. Loaded and no-load families have separate timelines. The repeated endpoint is available for scrubbing but skipped during looping playback. Pausing loads the exact numerical frame for element probes and zoom. Legacy completed runs can generate these views from their retained fields without solving again. Image preparation may briefly buffer on first viewing; the browser retains at most six decoded frames, while all numerical evidence stays on disk.

**Design file menu → Save design file (.coilem)** preserves the complete inputs. **Export results and design** in Results downloads the measured result payload with those inputs. A design file starts a new fresh analysis when requested; it does not silently turn stored curves into a new solve. Generic editable outrunner dimensions remain future work; this published reference keeps its exact source geometry and materials.

Experimental runs are stored under the normal user-data root in `experimental/femm-outrunner/`, separate from ordinary motor runs. `COILEM_USER_DATA_ROOT` can select an isolated review directory. Run raw fields are compressed and retained; cancelling stops the owned native process and leaves completed evidence resumable.

Use the [measured-results review](INITIAL-RESULTS.md) for comparison limits and remaining numerical qualifications. UI availability is not a hardware-accuracy or full-qualification claim.
