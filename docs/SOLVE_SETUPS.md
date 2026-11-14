# Saved run setups

Solve's **Run setup** selector restores an operating point and its requested
outputs without changing motor geometry, winding or materials.
The information icon beside **Run setup** explains what the selected setup
captures and how to rename or save another setup. Hover, focus or tap it to read
the tooltip; press **Escape** to dismiss it.

1. Set the operating point and analyses in Solve, then choose the **Save** (disk)
   icon beside the dropdown while **Custom** is selected. Type a name in the
   setup field and choose **Save**
   again. Leave **Include accuracy and solver settings** unchecked to keep
   numerical quality separately selectable, or check it to capture those choices.
2. Use the arrow beside the name to select a setup. An edit to its captured
   settings marks it **Modified**. **Save** replaces that setup's saved values.
   Saving unchanged settings keeps the same version.
3. Double-click a user setup's name, or focus it and press **F2**, to rename it
   inline. **Enter** or leaving the field saves the name; **Escape** cancels.
4. Choose **Custom**, then **Save**, to create another setup from the current
   values. The **Delete** (trash) icon asks for confirmation and leaves the
   operating settings and earlier run records in place.

User setups are stored locally in this browser for the current design. Reopening
the same original file, or reloading an example, restores its active setup and
the settings it captured. Check **Include accuracy and solver settings** when
saving to restore the accuracy plan, mesh and advanced options too. Files without
setup metadata are identified by their contents, so a different design with the
same filename keeps its own library.

Save the `.coilem` design file to keep a portable copy of the setups, their active
identity/version and the actual settings. Opening that portable file preserves
its exact settings, including any unsaved changes to the selected setup. This
also works when browser storage is unavailable; a notice explains that the
design file must be saved. Older files start without setups, and earlier app
versions may discard setups when saving a design again.

## Reference setups

The exact Pyleecan Prius model offers two immutable built-ins:

| Setup | Speed | Phase current | Magnets | Current angle |
| --- | --- | --- | --- | --- |
| No-load BEMF reference | 1,000 rpm | 0 A peak | 20 C | Phi0 = 140 degrees |
| Loaded torque reference | 2,000 rpm | 250 A peak | 60 C | Phi0 = 140 degrees |

These use Pyleecan's d-axis convention. They include the numerical settings
from the shipped, versioned reference designs. They are only offered for a
compatible physical model and cannot overwrite its geometry or materials.
Changing their values marks the active setup Modified; **Save** creates
a personal copy after asking for a name. Built-ins cannot be updated, renamed or deleted.

The Prius magnet-temperature control selects the supported 20 C or 60 C
reference material case while preserving the other operating settings. The
nonlinear iteration cap is visible and editable under Advanced options.

Reference setups describe registered software comparisons, not measured Prius
hardware accuracy. Saving a label does not change qualification status.

## Saved-run provenance

A run stores the submitted setup's ID, version and name alongside the actual
resolved request. Its result displays that recorded name/version. Later profile
updates or renames cannot relabel an earlier run. Modified or Custom conditions
do not claim to be an unchanged saved setup. Saved run projects/packages retain
the setup library snapshot for replay.

THD availability follows the selected accuracy plan. The torque-speed map's
grid also stays separately selectable for ordinary operating setups; its drive
limits and control choice are retained. Setups requesting analyses unavailable
with Elmer require selecting Magneto2D rather than silently dropping outputs.
