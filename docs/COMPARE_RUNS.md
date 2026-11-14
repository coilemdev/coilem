# Compare saved runs

Compare shows two completed Magneto2D runs. Run A is the baseline; values and
deltas for Run B are read from its saved result. No analysis starts when comparing.
Compare shows **Loading saved runs…** while listing saved analyses, then
**Preparing comparison…** while loading selected results. The insufficient-runs
message appears only after the run list has finished loading.

From Results, **Compare with previous run** chooses the most recent earlier
completed Magneto2D run in the same saved project as Run A, with the result you
opened as Run B. Selection uses recorded completion times. Failed, running,
cancelled, newer and other-project runs are excluded. If there is no earlier
run or the current result was removed from storage, an explanation is shown;
you can choose two runs manually. Unsaved and Elmer results cannot use this shortcut.

**What changed?** lists differing geometry, winding, materials, operating point,
accuracy/solver settings, requested analyses and saved setup identity/version.
The table reads the integrity-checked resolved request and recorded setup label
from each run, independently of the current open design or profile library.
Stored profile metadata from the saved-setups feature is supported when present.
The same table includes a Run details group with the design, solver, actual
mesh, torque extraction, excitation, saved setup and completion time. These
context rows remain visible even when they match; the changed-input count only
counts input differences.
Saved-run selectors show the design and recorded setup name, with timestamps
in local time as MM/DD/YY HH:mm:ss (24-hour time). Older runs without a recorded
setup label say **Setup not recorded**. Listing these labels does not load results.

Missing historical inputs are shown as **Not recorded**, while an explicit
stored null is **Not set**. No current schema migration or defaults fill these
gaps. Rows with missing data are counted separately from known changed inputs.
Equal records show **No differences in the recorded inputs**; this does not
claim that unrecorded settings were equal or establish solver qualification.

Results appear in a table with a metric per row and columns for Run A, Run B,
absolute delta (B − A) and percentage delta versus A. Percentage-valued metrics
use percentage points (`pp`) for their absolute delta. Missing results remain
unavailable; a zero baseline does not produce an infinite percentage.

The torque, back-EMF and cogging overlays draw Run A solid and Run B dashed, including
their legend swatches, so coincident traces remain distinguishable.
Each legend item toggles independently. Hiding every curve shows an empty-chart
message and keeps the legend available so any curve can be turned back on.
Cogging uses each run's recorded electrical angles and shows both angle ranges.
It does not stretch different periods onto the same span or interpolate missing
samples; the readout delta is available only at angles solved by both runs.
A cogging overlay is available if either run contains valid cogging samples.

**Losses & efficiency**, below the waveform overlays, compares efficiency,
input and shaft power, shaft torque, copper loss (stack and end turns), iron
loss (hysteresis and eddy current), mechanical loss and recorded totals.
Absolute efficiency deltas use percentage points. Recorded output statuses and
their reasons remain available beside values. Missing analysis records stay
**Not recorded**; unavailable outputs are not replaced by zero. Full loss totals
and known subtotals use separate rows, and partial shaft outputs exclude iron
loss and are compared only with other partial outputs. If neither run has loss
data, the section explains how to enable it for a new analysis.

**Solve time breakdown**, last after losses, compares total elapsed time, meshing, field solve and
packaging with absolute and percentage deltas. These are the recorded elapsed
partitions, separate from combined worker time. Workload rows compare mesh
elements, rotor positions, generated/rotated meshes, field solves and frames
when recorded. Missing historical timings and counts remain **Not recorded**;
zero counts remain zero and nonzero changes from zero have no percentage delta.
Multi-run baselines, further result types, comparison exports and studies are
subsequent Compare 2.0 work.
