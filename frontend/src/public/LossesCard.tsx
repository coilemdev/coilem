import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { PublicFieldLinePlot } from './model';
import type { IronLoss, IronLossDensity, LossBreakdown, PerformanceOutputStatus } from './performance';
import { densityColor, formatPower, lossesView, type LossSegment } from './lossesView';

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

interface PreparedDensity {
  triangles: Array<{ points: Array<[number, number]>; value: number | null; air: boolean }>;
  bounds: { minX: number; minY: number; span: number };
  /** Top of the color scale: the 98th percentile, so a few tooth-tip elements do not flatten the rest. */
  scaleMax: number;
  peak: number;
}

function prepareDensity(plot: PublicFieldLinePlot, density: IronLossDensity): PreparedDensity | null {
  if (plot.triangles.length !== density.element_w_per_kg.length || density.max_w_per_kg <= 0) return null;
  let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
  const triangles: PreparedDensity['triangles'] = [];
  plot.triangles.forEach((triangle, index) => {
    const points = triangle.map((node) => plot.nodes_mm[node]).filter(Boolean) as Array<[number, number]>;
    if (points.length !== 3) return;
    for (const [x, y] of points) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    const region = plot.regions[index] ?? '';
    triangles.push({ points, value: density.element_w_per_kg[index] ?? null, air: region === 'airgap' || region.includes('air') });
  });
  const span = Math.max(maxX - minX, maxY - minY);
  const values = triangles.flatMap((triangle) => (triangle.value === null ? [] : [triangle.value])).sort((a, b) => a - b);
  if (!triangles.length || !(span > 0) || !values.length) return null;
  const scaleMax = values[Math.floor(0.98 * (values.length - 1))] || density.max_w_per_kg;
  return { triangles, bounds: { minX, minY, span }, scaleMax, peak: density.max_w_per_kg };
}

function contains(point: [number, number], [a, b, c]: Array<[number, number]>): boolean {
  const det = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]);
  if (det === 0) return false;
  const u = ((c[1] - a[1]) * (point[0] - a[0]) - (c[0] - a[0]) * (point[1] - a[1])) / det;
  const v = ((b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])) / det;
  return u >= 0 && v >= 0 && u + v <= 1;
}

function DensityMap({ plot, density }: { plot: PublicFieldLinePlot; density: IronLossDensity }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const prepared = useMemo(() => prepareDensity(plot, density), [plot, density]);
  const [readout, setReadout] = useState<string | null>(null);
  const size = 240;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !prepared) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = size * ratio;
    canvas.height = size * ratio;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, size, size);
    const { minX, minY, span } = prepared.bounds;
    const scale = (size * 0.96) / span;
    const offset = size * 0.02;
    for (const triangle of prepared.triangles) {
      if (triangle.air && triangle.value === null) continue;
      context.beginPath();
      triangle.points.forEach(([x, y], index) => {
        const px = offset + (x - minX) * scale;
        const py = size - (offset + (y - minY) * scale);
        if (index === 0) context.moveTo(px, py); else context.lineTo(px, py);
      });
      context.closePath();
      context.fillStyle = triangle.value === null ? '#252a33' : densityColor(triangle.value / prepared.scaleMax);
      context.fill();
    }
  }, [prepared]);

  if (!prepared) return null;
  const onMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const { minX, minY, span } = prepared.bounds;
    const scale = (size * 0.96) / span;
    const x = minX + ((event.clientX - rect.left) * (size / rect.width) - size * 0.02) / scale;
    const y = minY + (size - (event.clientY - rect.top) * (size / rect.height) - size * 0.02) / scale;
    const hit = prepared.triangles.find((triangle) => triangle.value !== null && contains([x, y], triangle.points));
    setReadout(hit && hit.value !== null ? `${Number(hit.value.toPrecision(3))} W/kg here` : null);
  };
  const maxText = Number(prepared.scaleMax.toPrecision(3));
  const peakText = Number(prepared.peak.toPrecision(3));
  return (
    <figure className="losses-density">
      <canvas
        ref={canvasRef}
        style={{ width: size, height: size }}
        role="img"
        aria-label={`Iron loss per kilogram across the stator, peaking at ${peakText} W/kg`}
        onMouseMove={onMove}
        onMouseLeave={() => setReadout(null)}
      />
      <figcaption>
        <span className="losses-density-scale" aria-hidden="true" />
        <span className="losses-density-labels"><span>0</span><span>≥ {maxText} W/kg</span></span>
        <span className="losses-density-readout">
          {readout ?? `Iron loss per kilogram over one electrical period. The scale stops at the 98th percentile; the peak is ${peakText} W/kg. Grey has no iron-loss model.`}
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
  variant = 'panel',
}: {
  loss?: LossBreakdown | null;
  iron?: IronLoss | null;
  density?: IronLossDensity | null;
  plot?: PublicFieldLinePlot | null;
  variant?: 'panel' | 'report';
}) {
  const headingId = useId();
  const view = lossesView(loss, iron);
  if (!view) return null;
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
      {density && plot && <DensityMap plot={plot} density={density} />}
    </section>
  );
}
