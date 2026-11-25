import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { PublicFieldLinePlot } from './model';
import { StatusDot, StatusSummary } from './OutputStatusBadge';
import type { NamedOutputStatus } from './outputStatus';
import { PHASE_RESISTANCE_UNRECORDED_STATUS_REASON, recordStatus } from './outputStatus';
import type { IronLoss, IronLossDensity, LossBreakdown, RotorIronLoss } from './performance';
import { InfoTip } from './Popover';
import type { WindingResistance } from './windingResistance';
import { formatResistance } from './windingResistance';
import {
  CONTEXT_FILL,
  COPPER_FILL,
  MAGNET_FILL,
  STEEL_RAMP,
  densityColor,
  formatPower,
  lossesView,
  notModelledText,
  stackCopperWPerKg,
  type LossMapMode,
  type LossRow,
  type LossSegment,
} from './lossesView';
import { formatSignificant } from './numberFormat';

/** What the pointer is on: a bar segment, or a table row. Each lights up the other. */
type LossHover = { kind: 'segment'; key: LossSegment['key'] } | { kind: 'row'; key: string } | null;

/** One bar of the loss segments. The table above names them: each segment has its row and swatch there. */
function LossBar({ segments, totalW, partial, lit, readout, onHover }: {
  segments: LossSegment[];
  totalW: number;
  partial: boolean;
  /** Segments to keep bright while something is hovered; the rest dim. */
  lit: ReadonlySet<LossSegment['key']> | null;
  readout: string | null;
  onHover: (key: LossSegment['key'] | null) => void;
}) {
  const total = formatPower(totalW);
  return (
    <div className="losses-bar-block">
      <div className="losses-bar" role="img" aria-label={`Loss breakdown, ${total.value} ${total.unit} in total`} onMouseLeave={() => onHover(null)}>
        {segments.map((segment) => (
          <span
            key={segment.key}
            className={`losses-bar-segment${lit && !lit.has(segment.key) ? ' is-dimmed' : ''}`}
            style={{ flexGrow: segment.watts, background: segment.color }}
            onMouseEnter={() => onHover(segment.key)}
          />
        ))}
      </div>
      <p className="losses-bar-readout" aria-live="polite">
        {readout ?? `${total.value} ${total.unit} ${partial ? 'known loss subtotal' : 'total loss'}`}
      </p>
    </div>
  );
}

type Part = 'iron' | 'copper' | 'magnet' | 'rotor' | 'air';

interface PreparedMesh {
  triangles: Array<{ points: Array<[number, number]>; part: Exclude<Part, 'air'>; region: string; index: number }>;
  bounds: { minX: number; minY: number; maxX: number; maxY: number };
}

function partOf(region: string): Part {
  if (region.startsWith('stator')) return 'iron';
  if (region === 'slot_winding' || region.includes('winding')) return 'copper';
  if (region === 'airgap' || region.includes('air')) return 'air';
  if (region === 'magnet') return 'magnet';
  return 'rotor';
}

function prepareMesh(plot: PublicFieldLinePlot): PreparedMesh | null {
  let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
  const triangles: PreparedMesh['triangles'] = [];
  plot.triangles.forEach((triangle, index) => {
    const points = triangle.map((node) => plot.nodes_mm[node]).filter(Boolean) as Array<[number, number]>;
    if (points.length !== 3) return;
    const region = plot.regions[index] ?? '';
    const part = partOf(region);
    if (part === 'air') return;
    for (const [x, y] of points) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    triangles.push({ points, part, region, index });
  });
  return triangles.length && maxX > minX && maxY > minY ? { triangles, bounds: { minX, minY, maxX, maxY } } : null;
}

function contains(point: [number, number], [a, b, c]: Array<[number, number]>): boolean {
  const det = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]);
  if (det === 0) return false;
  const u = ((c[1] - a[1]) * (point[0] - a[0]) - (c[0] - a[0]) * (point[1] - a[1])) / det;
  const v = ((b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])) / det;
  return u >= 0 && v >= 0 && u + v <= 1;
}

