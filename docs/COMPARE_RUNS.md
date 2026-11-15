# Compare saved runs

Compare shows **two to six** completed Magneto2D runs. Start with the usual
pair, then choose **+ Add run** for up to four more. Duplicate selections are
disabled. Use **Pin as baseline** on any selected run: it moves to the first
table column and every candidate's delta is calculated against it. The baseline
stays selected when candidates are added, changed or removed; its Remove button
is disabled. Run letters, colors and line patterns stay attached to their slots
when pinning or removing another run. No analysis starts when comparing.

If a selected run fails to load, its selector shows the error and a Retry button.
Only selected compact comparison records are fetched, with in-flight and completed
requests reused. Removing a run during loading cannot change the selection later.
Deleting the pinned run from local storage leaves its choice empty so a replacement
must be selected explicitly.
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
mesh (with the solved sector, such as `1/2 sector`, for a sector solve), rotor
positions (the loaded sweep and the cogging sweep per cogging period), torque
extraction, excitation, saved setup and completion time. Runs on different
angle grids differ in ripple and cogging harmonics for that reason alone. These
context rows remain visible even when they match; the changed-input count only
counts distinct input paths with a known change from the baseline. A path may
also be marked incomplete if another selected run did not record it.
Saved-run selectors show the design and recorded setup name, with timestamps
in local time as MM/DD/YY HH:mm:ss (24-hour time). Older runs without a recorded
setup label say **Setup not recorded**. Listing these labels does not load results.

Missing historical inputs are shown as **Not recorded**, while an explicit
stored null is **Not set**. No current schema migration or defaults fill these
gaps. Rows with missing data are counted separately from known changed inputs.
Equal records show **No differences in the recorded inputs**; this does not
claim that unrecorded settings were equal or establish solver qualification.

Results appear in a table with a metric per row. Two-run comparisons retain
separate value, absolute-delta and percentage-delta columns. With three to six
runs, each candidate column shows its value and the absolute/percentage change
from the pinned baseline directly below. Input details, results, losses and timing
all use the same baseline-first column order. Tables scroll on narrow screens;
row names remain visible, and the baseline value also stays visible on wide screens. Percentage-valued metrics
use percentage points (`pp`) for their absolute delta. Missing results remain
unavailable; a zero baseline does not produce an infinite percentage.

Ke uses the single-run Results convention: V/krpm, line-to-line rms.
**Inductance & d/q** compares apparent Ld/Lq, current angle, id/iq,
λd/λq/λpm and d/q torque. Currents consistently use peak amperes, and flux
linkages use mWb. Recorded flux and inductance statuses retain their own
reasons. Missing records, unavailable results and open-circuit quantities stay
distinct. Component and inductance deltas require the same recorded d-axis
reference and supported conventions.

The torque, back-EMF and cogging overlays include every selected run. Run A is
solid and B–F have distinct dash patterns, also shown in their legend swatches.
Pinning another baseline preserves those identities and styles.
Each legend item toggles independently. Hiding every curve shows an empty-chart
message and keeps the legend available so any curve can be turned back on.
Cogging uses each run's recorded electrical angles and shows each recorded angle range.
It does not stretch different periods onto the same span or interpolate missing
samples; the readout delta is available only at angles solved by the candidate and pinned baseline.
A cogging overlay is available if any selected run contains valid cogging samples.

The **Torque–speed** tab overlays saved peak or continuous envelopes on a common
rpm axis, with Torque and Power views and independent run toggles. Its table
compares base/max speed, peak power, drive limits, resistance and winding
temperature with the pinned baseline. Readouts interpolate within each recorded
curve and never extrapolate. Incomplete maps, unavailable outputs and runs
without a map are labelled separately. This view does not compute a drive
envelope or start a map solve; each run keeps its recorded status and limits.

The **Fields** tab loads numerical pictures only when opened. It shows two to
six field maps in baseline-first order, using one fixed 0–2.0 T color scale
(above 2.0 T is magenta). Each motor fits its own panel, so picture sizes do not
compare dimensions. Choose Resultant or PM only, and either each run's stored
snapshot (with its own angle shown) or an exact recorded electrical angle.
Missing angles stay empty; the view does not choose a nearest frame or wrap
different periods. Older runs whose playback was removed can still show their
retained inline snapshot. Loading, errors and retry appear per run. Loaded
frames are cached with a bounded size, requests for superseded positions are
cancelled, and no field solve is started.

**Losses & efficiency**, below the waveform overlays, compares efficiency,
input and shaft power, shaft torque, copper loss (stack and end turns), iron
loss (hysteresis and eddy current), mechanical loss and recorded totals.
Absolute efficiency deltas use percentage points. Recorded output statuses and
their reasons remain available beside values. Missing analysis records stay
**Not recorded**; unavailable outputs are not replaced by zero. Full loss totals
and known subtotals use separate rows, and partial shaft outputs exclude iron
loss and are compared only with other partial outputs. If no selected run has loss
data, the section explains how to enable it for a new analysis.
Selecting **Losses & efficiency** requests a full 360° electrical sweep for
future analyses. The selected accuracy plan and its harmonic analysis are
preserved; existing full-cycle plans keep their own grid, and a shortened plan
is submitted using the existing full-cycle grid. Archived inputs and results
retain their original settings.

**Solve time breakdown**, last after losses, compares the solver time (the Solver time on
Results, without playback images and saving), meshing, field solve and
packaging with absolute and percentage deltas. These are the recorded elapsed
partitions, separate from combined worker time. Workload rows compare mesh
elements, rotor positions, generated/rotated meshes, field solves and frames
when recorded. Missing historical timings and counts remain **Not recorded**;
zero counts remain zero and nonzero changes from zero have no percentage delta.
**Export CSV** downloads the selected two to six runs, with the pinned baseline
first and each run's letter unchanged. It is available in Results and Previous
runs once all selected records are loaded. Loading, failed or incomplete
selections disable export. The download uses these stored records, independently
of the open design and visible plot; it starts no solve and loads no field meshes.

The UTF-8 CSV (`coilem.compare.csv.v1`) has one fixed header across labelled
sections: run/setup identity and provenance, differing recorded inputs, scalar
results, d/q, losses, timing, both envelope limits and their drive settings, field
availability, and torque/back-EMF/cogging/envelope samples. Run value columns are
followed by absolute and percentage changes from the baseline. `Unit` and
`Delta unit` distinguish percentage values from percentage-point changes.
`Record=value` rows hold the values; companion records hold availability, status,
reason, partial-loss basis, comparison notes and original sample indices. Filter
the Record column to `value` for a compact spreadsheet view.

Numbers use full precision and decimal points rather than the UI's display
rounding. The same unit conversions and comparability rules apply: mismatched
d/q references and full/partial shaft outputs have no delta, and a nonzero
change from a zero baseline has no percentage. Missing values remain labelled,
never zero-filled. Raw samples align only at identical recorded coordinates;
different grids are not interpolated or wrapped. Repeated coordinates retain
their occurrence and each run's original index. Cogging mechanical angles are
included where recorded.

The file has a UTF-8 BOM for scientific symbols, CRLF records and quoted text
that preserves commas, quotes and newlines. Text that spreadsheets might treat
as a formula is prefixed with an apostrophe; negative numeric readings remain
numbers. Stored results and generated single-run reports are unchanged.

PDF comparison reports and API-backed studies are subsequent Compare 2.0 work.
