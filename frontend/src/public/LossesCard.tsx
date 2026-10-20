import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { PublicFieldLinePlot } from './model';
import type { IronLoss, IronLossDensity, LossBreakdown, PerformanceOutputStatus } from './performance';
import type { WindingResistance } from './windingResistance';
import {
  CONTEXT_FILL,
  COPPER_FILL,
  STEEL_RAMP,
  densityColor,
  formatPower,
  lossesView,
  stackCopperWPerKg,
  type LossMapMode,
  type LossSegment,
} from './lossesView';

const STATUS_LABEL: Record<PerformanceOutputStatus, string> = {
  qualified: 'Qualified',
  experimental: 'Experimental',
  unavailable: 'Unavailable',
};

function StatusBadge({ status, title }: { status: PerformanceOutputStatus; title?: string }) {
  return <span className={`losses-status is-${status}`} title={title}>{STATUS_LABEL[status]}</span>;
}

function LossBar({ segments, totalW }: { segments: LossSegment[]; totalW: number }) {
  const [hovered, setHovered] = useState<LossSegment['key'] | null>(null);
  const active = segments.find((segment) => segment.key === hovered) ?? null;
  const total = formatPower(totalW);
  return (
    <div className="losses-bar-block">
      <div className="losses-bar" role="img" aria-label={`Loss breakdown, ${total.value} ${total.unit} in total`} onMouseLeave={() => setHovered(null)}>
        {segments.map((segment) => (
          <span
            key={segment.key}
            className={`losses-bar-segment${hovered && hovered !== segment.key ? ' is-dimmed' : ''}`}
            style={{ flexGrow: segment.watts, background: segment.color }}
            onMouseEnter={() => setHovered(segment.key)}
          />
        ))}
      </div>
      <p className="losses-bar-readout" aria-live="polite">
        {active
          ? `${active.label}: ${formatPower(active.watts).value} ${formatPower(active.watts).unit} (${Math.round(active.share * 100)}%)`
          : `${total.value} ${total.unit} total loss`}
      </p>
      <ul className="losses-legend">
        {segments.map((segment) => {
          const power = formatPower(segment.watts);
          return (
            <li key={segment.key} onMouseEnter={() => setHovered(segment.key)} onMouseLeave={() => setHovered(null)}>
              <span className="losses-swatch" style={{ background: segment.color }} aria-hidden="true" />
              <span className="losses-legend-label">{segment.label}</span>
              <span className="losses-legend-value">{power.value} {power.unit}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

type Part = 'iron' | 'copper' | 'unmodelled' | 'air';

interface PreparedMesh {
  triangles: Array<{ points: Array<[number, number]>; part: Exclude<Part, 'air'>; region: string; index: number }>;
  bounds: { minX: number; minY: number; maxX: number; maxY: number };
}

function partOf(region: string): Part {
  if (region.startsWith('stator')) return 'iron';
  if (region === 'slot_winding' || region.includes('winding')) return 'copper';
  if (region === 'airgap' || region.includes('air')) return 'air';
  return 'unmodelled';
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
  iron: 'Iron, total',
  hysteresis: 'Iron, hysteresis',
  eddy: 'Iron, eddy current',
  copper: 'Copper',
};
const PART_LABEL: Record<Exclude<Part, 'air'>, string> = { iron: 'Stator iron', copper: 'Coil side', unmodelled: 'Rotor or magnet' };
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
function LossMap({ plot, density, copperWPerKg, copperStackW, copperEndW }: {
  plot: PublicFieldLinePlot;
  density: IronLossDensity | null | undefined;
  copperWPerKg: number | null;
  copperStackW: number | null;
  copperEndW: number | null;
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
      if (triangle.part === 'unmodelled') fill = hatch;
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
    if (hit.part === 'unmodelled') return `${PART_LABEL.unmodelled}: loss not modelled`;
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

  const legendTop = scale ? Number(scale.top.toPrecision(3)) : null;
  const peak = scale ? Number(scale.peak.toPrecision(3)) : null;
  const copperText = copperWPerKg !== null ? Number(copperWPerKg.toPrecision(3)) : null;
  const stackPower = copperStackW !== null ? formatPower(copperStackW) : null;
  const endPower = copperEndW !== null ? formatPower(copperEndW) : null;
  return (
    <figure className="losses-map">
      <div className="losses-map-heading">
        <h4>Where the loss is</h4>
        <div className="losses-map-modes" role="group" aria-label="Loss shown on the map">
          {modes.map((item) => (
            <button key={item} type="button" aria-pressed={item === shownMode} onClick={() => setMode(item)}>{MODE_LABEL[item]}</button>
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
        <span className="losses-map-readout" aria-live="polite">
          {readout ?? `Scroll, double-click or use + and − to zoom; drag to move${view.zoom > 1 ? ` (${view.zoom.toFixed(1)}×)` : ''}.`}
        </span>
        {shownMode === 'copper' ? (
          <span className="losses-map-key">
            <span className="losses-map-swatch" style={{ background: COPPER_FILL }} aria-hidden="true" />
            Copper loss in the stack: {copperText} W/kg of copper in every coil side{stackPower ? `, ${stackPower.value} ${stackPower.unit} in all` : ''}.
            {endPower ? ` The end turns' ${endPower.value} ${endPower.unit} lie outside this cross-section.` : ''}
            {' '}The model carries the same current density in every coil side, so it is one value.
          </span>
        ) : (
          <>
            <span className="losses-map-scale" style={{ background: `linear-gradient(90deg, ${STEEL_RAMP.join(', ')})` }} aria-hidden="true" />
            <span className="losses-map-labels"><span>0</span><span>≥ {legendTop} W/kg</span></span>
            <span className="losses-map-key">
              {MODE_LABEL[shownMode]} loss per kilogram of steel over one electrical period; lighter is more loss.
              The scale stops at the 98th percentile; the peak is {peak} W/kg.
            </span>
          </>
        )}
        <span className="losses-map-key">
          <span className="losses-map-swatch is-hatched" aria-hidden="true" /> Not modelled: rotor and magnets.
          {shownMode !== 'copper' && <> <span className="losses-map-swatch" style={{ background: CONTEXT_FILL }} aria-hidden="true" /> Coil sides: choose Copper.</>}
        </span>
      </figcaption>
    </figure>
  );
}

/**
 * Losses and efficiency of a completed run (#138). Renders nothing for a run
 * without a loss breakdown.
 */
export function LossesCard({
  loss,
  iron,
  density,
  plot,
  winding,
  slotCount,
  variant = 'panel',
}: {
  loss?: LossBreakdown | null;
  iron?: IronLoss | null;
  density?: IronLossDensity | null;
  plot?: PublicFieldLinePlot | null;
  winding?: WindingResistance | null;
  slotCount?: number;
  variant?: 'panel' | 'report';
}) {
  const headingId = useId();
  const view = lossesView(loss, iron);
  if (!view) return null;
  const copperWPerKg = stackCopperWPerKg(loss, winding, slotCount ?? 0);
  return (
    <section className={`motor-constants losses-card${variant === 'report' ? ' is-report' : ''}`} aria-labelledby={headingId}>
      <h3 id={headingId}>Losses &amp; efficiency</h3>
      <div className="losses-headline" title={view.efficiency.reason}>
        <span className="losses-headline-label">Efficiency</span>
        <strong>{view.efficiency.text}</strong>
        <StatusBadge status={view.efficiency.status} title={view.efficiency.reason} />
      </div>
      <table>
        <tbody>
          {view.rows.map((row) => (
            <tr key={row.key} title={row.hint}>
              <th scope="row">{row.label}</th>
              <td className="motor-constants-value">{row.value}</td>
              <td className="motor-constants-unit">
                {row.unit}
                {row.status && row.status !== 'qualified' && <StatusBadge status={row.status} title={row.hint} />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {view.segments.length > 0 && <LossBar segments={view.segments} totalW={view.totalW} />}
      {plot && (density || copperWPerKg !== null) && (
        <LossMap
          plot={plot}
          density={density}
          copperWPerKg={copperWPerKg}
          copperStackW={loss?.copper_active_loss_W ?? null}
          copperEndW={loss?.copper_end_winding_loss_W ?? null}
        />
      )}
      <p className="losses-not-modelled">
        Not modelled: magnet and rotor eddy-current loss, AC copper loss (skin and proximity effects), inverter loss
        {loss && loss.mechanical_loss_W > 0 ? '.' : ', and mechanical loss unless entered under Operating point.'}
      </p>
    </section>
  );
}
