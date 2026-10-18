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
import { useId, useLayoutEffect, useRef, useState } from 'react';
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
  slotMarkerRadius,
  slotSideCentre,
  slotSidePath,
  type SlotLayerSplit,
} from './windingRing';
import {
  COIL_H,
  COIL_W,
  PHASE_TAG_SPACE,
  branchesForPhase,
  coilsPerRow,
  layoutPhaseWiring,
} from './windingWiring';

const PHASES: PublicPhaseId[] = ['A', 'B', 'C'];

/**
 * A coil side's current direction, drawn the way the 2D view draws it (MotorCanvas
 * drawCurrentMarker): a dark disc ringed in the phase colour with a light dot for
 * current out of the page or a cross for into it. Drawn rather than typed, so it
 * can fill its slot side and the dot stays round in every font.
 */
function CurrentMarker({ x, y, radius, outOfPage, colour }: {
  x: number;
  y: number;
  /** Outer edge, ring stroke included. */
  radius: number;
  outOfPage: boolean;
  colour: string;
}) {
  const ring = radius / 1.09;
  const reach = ring * 0.52;
  return (
    <g className="wl-ring-marker" transform={`translate(${x.toFixed(2)} ${y.toFixed(2)})`}>
      <circle className="wl-ring-marker-disc" r={ring} stroke={colour} strokeWidth={ring * 0.18} />
      {outOfPage ? (
        <circle className="wl-ring-marker-dot" r={ring * 0.34} />
      ) : (
        <path
          className="wl-ring-marker-cross"
          d={`M ${-reach} ${-reach} L ${reach} ${reach} M ${reach} ${-reach} L ${-reach} ${reach}`}
          strokeWidth={ring * 0.22}
        />
      )}
    </g>
  );
}

/**
 * One phase drawn as wiring rather than as a list of groups.
 *
 * A branch is a series chain between two junctions — the phase terminal and the
 * star point — and that is the whole difference between 1, 2 and 4 paths: the slots
 * hold exactly the same conductors either way, only the joins move. Listing which
 * coils group together read as sorting; drawing terminal → coil → jumper → coil →
 * neutral shows that a=1 is one long chain and a=4 is four short ones in parallel,
 * and labelling the leads shows the phase current dividing as it goes.
 *
 * A chain longer than the panel is wide wraps like a snake, row after row with a
 * U-turn at each end (see windingWiring.ts), so a=1 on a 36-slot machine is still
 * one chain without running off the side.
 */
