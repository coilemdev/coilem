/**
 * The Layout view: the winding as a linear slot strip rather than a cross-section.
 *
 * The annulus answers spatial questions — is the phase distribution symmetric,
 * where does a belt sit relative to a magnet. It cannot answer sequential ones:
 * on a ring, slot 12 -> 1 wraps behind the shaft and a coil span is a chord you
 * have to trace. Unrolled, slot order and coil spans are just things you can
 * count. Parallel paths in particular had no representation anywhere in the app —
 * the cross-section is pixel-identical for 1, 2 or 4 — which is what this view
 * exists to show.
 */
import type { GeometryPreview, MotorConfig, PublicWindingCoil } from './model';
import { PUBLIC_PHASE_COLORS, type PublicPhaseId } from './motorPalette';

const PHASES: PublicPhaseId[] = ['A', 'B', 'C'];
/** Column pitch. Wide enough for a phase letter and a direction glyph. */
const SLOT_PX = 46;
const ARC_HEIGHT = 44;

/**
 * Coils split into `pathCount` branches, evenly, in slot order.
 *
 * The solver models parallel paths only as a divisor on branch current — it has no
 * branch topology — so this grouping is the conventional reading rather than
 * something read back from the model, and the view says so. When the count does not
 * divide the coils the remainder is left over, which is the case the caller warns
 * about.
 */
function branchesForPhase(
  coils: PublicWindingCoil[],
  pathCount: number,
): PublicWindingCoil[][] {
  const ordered = [...coils].sort((a, b) => a.slot_in - b.slot_in);
  const paths = Math.max(1, Math.floor(pathCount));
  if (paths <= 1 || ordered.length === 0) return [ordered];
  const per = Math.floor(ordered.length / paths);
  if (per < 1) return ordered.map((coil) => [coil]);
  const groups: PublicWindingCoil[][] = [];
  for (let index = 0; index < paths; index += 1) {
    groups.push(ordered.slice(index * per, (index + 1) * per));
  }
  const remainder = ordered.slice(paths * per);
  if (remainder.length) groups.push(remainder);
  return groups;
}

/** Wiring-diagram geometry, in px. */
const COIL_W = 52;
const COIL_H = 20;
const JUMPER = 18;
const BRANCH_ROW = 32;
/** Room for the "path n" gutter, so the label cannot sit on the terminal bus. */
const LABEL_GUTTER = 46;
/** Lead length either side of the chain, long enough to carry a current label. */
const LEAD = 34;
/** Band above the rows for the incoming current and the neutral marker. */
const TOP_BAND = 15;

/**
 * One phase drawn as wiring rather than as a list of groups.
 *
 * A branch is a series chain between two junctions — the phase terminal and the
 * star point — and that is the whole difference between 1, 2 and 4 paths: the slots
 * hold exactly the same conductors either way, only the joins move. Listing which
 * coils group together read as sorting; drawing terminal → coil → jumper → coil →
 * neutral shows that a=1 is one long chain and a=4 is four short ones in parallel,
 * and labelling the leads shows the phase current dividing as it goes.
 */