/** The 98th percentile of a mode's values, so a few tooth-tip elements do not flatten the rest of the scale. */
function scaleTop(values: Array<number | null>): { top: number; peak: number } | null {
  const sorted = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value)).sort((a, b) => a - b);
  if (!sorted.length || sorted[sorted.length - 1] <= 0) return null;
  return { top: sorted[Math.floor(0.98 * (sorted.length - 1))] || sorted[sorted.length - 1], peak: sorted[sorted.length - 1] };
}

const MODE_LABEL: Record<LossMapMode, string> = {
  iron: 'Stator iron, total',
  hysteresis: 'Stator iron, hysteresis',
  eddy: 'Stator iron, lamination eddy',
  copper: 'Copper',
};
const MODE_SHORT: Record<LossMapMode, string> = { iron: 'Iron', hysteresis: 'Hyst.', eddy: 'Eddy', copper: 'Copper' };
/** What the pointer reads over a part that carries no value on this map. */
const NO_VALUE_TEXT: Record<'magnet' | 'rotor', string> = { magnet: 'Magnet: loss not calculated', rotor: 'Rotor core: not on this map' };
const MIN_ZOOM = 1;
const MAX_ZOOM = 16;
const MAP_SIZE = 360;
const HATCH_BASE = '#1f2226';

function hatchPattern(context: CanvasRenderingContext2D): CanvasPattern | string {
  const tile = document.createElement('canvas');
  tile.width = 8; tile.height = 8;
  const tileContext = tile.getContext('2d');
  if (!tileContext) return HATCH_BASE;
  tileContext.fillStyle = HATCH_BASE;
  tileContext.fillRect(0, 0, 8, 8);
  tileContext.strokeStyle = '#3d424d';
  tileContext.lineWidth = 1;
  tileContext.beginPath();
  tileContext.moveTo(0, 8); tileContext.lineTo(8, 0);
  tileContext.moveTo(-2, 2); tileContext.lineTo(2, -2);
  tileContext.moveTo(6, 10); tileContext.lineTo(10, 6);
  tileContext.stroke();
  return context.createPattern(tile, 'repeat') ?? HATCH_BASE;
}

/**
 * Where the loss is, element by element: iron loss per kilogram of steel (total,
 * hysteresis or eddy current) or the copper loss in the coil sides. Scroll or
 * use the buttons to zoom, drag to pan, double-click to zoom in.
 */
