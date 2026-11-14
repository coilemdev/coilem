# Compare saved runs

Compare shows two completed Magneto2D runs. Run A is the baseline; values and
deltas for Run B are read from its saved result. No analysis starts when comparing.

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

Missing historical inputs are shown as **Not recorded**, while an explicit
stored null is **Not set**. No current schema migration or defaults fill these
gaps. Rows with missing data are counted separately from known changed inputs.
Equal records show **No differences in the recorded inputs**; this does not
claim that unrecorded settings were equal or establish solver qualification.

Results appear in a table with a metric per row and columns for Run A, Run B,
absolute delta (B − A) and percentage delta versus A. Percentage-valued metrics
use percentage points (`pp`) for their absolute delta. Missing results remain
unavailable; a zero baseline does not produce an infinite percentage.

The torque and back-EMF overlays draw Run A solid and Run B dashed, including
their legend swatches, so coincident traces remain distinguishable.
Multi-run baselines, further result types, comparison exports and studies are
subsequent Compare 2.0 work.