function PhaseWiring({ phase, branches, pathCount, slotLabel, phaseCurrentA, convention, perRow }: {
  phase: PublicPhaseId;
  branches: PublicWindingCoil[][];
  pathCount: number;
  slotLabel: (slotIndex: number) => number;
  phaseCurrentA: number | null;
  convention: 'rms' | 'peak' | 'plateau';
  /** Coils that fit one row of the panel. */
  perRow: number;
}) {
  const colour = PUBLIC_PHASE_COLORS[phase];
  const layout = layoutPhaseWiring(branches.map((branch) => branch.length), perRow);
  const { terminalX, chainX, terminalBus, neutralBus } = layout;

  // What the solver actually does with the path count: divide the branch current.
  // Only true while the branches match, which is why the uneven case says so
  // instead of printing a number the machine would not deliver.
  const evenSplit = branches.length === pathCount;
  const branchCurrentA = phaseCurrentA !== null ? phaseCurrentA / pathCount : null;
  const amps = (value: number) => `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} A`;

  return (
    <svg
      className={`wl-wiring${layout.wrapped ? ' is-wrapped' : ''}`}
      width={layout.width}
      height={layout.height}
      role="img"
      aria-label={`Phase ${phase}: ${branches.length} branch${branches.length === 1 ? '' : 'es'} between terminal and neutral, ${branches.map((b) => `${b.length} coil${b.length === 1 ? '' : 's'}`).join(', ')}${branchCurrentA !== null && evenSplit ? `, ${amps(branchCurrentA)} per branch` : ''}`}
    >
      {/* Terminal and neutral buses: the two junctions every branch shares. */}
      {terminalBus && neutralBus ? (
        <>
          <line x1={terminalBus.x} y1={terminalBus.y1} x2={terminalBus.x} y2={terminalBus.y2} stroke={colour} strokeWidth={1.6} />
          <line x1={neutralBus.x} y1={neutralBus.y1} x2={neutralBus.x} y2={neutralBus.y2} stroke={colour} strokeWidth={1.6} />
        </>
      ) : null}

      {/* Phase current in, at the terminal. The phase tag beside the diagram already
          names the phase, so the terminal carries the current rather than a letter
          that repeated it and collided with the path label. */}
      {phaseCurrentA !== null ? (
        <text x={layout.totalCurrentLabel.x} y={layout.totalCurrentLabel.y} className="wl-wiring-current is-total" textAnchor="middle">
          {amps(phaseCurrentA)} {convention}
        </text>
      ) : null}
      {/* N at the neutral end: above it on the right, or in the gutter under
          "path 1" when a lone wrapped branch ends on the left. */}
      <text x={layout.neutralLabel.x} y={layout.neutralLabel.y} className="wl-wiring-node" textAnchor={layout.neutralLabel.anchor}>N</text>

      {branches.map((branch, branchIndex) => {
        const placed = layout.branches[branchIndex];
        const y = placed.startY;
        // A group beyond the requested count is the remainder of an uneven split.
        const leftover = branches.length > pathCount && branchIndex === branches.length - 1;
        const leadStroke = leftover ? '#f87171' : colour;
        return (
          <g key={branchIndex}>
            <path className="wl-wiring-wire" d={placed.leadIn} stroke={leadStroke} strokeDasharray={leftover ? '3 2' : undefined} />
            {/* Out to neutral; a branch that ends on the left with a bus to reach
                returns under its last row. */}
            <path className="wl-wiring-wire" d={placed.leadOut} stroke={leadStroke} strokeDasharray={leftover ? '3 2' : undefined} />

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
              const { x, y: coilY } = placed.coils[coilIndex];
              return (
                <g key={coil.coil_index}>
                  {/* The jumper between coils in series — the join that disappears
                      as paths increase — or, at a row end, the U-turn to the next row. */}
                  {coilIndex > 0 ? (
                    <path className="wl-wiring-wire" d={placed.joins[coilIndex - 1]} stroke={colour} />
                  ) : null}
                  <rect
                    x={x}
                    y={coilY - COIL_H / 2}
                    width={COIL_W}
                    height={COIL_H}
                    rx={4}
                    fill={`${colour}24`}
                    stroke={colour}
                    strokeWidth={1}
                  />
                  <text x={x + COIL_W / 2} y={coilY + 3.5} className="wl-wiring-coil" textAnchor="middle">
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
  // The wiring wraps to the width the paths section has, so follow the panel as
  // it resizes. Measured before paint, so a long chain never shows unwrapped first.
  const pathsRef = useRef<HTMLElement | null>(null);
  const [pathsWidth, setPathsWidth] = useState<number | null>(null);
  // What the solver makes of the wiring, behind a question the reader can open,
  // so it never takes the wiring's room unasked.
  const [pathsHelpOpen, setPathsHelpOpen] = useState(false);
  const pathsHelpId = useId();
  const hasLayout = slots.length > 0;
  useLayoutEffect(() => {
    const section = pathsRef.current;
    if (!section) return undefined;
    const measure = () => setPathsWidth(section.clientWidth);
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(section);
    return () => observer.disconnect();
  }, [hasLayout]);
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

  if (!hasLayout) {
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
  // Marker and number sizes follow the space a slot side and a slot pitch have.
  const markerRadius = slotMarkerRadius(slotCount, ringLayers, layerSplit);
  const numberSize = Math.max(12, Math.min(22, ((2 * Math.PI * WINDING_RING.numbers) / slotCount) * 0.42));
  const numberStep = slotCount > 48 ? 2 : 1;
  // Each wiring sits beside its phase tag, so it has the section's width less the tag.
  const wiringPerRow = coilsPerRow(pathsWidth === null ? null : pathsWidth - PHASE_TAG_SPACE);

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

      {/* The ring and the paths below the header: stacked in a narrow panel, side by
          side (ring left, paths right) in a wide one, so both stay on screen. */}
      <div className="wl-body">
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
                      const [markerX, markerY] = slotSideCentre(slotIndex, slotCount, layer, ringLayers, layerSplit);
                      // The solver drives an "in" side at +J, which in the x-y plane is
                      // out of the page; the cross-section marks it ⊙ too.
                      const outOfPage = side.direction === 'in';
                      return (
                        <g key={`${side.layer}-${side.phase}-${side.direction}`}>
                          <path
                            className="wl-ring-slot"
                            d={slotSidePath(slotIndex, slotCount, layer, ringLayers, layerSplit)}
                            fill={`${colour}3d`}
                            stroke={colour}
                          >
                            <title>{`Slot ${slotNumber}${layerCount > 1 ? ` layer ${side.layer}` : ''}: phase ${side.phase}, current ${outOfPage ? 'out of' : 'into'} the page`}</title>
                          </path>
                          {/* The cross-section's ⊙ / ⊗, so the two views tie together. */}
                          <CurrentMarker x={markerX} y={markerY} radius={markerRadius} outOfPage={outOfPage} colour={colour} />
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

        <section className="wl-paths" ref={pathsRef} aria-label="Parallel paths per phase">
          <div className="wl-paths-heading">
            <strong>Parallel paths</strong>
            <span>
              {phaseCurrentA !== null
                ? `${phaseCurrentA} A ${currentConvention} into each phase terminal, splitting across ${pathCount} branch${pathCount === 1 ? '' : 'es'}${pathCount > 1 ? ` at ${(phaseCurrentA / pathCount).toFixed(1)} A each` : ''}, and rejoining at neutral`
                : `Each phase's coils split into ${pathCount} branch${pathCount === 1 ? '' : 'es'}`}
            </span>
            <button
              type="button"
              className="wl-paths-help-toggle"
              aria-expanded={pathsHelpOpen}
              aria-controls={pathsHelpId}
              onClick={() => setPathsHelpOpen((open) => !open)}
            >
              <span className="wl-paths-help-icon" aria-hidden="true">i</span>
              Does the solver use this wiring?
            </button>
          </div>
          {pathsHelpOpen ? (
            <p className="wl-paths-help" id={pathsHelpId}>
              <strong>Not directly.</strong> The branches are drawn in slot order, a common
              way to connect them. The solver gives every coil the phase current divided by
              the number of paths, so the number of paths changes the result but which coils
              share a branch does not. Current circulating between unequal branches is not
              modeled.
            </p>
          ) : null}
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
                      perRow={wiringPerRow}
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
          </div>
        </section>
      </div>
    </div>
  );
}