function LossMap({ plot, density, copperWPerKg, copperStackW, copperEndW, statuses }: {
  plot: PublicFieldLinePlot;
  density: IronLossDensity | null | undefined;
  copperWPerKg: number | null;
  copperStackW: number | null;
  copperEndW: number | null;
  /** The iron and copper losses' statuses: the map is only as checked as the loss it shows. */
  statuses: NamedOutputStatus[];
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const mesh = useMemo(() => prepareMesh(plot), [plot]);
  const modes = useMemo(() => {
    const available: LossMapMode[] = [];
    const count = plot.triangles.length;
    if (density && density.element_w_per_kg.length === count) {
      available.push('iron');
      if (density.element_hysteresis_w_per_kg?.length === count) available.push('hysteresis');
      if (density.element_eddy_w_per_kg?.length === count) available.push('eddy');
    }
    if (copperWPerKg !== null && copperWPerKg > 0) available.push('copper');
    return available;
  }, [density, plot, copperWPerKg]);
  const [mode, setMode] = useState<LossMapMode>('iron');
  const shownMode: LossMapMode | undefined = modes.includes(mode) ? mode : modes[0];
  const values = useMemo(() => {
    if (!density || shownMode === 'copper') return null;
    return shownMode === 'hysteresis' ? density.element_hysteresis_w_per_kg ?? null
      : shownMode === 'eddy' ? density.element_eddy_w_per_kg ?? null
        : density.element_w_per_kg;
  }, [density, shownMode]);
  const scale = useMemo(() => (values ? scaleTop(values) : null), [values]);
  const [view, setView] = useState({ zoom: 1, cx: 0, cy: 0 });
  const [readout, setReadout] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; cx: number; cy: number } | null>(null);

  const basePixelsPerMm = useMemo(() => {
    if (!mesh) return 1;
    const { minX, minY, maxX, maxY } = mesh.bounds;
    return (MAP_SIZE * 0.96) / Math.max(maxX - minX, maxY - minY);
  }, [mesh]);
  const pixelsPerMm = basePixelsPerMm * view.zoom;

  const fit = useCallback(() => {
    if (!mesh) return;
    const { minX, minY, maxX, maxY } = mesh.bounds;
    setView({ zoom: 1, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 });
  }, [mesh]);
  useEffect(() => { fit(); }, [fit]);

  const zoomAt = useCallback((factor: number, px = MAP_SIZE / 2, py = MAP_SIZE / 2) => {
    setView((current) => {
      const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current.zoom * factor));
      // Keep the point under the cursor where it is.
      const mx = current.cx + (px - MAP_SIZE / 2) / (basePixelsPerMm * current.zoom);
      const my = current.cy - (py - MAP_SIZE / 2) / (basePixelsPerMm * current.zoom);
      return { zoom, cx: mx - (px - MAP_SIZE / 2) / (basePixelsPerMm * zoom), cy: my + (py - MAP_SIZE / 2) / (basePixelsPerMm * zoom) };
    });
  }, [basePixelsPerMm]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !mesh || !shownMode) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = MAP_SIZE * ratio;
    canvas.height = MAP_SIZE * ratio;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, MAP_SIZE, MAP_SIZE);
    const hatch = hatchPattern(context);
    const px = (x: number) => MAP_SIZE / 2 + (x - view.cx) * pixelsPerMm;
    const py = (y: number) => MAP_SIZE / 2 - (y - view.cy) * pixelsPerMm;
    for (const triangle of mesh.triangles) {
      let fill: string | CanvasPattern = CONTEXT_FILL;
      if (triangle.part === 'rotor') fill = hatch;
      else if (triangle.part === 'magnet') fill = MAGNET_FILL;
      else if (shownMode === 'copper') fill = triangle.part === 'copper' ? COPPER_FILL : CONTEXT_FILL;
      else if (triangle.part === 'iron') {
        const value = values?.[triangle.index];
        if (typeof value === 'number' && scale) fill = densityColor(value / scale.top);
      }
      context.beginPath();
      triangle.points.forEach(([x, y], index) => {
        if (index === 0) context.moveTo(px(x), py(y)); else context.lineTo(px(x), py(y));
      });
      context.closePath();
      context.fillStyle = fill;
      context.fill();
      // A hairline of the same fill closes the anti-aliasing seams between triangles.
      context.strokeStyle = typeof fill === 'string' ? fill : HATCH_BASE;
      context.lineWidth = 0.4;
      context.stroke();
    }
  }, [mesh, view, pixelsPerMm, shownMode, values, scale]);

  // Wheel zoom needs a non-passive listener to keep the page from scrolling.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      zoomAt(Math.exp(-event.deltaY * 0.0015), (event.clientX - rect.left) * (MAP_SIZE / rect.width), (event.clientY - rect.top) * (MAP_SIZE / rect.height));
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [zoomAt, mesh]);

  if (!mesh || !shownMode) return null;

  const canvasPoint = (event: React.MouseEvent<HTMLCanvasElement>): [number, number] => {
    const rect = event.currentTarget.getBoundingClientRect();
    return [(event.clientX - rect.left) * (MAP_SIZE / rect.width), (event.clientY - rect.top) * (MAP_SIZE / rect.height)];
  };
  const describe = (point: [number, number]): string | null => {
    const hit = mesh.triangles.find((triangle) => contains(point, triangle.points));
    if (!hit) return null;
    if (hit.part === 'magnet' || hit.part === 'rotor') return NO_VALUE_TEXT[hit.part];
    if (shownMode === 'copper') {
      return hit.part === 'copper' && copperWPerKg !== null
        ? `Coil side: ${Number(copperWPerKg.toPrecision(3))} W/kg of copper`
        : 'Stator iron: choose an iron view';
    }
    if (hit.part === 'copper') return 'Coil side: choose Copper';
    const value = values?.[hit.index];
    const place = hit.region === 'stator_tooth' ? 'Tooth' : hit.region === 'stator_yoke' ? 'Yoke' : 'Stator iron';
    return typeof value === 'number' ? `${place}: ${Number(value.toPrecision(3))} W/kg` : `${place}: no value`;
  };
  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, cx: view.cx, cy: view.cy };
  };
  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (drag.current) {
      const start = drag.current;
      const dx = (event.clientX - start.x) * (MAP_SIZE / rect.width);
      const dy = (event.clientY - start.y) * (MAP_SIZE / rect.height);
      setView((current) => ({ ...current, cx: start.cx - dx / pixelsPerMm, cy: start.cy + dy / pixelsPerMm }));
      return;
    }
    const [x, y] = canvasPoint(event);
    setReadout(describe([view.cx + (x - MAP_SIZE / 2) / pixelsPerMm, view.cy - (y - MAP_SIZE / 2) / pixelsPerMm]));
  };
  const onPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    drag.current = null;
  };

  const shownStatus = statuses.find((item) => item.key === (shownMode === 'copper' ? 'copper' : 'iron'));
  const legendTop = scale ? formatSignificant(scale.top) : null;
  const peak = scale ? formatSignificant(scale.peak) : null;
  const copperText = copperWPerKg !== null ? formatSignificant(copperWPerKg) : null;
  const stackPower = copperStackW !== null ? formatPower(copperStackW) : null;
  const endPower = copperEndW !== null ? formatPower(copperEndW) : null;
  return (
    <figure className="losses-map">
      <div className="losses-map-heading">
        <h4>Where the loss is</h4>
        {shownStatus && <StatusDot status={shownStatus.status} label={shownStatus.label} reason={shownStatus.reason} />}
        <InfoTip label="About the loss map">
          {shownMode === 'copper' ? (
            <p>
              Copper loss in the stack: {copperText} W/kg of copper in every coil side{stackPower ? `, ${stackPower.value} ${stackPower.unit} in all` : ''}.
              {endPower ? ` The end turns' ${endPower.value} ${endPower.unit} lie outside this cross-section.` : ''}
              {' '}The model carries the same current density in every coil side, so it is one value.
            </p>
          ) : (
            <p>
              {MODE_LABEL[shownMode]} loss per kilogram of steel over one electrical period; lighter is more loss.
              The scale stops at the 98th percentile; the peak is {peak} W/kg.
            </p>
          )}
          <p>
            <span className="losses-map-swatch" style={{ background: MAGNET_FILL }} aria-hidden="true" /> Magnets: coilEM does not calculate a magnet loss yet.
            {' '}<span className="losses-map-swatch is-hatched" aria-hidden="true" /> Rotor core: not on this density map.
            {shownMode !== 'copper' && <> <span className="losses-map-swatch" style={{ background: CONTEXT_FILL }} aria-hidden="true" /> Coil sides: choose Copper.</>}
          </p>
          <p>Scroll, double-click or use + and − to zoom; drag to move.</p>
        </InfoTip>
        <div className="losses-map-modes" role="group" aria-label="Loss shown on the map">
          {modes.map((item) => (
            <button key={item} type="button" aria-pressed={item === shownMode} aria-label={MODE_LABEL[item]} title={MODE_LABEL[item]} onClick={() => setMode(item)}>{MODE_SHORT[item]}</button>
          ))}
        </div>
      </div>
      <div className="losses-map-stage">
        <canvas
          ref={canvasRef}
          style={{ width: MAP_SIZE, height: MAP_SIZE }}
          role="img"
          aria-label={shownMode === 'copper'
            ? `Copper loss in the coil sides, ${copperText} W/kg of copper`
            : `${MODE_LABEL[shownMode]} loss per kilogram across the stator, peaking at ${peak} W/kg`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onPointerLeave={() => { if (!drag.current) setReadout(null); }}
          onDoubleClick={(event) => zoomAt(2, ...canvasPoint(event))}
        />
        <div className="losses-map-zoom" role="group" aria-label="Map zoom">
          <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => zoomAt(1.6)}>+</button>
          <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => zoomAt(1 / 1.6)} disabled={view.zoom <= MIN_ZOOM}>−</button>
          <button type="button" aria-label="Fit motor to view" title="Fit motor to view" onClick={fit} disabled={view.zoom <= MIN_ZOOM}>Fit</button>
        </div>
      </div>
      <figcaption>
        {shownMode === 'copper' ? (
          <span className="losses-map-key">
            <span className="losses-map-swatch" style={{ background: COPPER_FILL }} aria-hidden="true" />
            {copperText} W/kg of copper in every coil side
          </span>
        ) : (
          <span className="losses-map-scale-row">
            <span>0</span>
            <span className="losses-map-scale" style={{ background: `linear-gradient(90deg, ${STEEL_RAMP.join(', ')})` }} aria-hidden="true" />
            <span>≥ {legendTop} W/kg</span>
          </span>
        )}
        <span className="losses-map-parts">
          <span><span className="losses-map-swatch" style={{ background: MAGNET_FILL }} aria-hidden="true" />Magnets, loss not calculated</span>
          <span><span className="losses-map-swatch is-hatched" aria-hidden="true" />Rotor core, not on this map</span>
        </span>
        <span className="losses-map-readout" aria-live="polite">
          {readout ?? (view.zoom > 1 ? `${view.zoom.toFixed(1)}×` : '')}
        </span>
      </figcaption>
    </figure>
  );
}

