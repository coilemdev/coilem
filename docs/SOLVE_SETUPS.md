# Saved run setups

Solve's **Run setup** selector restores an operating point and its requested
outputs without changing motor geometry, winding or materials.

1. Set the operating point and analyses in Solve, then choose **Save setup…**.
2. Give it a name. Leave **Include accuracy and solver settings** unchecked
   to keep mesh, sweep resolution and solver separately selectable. Check it
   when the setup should also restore those numerical choices.
3. Select a saved setup to apply its settings together. Review the existing
   controls before running. An edit marks the selected setup **Modified**.
4. Use **Update setup**, **Rename setup**, or **Delete setup** to manage it.
   **Save setup…** while one is selected creates a separate named copy.

User setups are stored locally in this browser for the current design. Save
the `.coilem` design file to keep a portable copy of the setups, their active
identity/version and the actual settings. This also works when browser storage
is unavailable; a notice explains that the design file must be saved. Older
files open without setups, and earlier app versions may discard setups when
saving a design again.

## Reference setups

The exact Pyleecan Prius model offers two immutable built-ins:

| Setup | Speed | Phase current | Magnets | Current angle |
| --- | --- | --- | --- | --- |
| No-load BEMF reference | 1,000 rpm | 0 A peak | 20 C | Phi0 = 140 degrees |
| Loaded torque reference | 2,000 rpm | 250 A peak | 60 C | Phi0 = 140 degrees |

These use Pyleecan's d-axis convention. They include the numerical settings
from the shipped, versioned reference designs. They are only offered for a
compatible physical model and cannot overwrite its geometry or materials.
Changing their values marks the active setup Modified; **Save a copy…** creates
a user setup. Built-ins cannot be updated, renamed or deleted.

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
