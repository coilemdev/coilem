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

Choose **Original operating point** for a short fresh native solve. **Torque and back-EMF curves** runs two independent sweeps, with loaded currents from the design and zero current for back-EMF. Positive angle and outer-body torque are CCW. Back-EMF uses the explicitly displayed induced-voltage sign convention and normalization speed.

The initial file uses 48 unique angles plus a separately solved endpoint. Larger grids and finer meshes can take many minutes. Progress and partial curves are retained in **Solve**, with a separate run-plan rail. Completed results appear under the usual **Results** stage with torque, flux-linkage and back-EMF plots. A closed/restarted backend marks an unfinished job interrupted; reopening the same design offers **Resume saved analysis**. Completed cases can only be reused after exact request, binary, fixture and raw-evidence checks.

**Design file menu → Save design file (.coilem)** preserves the complete inputs. **Export results and design** in Results downloads the measured result payload with those inputs. A design file starts a new fresh analysis when requested; it does not silently turn stored curves into a new solve. The workspace currently shows geometry and torque/linkage/EMF results; field playback and generic editable outrunner dimensions remain future work.

Experimental runs are stored under the normal user-data root in `experimental/femm-outrunner/`, separate from ordinary motor runs. `COILEM_USER_DATA_ROOT` can select an isolated review directory. Run raw fields are compressed and retained; cancelling stops the owned native process and leaves completed evidence resumable.

Use the [measured-results review](INITIAL-RESULTS.md) for comparison limits and remaining numerical qualifications. UI availability is not a hardware-accuracy or full-qualification claim.
