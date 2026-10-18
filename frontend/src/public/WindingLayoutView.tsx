/**
 * The Layout view: the winding drawn as a wiring diagram.
 *
 * The top half is the stator as a ring of numbered slots, each coil side in its
 * phase colour with its current direction, and every coil's end turn arcing from
 * one side to the other outside the ring. It keeps the cross-section's
 * orientation, so a phase belt sits where it does in the 2D view, and the end
 * turns show how the coils join slots, which the cross-section cannot. Below,
 * parallel paths, which had no representation anywhere in the app (the
 * cross-section is pixel-identical for 1, 2 or 4), are drawn as wiring.
 */
import { createPortal } from 'react-dom';
import type { GeometryPreview, MotorConfig, PublicWindingCoil } from './model';
import { PUBLIC_PHASE_COLORS, type PublicPhaseId } from './motorPalette';
import { useViewportNavigation, ViewportNavigationControls } from './ViewportNavigation';
import {
  WINDING_RING,
  WINDING_RING_EXTENT,
  endTurnPath,
  polar,
  slotAngle,
  slotSideCentre,
  slotSidePath,
  type SlotLayerSplit,
} from './windingRing';

const PHASES: PublicPhaseId[] = ['A', 'B', 'C'];

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

export function WindingLayoutView({ config, geometry, navigationSlot = null }: {
  config: MotorConfig;
  geometry: GeometryPreview | null;
  /** The bottom bar's zoom slot, where the 2D view puts its controls too. */
  navigationSlot?: HTMLElement | null;
}) {
  // Zoom and pan the ring the way the 2D view zooms the motor: wheel about the
  // pointer, drag once zoomed in, and the same - / + / Fit controls.
  const navigation = useViewportNavigation();
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
  // The payload indexes slots from 0 (winding_layout.slot_index and
  // winding_coils.slot_in/out all run 0..slotCount-1). Everything shown to the
  // reader is 1-based, the way a slot would be numbered on a drawing.
  const slotLabel = (slotIndex: number) => slotIndex + 1;
  // How a two-layer slot divides, as the geometry builds it.
  const layerSplit: SlotLayerSplit = metadata.slot_layer_split === 'radial' || metadata.slot_layer_split === 'tangential'
    ? metadata.slot_layer_split
    : null;
  const ringLayers = layerSplit ? layerCount : 1;
  // Glyph and number sizes follow the space a slot side and a slot pitch have.
  const pitchAtSlots = (2 * Math.PI * ((WINDING_RING.inner + WINDING_RING.outer) / 2)) / slotCount;
  const sideWidth = pitchAtSlots * 0.62 / (layerSplit === 'tangential' ? ringLayers : 1);
  const sideDepth = (WINDING_RING.outer - WINDING_RING.inner) / (layerSplit === 'radial' ? ringLayers : 1);
  const glyphSize = Math.max(10, Math.min(30, Math.min(sideWidth, sideDepth) * 0.72));
  const numberSize = Math.max(12, Math.min(22, ((2 * Math.PI * WINDING_RING.numbers) / slotCount) * 0.42));
  const numberStep = slotCount > 48 ? 2 : 1;

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

      {/* The stator as a ring of slots, in the cross-section's orientation, with
          each coil's end turn outside it: a hop between neighbours for a tooth
          coil, an arc across its span for a distributed one. */}
      <div
        className={`wl-ring public-viewport-navigation${navigation.panEnabled ? ' is-pannable' : ''}${navigation.isDragging ? ' is-dragging' : ''}`}
        ref={navigation.viewportRef}
        {...navigation.bind}
      >
        <div className="public-viewport-navigation-content" style={navigation.contentStyle}>
          <svg
            className="wl-ring-svg"
            viewBox={`${-WINDING_RING_EXTENT} ${-WINDING_RING_EXTENT} ${2 * WINDING_RING_EXTENT} ${2 * WINDING_RING_EXTENT}`}
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label={`${slotCount} slots around the bore, numbered counter-clockwise from slot 1 at three o'clock, with each coil's end turn`}
          >
            <circle className="wl-ring-bore" r={WINDING_RING.inner} />
            <circle className="wl-ring-back" r={WINDING_RING.outer} />
            {coils.map((coil) => (
              <path
                key={coil.coil_index}
                className="wl-ring-end-turn"
                d={endTurnPath(coil.slot_in, coil.slot_out, slotCount)}
                stroke={PUBLIC_PHASE_COLORS[coil.phase]}
              >
                <title>{`Coil ${coil.coil_index + 1} · phase ${coil.phase} · slots ${slotLabel(coil.slot_in)}→${slotLabel(coil.slot_out)}`}</title>
              </path>
            ))}
            {Array.from({ length: slotCount }, (_, index) => index).map((slotIndex) => {
              const sides = slots.filter((slot) => slot.slot_index === slotIndex);
              const slotNumber = slotLabel(slotIndex);
              const [numberX, numberY] = polar(WINDING_RING.numbers, slotAngle(slotIndex, slotCount));
              return (
                <g key={slotIndex}>
                  {sides.length === 0 ? (
                    <path className="wl-ring-slot is-empty" d={slotSidePath(slotIndex, slotCount, 1, 1, null)}>
                      <title>{`Slot ${slotNumber}: no winding`}</title>
                    </path>
                  ) : sides.map((side) => {
                    const colour = PUBLIC_PHASE_COLORS[side.phase];
                    const layer = layerSplit ? side.layer : 1;
                    const [glyphX, glyphY] = slotSideCentre(slotIndex, slotCount, layer, ringLayers, layerSplit);
                    return (
                      <g key={`${side.layer}-${side.phase}-${side.direction}`}>
                        <path
                          className="wl-ring-slot"
                          d={slotSidePath(slotIndex, slotCount, layer, ringLayers, layerSplit)}
                          fill={`${colour}3d`}
                          stroke={colour}
                        >
                          <title>{`Slot ${slotNumber}${layerCount > 1 ? ` layer ${side.layer}` : ''}: phase ${side.phase}, current ${side.direction === 'out' ? 'out of' : 'into'} the page`}</title>
                        </path>
                        {/* Same glyphs the cross-section uses, so the two views tie together. */}
                        <text
                          className="wl-ring-glyph"
                          x={glyphX}
                          y={glyphY}
                          fill={colour}
                          fontSize={glyphSize}
                          textAnchor="middle"
                          dominantBaseline="central"
                        >
                          {side.direction === 'out' ? '⊙' : '⊗'}
                        </text>
                      </g>
                    );
                  })}
                  {slotIndex % numberStep === 0 ? (
                    <text
                      className="wl-ring-number"
                      x={numberX}
                      y={numberY}
                      fontSize={numberSize}
                      textAnchor="middle"
                      dominantBaseline="central"
                    >
                      {slotNumber}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </svg>
        </div>
      </div>
      {navigationSlot ? createPortal(
        <ViewportNavigationControls
          scale={navigation.scale}
          onZoomIn={navigation.zoomIn}
          onZoomOut={navigation.zoomOut}
          onReset={navigation.reset}
          fitSubject="winding"
        />,
        navigationSlot,
      ) : null}

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
