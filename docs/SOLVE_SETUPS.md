# Saved run setups

Solve's **Run setup** selector restores operating conditions, requested outputs,
accuracy, mesh and advanced solver settings by default, without changing motor
geometry, winding or materials.
The information icon beside **Run setup** explains what the selected setup
captures and how to rename or save another setup. Hover, focus or tap it to read
the tooltip; press **Escape** to dismiss it.

1. Set the operating point and analyses in Solve, then choose the **Save** (disk)
   icon beside the dropdown while **Custom** is selected. Type a name in the
   setup field and choose **Save** again. **Include accuracy and solver settings**
   starts checked. Uncheck it only when you want to reuse an operating point and
   its requested analyses while keeping accuracy and solver choices separate.
2. Use the arrow beside the name to select a setup. An edit to its captured
   settings marks it **Modified** and enables **Save**. Saving replaces that
   setup's values, confirms **Updated setup**, and disables **Save** again.
   Reverting the values also disables **Save**, keeping the same version.
3. Double-click a user setup's name, or focus it and press **F2**, to rename it
   inline. **Enter** or leaving the field saves the name; **Escape** cancels.
4. Choose **Custom**, then **Save**, to create another setup from the current
   values. The **Delete** (trash) icon asks for confirmation and leaves the
   operating settings and earlier run records in place.

User setups are stored locally in this browser for the current design. Reopening
the same original file, or reloading an example, restores its active setup and
the settings it captured. The starter motor and the gallery's SPM 8p/12s example
share one library, and **Reset** restores the starter with its active setup, as
launching the app does. Switching the rotor arrangement to Outrunner and back
returns the previous inrunner with its own library. The default includes the
accuracy plan, mesh and advanced options. Files without
setup metadata are identified by their contents, so a different design with the
same filename keeps its own library.

Settings left at their catalogue default (20 C magnet and winding temperature,
no mechanical loss) stay unset in a setup. Applying a setup therefore never adds
an explicit temperature to a magnet grade without cited temperature data, or to
the LRK reference, which both refuse one.

Save the `.coilem` design file to keep a portable copy of the setups, their active
identity/version and the actual settings. Opening that portable file preserves
its exact settings, including any unsaved changes to the selected setup. Its
setups join this browser's library for the same design; where both hold the
same setup, the newer version is kept, so opening an older copy never removes
setups or versions saved since. This
also works when browser storage is unavailable; a notice explains that the
design file must be saved. Older files start without setups, and earlier app
versions may discard setups when saving a design again.

A setup this version cannot read, for example one saved by a newer coilEM, is
skipped with a notice. The motor and the other setups still open, and browser
storage keeps the unreadable copy beside the library instead of overwriting it.

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
recorded case ID then names that magnet case; the run's speed and current are
the values shown in Solve, as for any edited reference operating point. The
nonlinear iteration cap is visible and editable under Advanced options.

Reference setups describe registered software comparisons, not measured Prius
hardware accuracy. Saving a label does not change qualification status.

## Saved-run provenance

A run stores the submitted setup's ID, version and name alongside the actual
resolved request. Its result displays that recorded name/version. Later profile
updates or renames cannot relabel an earlier run. Modified or Custom conditions
do not claim to be an unchanged saved setup. Saved run projects/packages retain
the setup library snapshot for replay; the request record keeps only the
submitted setup's label. Opening a saved run keeps this browser's current library
for that design and selects the run's setup only while that version still exists.
The snapshot is used when this browser has no library for the design. Setup
metadata in a solve request must be plain JSON with finite numbers, and the
library is limited to 256 KB.

THD availability follows the selected accuracy plan. When accuracy and solver
settings are excluded, the torque-speed map's grid stays separately selectable;
its drive limits and control choice are retained. Setups requesting analyses unavailable
with Elmer require selecting Magneto2D rather than silently dropping outputs.
