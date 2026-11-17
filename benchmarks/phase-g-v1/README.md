# Phase G: independent full-motor loss checks

Phase G is a separately selected, experimental loss benchmark for 0.5.9.
It does not change the registered A–F suite, its FEMM references, or its gates.
Four copied, hashed fixtures cover concentrated inner SPM 8p/12s, flat-IPM
8p/12s FSAE, distributed inner SPM 8p/24s, and single-layer outer SPM 10p/12s.
Each has no-load and one loaded point (20/50/8/15 A peak respectively).
The distributed winding retains its two parallel paths; phase-axis and
turn-sharing contracts are checked independently, not borrowed from the SPM.

All models use full-motor sinusoidal excitation at public gamma zero,
M350-50A/N42, 3000 rpm collection, specified 0.8 mm copper with two strands,
20 °C winding temperature and zero declared mechanical loss. These are explicit
benchmark assumptions, not measured winding or thermal data. Histories are
evaluated independently at 1500/3000 rpm without new magnetostatic solves.

## What is compared

- Stator hysteresis, classical lamination eddy and total iron loss.
- Rotor hysteresis, lamination eddy and total on the three inner fixtures.
- DC phase resistance and copper watts: production geometry/resistance versus
  an independent specified-wire/turn-count/end-arc calculation using FEMM
  winding-block areas and centroids. No production resistance or mean-turn
  length is copied into that independent calculation.
- Known loss subtotal and modelled total where every registered term exists.
  Report each component's share, so small relative rotor errors do not obscure
  dominant copper/stator terms. Efficiency is explicitly not evaluated by this
  field-history suite; it requires a separate matched power/torque check.

**Outrunner rotor loss is unavailable**, by owner decision. Its stator/copper
checks participate; a known subtotal never becomes a complete total or an
efficiency result by substituting zero for missing rotor loss. No new product
outrunner rotor-motion support is included in this tooling change.

The native collector uses fresh Magneto2D solves, the production loss kernel
and fixed material meshes for the inner rotors. It retains stator fields in
static axes and rotor fields in rotor-material axes. The full mechanical-turn
time base is mechanical frequency for both regions; the stator electrical
fundamental occupies its pole-pair harmonic. This is an explicit kernel/history
validation plan, not a claim that the UX's shorter electrical sampling grid or
all public integration/platform paths have been qualified.

FEMM runs in an isolated process against the byte-preserved E or F geometry
adapter, with matched inputs, steel and magnets. Inner fixtures use one fixed
FEMM mesh throughout the full turn, with motion in the periodic air gap.
Outrunner stator queries remain at fixed physical points through the existing
Phase F remeshing path. A separate direct DFT computes reference losses; it
does not import the production FFT/loss kernel. Neither solver's mass is
renormalized to match the other.

## Gates and limitations

**Owner decision, 2026-11-17:** the distributed no-load native history failed
96→192 angular refinement for rotor loss, then changed only 0.28% from 192→384
at 3000 rpm. Keep the bounded 384-pose pilot and retain the failed gate, without
adding a 768-pose campaign. `--allow-angular-failure` permits that distributed
fixture's diagnostic comparison only when closure and the final 192→384 step
pass. The original two-step gate stays failed; component agreement is reported
separately and cannot turn it into a numerical validation pass. Other fixtures,
failed final refinements, closure failures and cross-solver disagreements have
no gate waiver. Model status and qualification remain experimental/incomplete.

Each history contains 384 half-open mechanical poses plus a fresh endpoint.
Both 96→192→384 angular steps use max(5% of finer, 0.001 W), separately for
hysteresis, eddy and total. Endpoint maximum/RMS limits are 1e-6/1e-7 T.
Native/FEMM component agreement uses max(10% FEMM, 0.001 W); independent
resistance/loaded DC copper uses 1%. Zero-current cases still check resistance.
Use the existing working meshes; this suite does not claim a new independent
spatial convergence study at every point. By default, failed checks stop with all
completed checkpoints retained. `--continue-independent-cases` can finish the
other registered conditions, recording the failed history and withholding its
FEMM comparison when native closure or angular gates are inadmissible. It does
not broaden the distributed pilot exception. Reference-history or comparison
failures also remain failed when independent cases continue; unexpected worker,
source or integrity errors still stop the campaign. No failed check is converted
to a pass or repaired by fitting.

The material law and dependent totals stay experimental. Magnet/component
eddy currents, AC winding loss, inverter loss, separate excess loss, minor
loops, manufacturing corrections and thermal prediction are not included.
Matching FEMM with the same empirical coefficients is numerical verification,
not measured motor-efficiency validation. Remaining qualification is #330;
sector work is #319 and is outside this full-motor suite.

## Run on Windows

An optional `reuse-femm.json` in the external campaign directory can map a case
ID to `history` and `source_checkout` absolute directory paths. This selects
read-only extraction of a previously audited, complete fixed-mesh FEMM history.
The extractor verifies geometry/winding/materials, current/angle, mesh controls,
the frozen producer sources, every original checkpoint and answer hash, and
every saved solution's current and mesh audits. Only specified wire data may
differ: it does not change the homogenized ampere-turn source; copper is
recomputed independently for the newly declared conductor.

Unsmoothed B is independently derived from each answer's linear triangular
A_z solution and checked against its retained FEMM rotor CSV to 1e-9 T. The
original histories stay untouched and keep their source identities. New reports
link the original protocol/answer hashes, record the extraction implementation,
and explicitly report **zero new FEMM field solves** for reused cases. This
allows the new stator comparison without re-solving an identical magnetic case.
Nonmatching or incomplete histories are rejected. Cases without a reuse mapping
use fresh Windows FEMM solves as described above.

Use a clean committed checkout, a source-matched Magneto2D binary and the pinned
FEMM Python environment documented in `tools/femm_reference/README.md`.
Output must be outside the checkout. The coordinator runs **all selected native
conditions first**, then starts the slower FEMM work with at most two workers.
It waits for existing FEMM sessions rather than adding to an active campaign.

`--parallel-femm-cases` assigns one worker to each independent fixture/load
condition, up to the same global `--femm-workers` limit. For example, flat-IPM
and distributed SPM can collect concurrently with two total FEMM instances.
Each case bootstraps its own mesh, then one worker resumes all missing poses;
previously completed even/odd shards are verified and retained. Scheduling
changes do not change the registered magnetic inputs or source identities.
An unexpected failure cancels the other owned worker. Numerical gates and the
rules for withholding inadmissible native cases remain unchanged.

```powershell
python -m tools.phase_g_loss run --out ../phase-g-run --binary <magneto2d.exe> --femm-python <pinned-python.exe> --wait-for-femm
```

Use `native` or `femm` instead of `run` for a staged campaign; repeat the same
command and output directory to resume. `--case` can be repeated to register a
bounded selection. Changing field producers, binary, fixtures, selection or
controls requires a new registration. Orchestration/readers may advance only
when every hashed native producer/physics file still matches; the actual field
candidate is retained and the newer tooling commit is recorded separately.
Analysis replay verifies the raw inputs and numerical result, preserving the
original canonical receipt and writing a separate replay record. Completed
reference extraction is verified and reused without retagging its producer.
Case checkpoints retain source/input/mesh identity,
excitation and raw-field hashes; writes are atomic. Each FEMM worker owns and
closes only its own COM session. Monitor `run-state.json`, per-case worker logs,
`analysis.json` and `reports/*.json`. Raw fields/meshes stay outside git.