function PhaseWiring({ phase, branches, pathCount, slotLabel, phaseCurrentA, convention }: {
  phase: PublicPhaseId;
  branches: PublicWindingCoil[][];
  pathCount: number;
  slotLabel: (slotIndex: number) => number;
  phaseCurrentA: number | null;
  convention: 'rms' | 'peak' | 'plateau';
}) {
  const colour = PUBLIC_PHASE_COLORS[phase];
  const longest = branches.reduce((max, branch) => Math.max(max, branch.length), 0);
  const chainWidth = longest * COIL_W + Math.max(0, longest - 1) * JUMPER;
  const terminalX = LABEL_GUTTER;
  const chainX = terminalX + LEAD;
  const neutralX = chainX + chainWidth + LEAD;
  const width = neutralX + 16;
  const height = TOP_BAND + Math.max(1, branches.length) * BRANCH_ROW;
  const rowY = (index: number) => TOP_BAND + index * BRANCH_ROW + BRANCH_ROW / 2;
  const firstY = rowY(0);
  const lastY = rowY(branches.length - 1);

  // What the solver actually does with the path count: divide the branch current.
  // Only true while the branches match, which is why the uneven case says so
  // instead of printing a number the machine would not deliver.
  const evenSplit = branches.length === pathCount;
  const branchCurrentA = phaseCurrentA !== null ? phaseCurrentA / pathCount : null;
  const amps = (value: number) => `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} A`;

  return (
    <svg
      className="wl-wiring"
      width={width}
      height={height}
      role="img"
      aria-label={`Phase ${phase}: ${branches.length} branch${branches.length === 1 ? '' : 'es'} between terminal and neutral, ${branches.map((b) => `${b.length} coil${b.length === 1 ? '' : 's'}`).join(', ')}${branchCurrentA !== null && evenSplit ? `, ${amps(branchCurrentA)} per branch` : ''}`}
    >
      {/* Terminal and neutral buses: the two junctions every branch shares. */}
      {branches.length > 1 ? (
        <>
          <line x1={terminalX} y1={firstY} x2={terminalX} y2={lastY} stroke={colour} strokeWidth={1.6} />
          <line x1={neutralX} y1={firstY} x2={neutralX} y2={lastY} stroke={colour} strokeWidth={1.6} />
        </>
      ) : null}

      {/* Phase current in, at the terminal. The phase tag beside the diagram already
          names the phase, so the terminal carries the current rather than a letter
          that repeated it and collided with the path label. */}
      {phaseCurrentA !== null ? (
        <text x={terminalX} y={TOP_BAND - 4} className="wl-wiring-current is-total" textAnchor="middle">
          {amps(phaseCurrentA)} {convention}
        </text>
      ) : null}
      <text x={neutralX} y={TOP_BAND - 4} className="wl-wiring-node" textAnchor="middle">N</text>

      {branches.map((branch, branchIndex) => {
        const y = rowY(branchIndex);
        // A group beyond the requested count is the remainder of an uneven split.
        const leftover = branches.length > pathCount && branchIndex === branches.length - 1;
        const chainEnd = chainX + branch.length * COIL_W + Math.max(0, branch.length - 1) * JUMPER;
        const leadStroke = leftover ? '#f87171' : colour;
        return (
          <g key={branchIndex}>
            <line x1={terminalX} y1={y} x2={chainX} y2={y} stroke={leadStroke} strokeWidth={1.6} strokeDasharray={leftover ? '3 2' : undefined} />
            <line x1={chainEnd} y1={y} x2={neutralX} y2={y} stroke={leadStroke} strokeWidth={1.6} strokeDasharray={leftover ? '3 2' : undefined} />

            {/* Branch current on the incoming lead. */}
            {branchCurrentA !== null ? (
              <text
                x={(terminalX + chainX) / 2}
                y={y - 5}
                className={`wl-wiring-current${leftover || !evenSplit ? ' is-uneven' : ''}`}
                textAnchor="middle"
              >
                {evenSplit ? amps(branchCurrentA) : '?'}
              </text>
            ) : null}

            {branch.map((coil, coilIndex) => {
              const x = chainX + coilIndex * (COIL_W + JUMPER);
              return (
                <g key={coil.coil_index}>
                  {/* The jumper between coils in series — the join that disappears
                      as paths increase. */}
                  {coilIndex > 0 ? (
                    <line x1={x - JUMPER} y1={y} x2={x} y2={y} stroke={colour} strokeWidth={1.6} />
                  ) : null}
                  <rect
                    x={x}
                    y={y - COIL_H / 2}
                    width={COIL_W}
                    height={COIL_H}
                    rx={4}
                    fill={`${colour}24`}
                    stroke={colour}
                    strokeWidth={1}
                  />
                  <text x={x + COIL_W / 2} y={y + 3.5} className="wl-wiring-coil" textAnchor="middle">
                    {slotLabel(coil.slot_in)}&ndash;{slotLabel(coil.slot_out)}
                  </text>
                  <title>{`Phase ${phase} coil in slots ${slotLabel(coil.slot_in)} and ${slotLabel(coil.slot_out)}`}</title>
                </g>
              );
            })}

            <text x={terminalX - 8} y={y + 3.5} className="wl-wiring-label" textAnchor="end">
              {leftover ? 'left over' : `path ${branchIndex + 1}`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function WindingLayoutView({ config, geometry }: {
  config: MotorConfig;
  geometry: GeometryPreview | null;
}) {
  const slots = geometry?.winding_layout ?? [];
  const coils = geometry?.winding_coils ?? [];
  const slotCount = config.stator.slot_count;
  const pathCount = Math.max(1, config.winding.parallel_paths);
  const metadata = (geometry?.metadata ?? {}) as Record<string, unknown>;
  const windingFactor = typeof metadata.winding_factor === 'number' ? metadata.winding_factor : null;
  const coilSpanLabel = typeof metadata.coil_span_label === 'string' ? metadata.coil_span_label : null;
  const layerCount = Math.max(1, config.winding.layers);
  const phaseCurrentA = typeof config.solve_params?.current_amplitude_A === 'number'
    ? config.solve_params.current_amplitude_A
    : null;
  const currentConvention = config.solve_params?.current_amplitude_convention ?? 'rms';

  if (!slots.length) {
    return (
      <div className="public-winding-layout is-empty">
        Start the local backend to load the winding layout.
      </div>
    );
  }

  // Turns the field carries per slot; series turns per phase is S*N/6 because each
  // physical turn has two active sides. See backend/winding_utils.py.
  const seriesTurnsPerPhase = (slotCount * config.winding.turns_per_coil) / 6;
  const stripWidth = slotCount * SLOT_PX;
  // The payload indexes slots from 0 (winding_layout.slot_index and
  // winding_coils.slot_in/out all run 0..slotCount-1). Everything shown to the
  // reader is 1-based, the way a slot would be numbered on a drawing.
  const slotCentre = (slotIndex: number) => ((slotIndex + 0.5) * SLOT_PX);
  const slotLabel = (slotIndex: number) => slotIndex + 1;

  return (
    <div className="public-winding-layout">
      <header>
        <div className="wl-title">
          <span className="wl-kicker">Winding layout</span>
          <h3>{slotCount} slots · {config.rotor.pole_count} poles</h3>
          <span className="wl-legend" aria-label="Phase colours and current direction">
            {PHASES.map((phase) => (
              <b key={phase} style={{ color: PUBLIC_PHASE_COLORS[phase], borderColor: PUBLIC_PHASE_COLORS[phase] }}>{phase}</b>
            ))}
            <em>⊙ out of page · ⊗ into page</em>
          </span>
        </div>
        <div className="wl-chips">
          <span>{config.winding.type}</span>
          <span>{config.winding.turns_per_coil} cond./slot</span>
          <span>{layerCount} layer{layerCount === 1 ? '' : 's'}</span>
          <span className="is-accent">{pathCount} path{pathCount === 1 ? '' : 's'}</span>
          {coilSpanLabel ? <span>span {coilSpanLabel.replace(' slot pitch', ' slot')}</span> : null}
          {windingFactor !== null ? <span>k_w {windingFactor.toFixed(3)}</span> : null}
          <span>{(seriesTurnsPerPhase / pathCount).toFixed(1)} turns/path</span>
        </div>
      </header>

      <div className="wl-scroll">
        <div className="wl-strip" style={{ width: `${stripWidth}px` }}>
          {/* Coil spans. Drawn over the strip so a coil's two sides read as one
              thing; concentrated coils hop between neighbours, distributed ones
              arc across their span. */}
          <svg
            className="wl-arcs"
            width={stripWidth}
            height={ARC_HEIGHT}
            role="img"
            aria-label="Coil spans between slots"
          >
            {coils.map((coil) => {
              const from = slotCentre(coil.slot_in);
              const to = slotCentre(coil.slot_out);
              // A coil that wraps past the last slot would draw backwards across the
              // whole strip, so it is marked at each end instead of joined.
              const wraps = Math.abs(to - from) > slotCount * SLOT_PX * 0.5;
              const colour = PUBLIC_PHASE_COLORS[coil.phase];
              if (wraps) {
                return [from, to].map((x, index) => (
                  <line
                    key={`${coil.coil_index}-wrap-${index}`}
                    x1={x}
                    y1={ARC_HEIGHT - 2}
                    x2={x}
                    y2={ARC_HEIGHT - 14}
                    stroke={colour}
                    strokeWidth={1.5}
                    strokeDasharray="3 3"
                  />
                ));
              }
              return (
                <path
                  key={coil.coil_index}
                  d={`M ${from} ${ARC_HEIGHT - 2} C ${from} ${ARC_HEIGHT * 0.3}, ${to} ${ARC_HEIGHT * 0.3}, ${to} ${ARC_HEIGHT - 2}`}
                  fill="none"
                  stroke={colour}
                  strokeWidth={1.5}
                  opacity={0.85}
                >
                  <title>{`Coil ${coil.coil_index + 1} · phase ${coil.phase} · slots ${slotLabel(coil.slot_in)}→${slotLabel(coil.slot_out)}`}</title>
                </path>
              );
            })}
          </svg>

          <ol className="wl-slots" aria-label="Slots in order">
            {Array.from({ length: slotCount }, (_, index) => index).map((slotIndex) => {
              const sides = slots
                .filter((slot) => slot.slot_index === slotIndex)
                .sort((a, b) => a.layer - b.layer);
              const slotNumber = slotLabel(slotIndex);
              return (
                <li key={slotIndex} style={{ width: `${SLOT_PX}px` }}>
                  <span className="wl-slot-number">{slotNumber}</span>
                  <div className="wl-slot-body">
                    {sides.length === 0
                      ? <span className="wl-side is-empty" aria-label="no winding">—</span>
                      : sides.map((side) => (
                        <span
                          key={`${side.layer}-${side.phase}-${side.direction}`}
                          className="wl-side"
                          style={{
                            background: `${PUBLIC_PHASE_COLORS[side.phase]}2e`,
                            borderColor: PUBLIC_PHASE_COLORS[side.phase],
                            color: PUBLIC_PHASE_COLORS[side.phase],
                          }}
                          title={`Slot ${slotNumber} layer ${side.layer}: phase ${side.phase}, current ${side.direction === 'out' ? 'out of' : 'into'} the page`}
                        >
                          {layerCount > 1 ? <b>L{side.layer}</b> : null}
                          <strong>{side.phase}</strong>
                          {/* Same glyphs the cross-section uses, so the two views tie together. */}
                          <em>{side.direction === 'out' ? '⊙' : '⊗'}</em>
                        </span>
                      ))}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>

      <section className="wl-paths" aria-label="Parallel paths per phase">
        <div className="wl-paths-heading">
          <strong>Parallel paths</strong>
          <span>
            {phaseCurrentA !== null
              ? `${phaseCurrentA} A ${currentConvention} into each phase terminal, splitting across ${pathCount} branch${pathCount === 1 ? '' : 'es'}${pathCount > 1 ? ` at ${(phaseCurrentA / pathCount).toFixed(1)} A each` : ''}, and rejoining at neutral`
              : `Each phase's coils split into ${pathCount} branch${pathCount === 1 ? '' : 'es'}`}
          </span>
        </div>
        <div className="wl-paths-content">
          <div className="wl-phase-list">
            {PHASES.map((phase) => {
              const phaseCoils = coils.filter((coil) => coil.phase === phase);
              const branches = branchesForPhase(phaseCoils, pathCount);
              const uneven = phaseCoils.length % pathCount !== 0;
              return (
                <div className="wl-phase-row" key={phase}>
                  <span
                    className="wl-phase-tag"
                    style={{ borderColor: PUBLIC_PHASE_COLORS[phase], color: PUBLIC_PHASE_COLORS[phase] }}
                  >
                    {phase}
                  </span>
                  <PhaseWiring
                    phase={phase}
                    branches={branches}
                    pathCount={pathCount}
                    slotLabel={slotLabel}
                    phaseCurrentA={phaseCurrentA}
                    convention={currentConvention}
                  />
                  {uneven ? (
                    <span className="wl-uneven">
                      {phaseCoils.length} coils do not divide into {pathCount} equal branches
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
          <aside className="wl-paths-info" aria-label="How parallel paths are modeled">
            <span className="wl-paths-info-icon" aria-hidden="true">i</span>
            <div>
              <strong>How the solver reads this</strong>
              <p>
                Coils split evenly in slot order. The solver divides branch current
                by the path count, modeling the electrical effect rather than the
                physical wiring.
              </p>
            </div>
          </aside>
        </div>
      </section>
    </div>
  );
}