/**
 * Losses and efficiency of a completed run (#138). Renders nothing for a run
 * without a loss breakdown.
 */
interface LossMapSource {
  loss?: LossBreakdown | null;
  iron?: IronLoss | null;
  rotor?: RotorIronLoss | null;
  density?: IronLossDensity | null;
  plot?: PublicFieldLinePlot | null;
  winding?: WindingResistance | null;
  slotCount?: number;
}

/** Whether a run has a loss density that can be drawn on its cross-section. */
export function hasLossMap({ loss, density, plot, winding, slotCount }: LossMapSource): boolean {
  return Boolean(loss && plot && (density || stackCopperWPerKg(loss, winding, slotCount ?? 0) !== null));
}

/** The loss map on its own, for the Results plot tabs: where in the cross-section the iron and copper loss is. */
export function LossMapPanel({ loss, iron, rotor, density, plot, winding, slotCount }: LossMapSource) {
  const view = lossesView(loss, iron, winding ?? null, rotor ?? null);
  if (!view || !loss || !plot || !hasLossMap({ loss, density, plot, winding, slotCount })) return null;
  return <section className="losses-map-panel" aria-label="Loss map">
    <LossMap
      plot={plot}
      density={density}
      copperWPerKg={stackCopperWPerKg(loss, winding, slotCount ?? 0)}
      copperStackW={loss.copper_active_loss_W ?? null}
      copperEndW={loss.copper_end_winding_loss_W ?? null}
      statuses={view.statuses}
    />
  </section>;
}

export function LossesCard({
  loss,
  iron,
  rotor,
  density,
  plot,
  winding,
  slotCount,
  variant = 'panel',
  map = true,
}: {
  loss?: LossBreakdown | null;
  iron?: IronLoss | null;
  rotor?: RotorIronLoss | null;
  density?: IronLossDensity | null;
  plot?: PublicFieldLinePlot | null;
  winding?: WindingResistance | null;
  slotCount?: number;
  variant?: 'panel' | 'report';
  /** False keeps the card to its numbers; the map is then shown by LossMapPanel elsewhere. */
  map?: boolean;
}) {
  const headingId = useId();
  const [hover, setHover] = useState<LossHover>(null);
  // Loss rows the user opened or closed; the rest follow the view's default.
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  const view = lossesView(loss, iron, winding ?? null, rotor ?? null);
  if (!view || !loss) {
    if (!winding) return null;
    const status = recordStatus(winding, PHASE_RESISTANCE_UNRECORDED_STATUS_REASON);
    return <section className={`motor-constants losses-card${variant === 'report' ? ' is-report' : ''}`} aria-labelledby={headingId}>
      <div className="results-card-heading">
        <h3 id={headingId}>Winding</h3>
        <StatusSummary statuses={[{ key: 'resistance', label: 'Phase resistance', ...status }]} />
      </div>
      <table><tbody>
        <tr><th scope="row">Phase resistance</th><td>{formatResistance(winding.phase_resistance_ohm)} at {winding.winding_temperature_C} °C</td></tr>
        {winding.winding_temperature_C !== 20 && <tr><th scope="row">Phase resistance at 20 °C</th><td>{formatResistance(winding.phase_resistance_20C_ohm)}</td></tr>}
      </tbody></table>
    </section>;
  }
  const copperWPerKg = stackCopperWPerKg(loss, winding, slotCount ?? 0);
  const rowStatus = (key: string) => view.statuses.find((item) => item.key === key) ?? null;
  const efficiencyStatus = rowStatus('efficiency');
  const mapAvailable = Boolean(plot && (density || copperWPerKg !== null));
  const showMap = map && mapAvailable;
  const isOpen = (row: LossRow) => opened[row.key] ?? row.expanded ?? false;
  const openParents = new Set(view.rows.filter((row) => row.expanded !== undefined && isOpen(row)).map((row) => row.key));
  const shownRows = view.rows.filter((row) => !row.parent || openParents.has(row.parent));
  // A segment's own row when it shows, else the loss row that holds it.
  const rowOfSegment = (key: LossSegment['key']) => shownRows.find((row) => row.key === key) ?? shownRows.find((row) => row.segments?.includes(key));
  const hoveredRow = hover?.kind === 'row' ? shownRows.find((row) => row.key === hover.key) : undefined;
  const hoveredSegment = hover?.kind === 'segment' ? view.segments.find((segment) => segment.key === hover.key) : undefined;
  const litRowKey = hoveredRow?.key ?? (hoveredSegment ? rowOfSegment(hoveredSegment.key)?.key : undefined);
  const lit = hoveredSegment ? new Set([hoveredSegment.key]) : hoveredRow?.segments ? new Set(hoveredRow.segments) : null;
  const segmentReadout = (segment: LossSegment) => {
    const power = formatPower(segment.watts);
    return `${segment.label}: ${power.value} ${power.unit} (${segment.shareText})`;
  };
  const readout = hoveredSegment ? segmentReadout(hoveredSegment)
    : hoveredRow?.parent ? segmentReadout(view.segments.find((segment) => segment.key === hoveredRow.key)!)
      : hoveredRow?.share ? `${hoveredRow.label}: ${hoveredRow.value} ${hoveredRow.unit} (${hoveredRow.share})` : null;
  const hoverRow = (row: LossRow) => (row.segments ? () => setHover({ kind: 'row', key: row.key }) : undefined);
  const rowClass = (row: LossRow) => [
    row.key === 'input' || row.key === 'copper' ? 'is-group-start' : row.key === 'total' ? 'is-total' : '',
    row.parent ? 'is-segment' : '',
    row.key === litRowKey ? 'is-lit' : '',
  ].filter(Boolean).join(' ') || undefined;
  return (
    <section className={`motor-constants losses-card${variant === 'report' ? ' is-report' : ''}${showMap ? ' has-map' : ''}`} aria-labelledby={headingId}>
      <div className="results-card-heading">
        <h3 id={headingId}>Losses &amp; efficiency</h3>
        <StatusSummary statuses={view.statuses}>
          <p className="popover-note">{notModelledText(loss)}</p>
        </StatusSummary>
      </div>
      {view.efficiency.status === 'unavailable' && <p className="performance-message" role="status">{view.efficiency.reason || 'Efficiency is unavailable for this run.'} {loss.iron_loss_status_reason} {loss.iron_loss_W == null && 'The loss subtotal excludes unavailable iron loss.'}</p>}
      <div className="losses-card-body">
        <div className="losses-card-numbers">
          {/* The table is the bar's legend: every bar segment has a row here with the same swatch and share. */}
          <table>
            <tbody>
              <tr className="losses-efficiency" title="Shaft power ÷ input power at the solved operating point.">
                <th scope="row"><span className="losses-hint">Efficiency</span></th>
                <td className="motor-constants-value">{view.efficiency.value}</td>
                <td className="motor-constants-unit">{view.efficiency.value === '—' ? '' : '%'}</td>
                <td className="losses-share-cell" />
                <td className="losses-status-cell">
                  {efficiencyStatus && <StatusDot status={efficiencyStatus.status} label={efficiencyStatus.label} reason={efficiencyStatus.reason} />}
                </td>
              </tr>
              {shownRows.map((row) => {
                const status = row.status ? rowStatus(row.key) : null;
                const label = <span className={row.hint ? 'losses-hint' : undefined}>{row.label}</span>;
                const segment = row.parent ? view.segments.find((item) => item.key === row.key) : undefined;
                return (
                  <tr key={row.key} title={row.hint} className={rowClass(row)} onMouseEnter={hoverRow(row)} onMouseLeave={row.segments ? () => setHover(null) : undefined}>
                    <th scope="row">
                      {row.expanded !== undefined ? (
                        <button
                          type="button"
                          className="losses-group-toggle"
                          aria-expanded={isOpen(row)}
                          onClick={() => setOpened((current) => ({ ...current, [row.key]: !isOpen(row) }))}
                          onFocus={hoverRow(row)}
                          onBlur={() => setHover(null)}
                        >
                          <span className="losses-chevron" aria-hidden="true" />
                          {label}
                        </button>
                      ) : (
                        <>
                          {row.color
                            ? <span className="losses-swatch" style={{ background: row.color }} aria-hidden="true" />
                            : row.group && <span className="losses-swatch is-blank" aria-hidden="true" />}
                          {segment ? <><span className="public-visually-hidden">{segment.label}</span><span aria-hidden="true">{label}</span></> : label}
                        </>
                      )}
                    </th>
                    <td className="motor-constants-value">{row.value}</td>
                    <td className="motor-constants-unit">{row.unit}</td>
                    <td className="losses-share-cell">{row.share ?? ''}</td>
                    <td className="losses-status-cell">
                      {row.status && <StatusDot status={row.status} label={status?.label ?? row.label} reason={status?.reason ?? row.hint ?? ''} />}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {view.segments.length > 0 && <LossBar
            segments={view.segments}
            totalW={view.totalW}
            partial={loss.iron_loss_W == null || loss.rotor_iron_loss_status === 'unavailable'}
            lit={lit}
            readout={readout}
            onHover={(key) => setHover(key ? { kind: 'segment', key } : null)}
          />}
          {mapAvailable && !showMap && <p className="motor-constants-note">Where the loss is in the motor: the Losses tab below.</p>}
        </div>
        {showMap && plot && (
          <LossMap
            plot={plot}
            density={density}
            copperWPerKg={copperWPerKg}
            copperStackW={loss.copper_active_loss_W ?? null}
            copperEndW={loss.copper_end_winding_loss_W ?? null}
            statuses={view.statuses}
          />
        )}
      </div>
    </section>
  );
}
