import { useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  downloadPerformanceReport,
  type PublicApiError,
} from './api';
import type { MotorConfig, SolveResult } from './model';
import type {
  DriveControl,
  EfficiencyMap,
  PerformanceReportContext,
  PerformanceReportKind,
  TorqueSpeedAnalysisResult,
  TorqueSpeedEnvelope,
} from './performance';
import {
  axisTop,
  currentAt,
  currentUnits,
  curveAt,
  efficiencyAt,
  efficiencyBands,
  efficiencyColor,
  inductanceTable,
  mapCsv,
  niceTicks,
} from './performanceView';
import { isDeratedRun } from './magnetTemperature';
import { formatSignificant } from './numberFormat';
import { StatusSummary } from './OutputStatusBadge';
import { InfoTip } from './Popover';
import {
  FLUX_LINKAGE_MAP_STATUS_REASON,
  MAGNET_TEMPERATURE_STATUS_REASON,
  PHASE_RESISTANCE_UNRECORDED_STATUS_REASON,
  recordStatus,
  type NamedOutputStatus,
} from './outputStatus';

// Categorical slots 1 and 2 of the validated dark palette.
const CURVE_COLORS = { peak: '#3987e5', continuous: '#d95926' } as const;
const REGION_LABEL: Record<string, string> = { mtpa: 'MTPA', field_weakening: 'field weakening', mtpv: 'MTPV' };
const MAX_WIDTH = 760;
const MIN_WIDTH = 280;
const HEIGHT = 250;
// As the waveform charts: the unit above the y axis, the x label at the bottom right.
const MARGIN = { top: 22, right: 14, bottom: 34, left: 44 };

const significant = (value: number, digits = 3) => formatSignificant(value, digits);
// Currents echo the limits as typed: 40 A rms, not 40.0 A rms.
const compact = (value: number) => Number(value.toPrecision(3)).toLocaleString();
const tickText = (value: number) => value.toLocaleString();

function errorText(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) return String((error as PublicApiError).message);
  return 'The local API could not compute the performance map.';
}

/**
 * The chart's own width in viewBox units: its frame's width up to 760, so tick
 * labels keep their size on a narrow window instead of shrinking with the plot.
 */
function useChartWidth() {
  const ref = useRef<HTMLElement>(null);
  const [width, setWidth] = useState(MAX_WIDTH);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, entry.contentRect.width)));
      setWidth((current) => (Math.abs(current - next) > 1 ? next : current));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

function Axes({ width, xMax, yMax, xTicks, xLabel, yUnit }: {
  width: number; xMax: number; yMax: number; xTicks: number; xLabel: string; yUnit: string;
}) {
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  return (
    <g className="performance-axes">
      {niceTicks(yMax, 5).filter((tick) => tick <= yMax + 1e-9).map((tick) => {
        const y = MARGIN.top + plotH * (1 - tick / yMax);
        return (
          <g key={`y${tick}`}>
            <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y} y2={y} className="chart-grid" />
            <text x={MARGIN.left - 8} y={y + 4} textAnchor="end" className="chart-label">{tickText(tick)}</text>
          </g>
        );
      })}
      {niceTicks(xMax, xTicks).filter((tick) => tick <= xMax + 1e-9).map((tick) => {
        const x = MARGIN.left + plotW * (tick / xMax);
        return (
          <g key={`x${tick}`}>
            <line x1={x} x2={x} y1={MARGIN.top} y2={HEIGHT - MARGIN.bottom} className="chart-grid" />
            <text x={x} y={HEIGHT - MARGIN.bottom + 15} textAnchor="middle" className="chart-label">{tickText(tick)}</text>
          </g>
        );
      })}
      <text x={width - MARGIN.right} y={HEIGHT - 4} textAnchor="end" className="chart-label">{xLabel}</text>
      <text x={MARGIN.left} y={12} className="chart-label chart-unit-label">{yUnit}</text>
    </g>
  );
}

/** The run's own operating point: its speed, solved torque and, for sinusoidal current, its current angle. */
interface SolvedPoint {
  speedRpm: number;
  torqueNm: number;
  gammaDeg: number | null;
}

const CONTROL_NOTE: Record<DriveControl, string> = {
  mtpa: 'MTPA: the smallest current for each torque, as most drives run',
  least_loss: 'Least loss: the current with the least copper plus iron loss',
};

/** Whether a point lies inside the plot area, where its marker is drawn. */
function inPlot(width: number, cx: number, cy: number): boolean {
  return Number.isFinite(cx) && Number.isFinite(cy) && cx >= MARGIN.left && cx <= width - MARGIN.right && cy >= MARGIN.top && cy <= HEIGHT - MARGIN.bottom;
}

function SolvedMarker({ width, cx, cy, label }: { width: number; cx: number; cy: number; label: string }) {
  if (!inPlot(width, cx, cy)) return null;
  const right = cx < width - MARGIN.right - 90;
  return (
    <g className="performance-solved-marker" aria-hidden="true">
      <circle cx={cx} cy={cy} r={6} className="performance-solved-ring" />
      <circle cx={cx} cy={cy} r={2} className="performance-solved-dot" />
      <text x={right ? cx + 9 : cx - 9} y={cy - 8} textAnchor={right ? 'start' : 'end'} className="performance-solved-label">{label}</text>
    </g>
  );
}

/** The solved point's legend entry, saying so when it lies beyond the axes and is not drawn. */
function SolvedLegend({ solved, drawn }: { solved: SolvedPoint; drawn: boolean }) {
  return (
    <span className={drawn ? undefined : 'is-off-chart'} title={`Your solved operating point: ${significant(solved.torqueNm)} N·m at ${significant(solved.speedRpm)} rpm`}>
      <i className="performance-solved-swatch" />
      {drawn ? 'Solved point' : `Solved point at ${significant(solved.speedRpm)} rpm, off chart`}
    </span>
  );
}

function usePlotPointer(width: number, xMax: number) {
  const [speed, setSpeed] = useState<number | null>(null);
  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * width;
    const fraction = (svgX - MARGIN.left) / (width - MARGIN.left - MARGIN.right);
    setSpeed(fraction >= 0 && fraction <= 1 ? fraction * xMax : null);
  };
  return { speed, onMove, onLeave: () => setSpeed(null) };
}

function TorqueSpeedChart({ envelope, formatCurrent, solved, compact = false }: {
  envelope: TorqueSpeedEnvelope;
  formatCurrent: (peakA: number) => string;
  solved: SolvedPoint | null;
  compact?: boolean;
}) {
  const { ref, width } = useChartWidth();
  const [quantity, setQuantity] = useState<'torque' | 'power'>('torque');
  const curves = envelope.curves;
  const xTicks = width < 480 ? 3 : 6;
  const xMax = axisTop(Math.max(...curves.map((curve) => curve.max_speed_rpm), 1), xTicks);
  const values = (curve: TorqueSpeedEnvelope['curves'][number]) => (quantity === 'torque' ? curve.torque_Nm : curve.power_W.map((watts) => watts / 1000));
  const yMax = axisTop(Math.max(...curves.flatMap(values), 1e-6) * 1.05, 5);
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (speed: number) => MARGIN.left + plotW * (speed / xMax);
  const y = (value: number) => MARGIN.top + plotH * (1 - value / yMax);
  const pointer = usePlotPointer(width, xMax);
  const peak = curves.find((curve) => curve.limit === 'peak') ?? curves[0];
  // MTPA can hold up to the top speed; then there is no base speed on the chart.
  const baseReached = peak.base_speed_rpm < envelope.limits.max_speed_rpm * (1 - 1e-6);
  const unit = quantity === 'torque' ? 'N·m' : 'kW';
  const solvedY = solved ? y(quantity === 'torque' ? solved.torqueNm : (solved.torqueNm * solved.speedRpm * 2 * Math.PI) / 60 / 1000) : NaN;
  const solvedDrawn = solved !== null && inPlot(width, x(solved.speedRpm), solvedY);
  const readout = pointer.speed === null ? null : curves.map((curve) => {
    const at = curveAt(curve, pointer.speed as number);
    if (!at) return `${curve.limit === 'peak' ? 'Peak' : 'Continuous'} —`;
    const value = quantity === 'torque' ? at.torque : at.power / 1000;
    return `${curve.limit === 'peak' ? 'Peak' : 'Continuous'} ${significant(value)} ${unit} at ${formatCurrent(at.currentPeakA)}, γ ${Math.round(at.gammaDeg)}° (${REGION_LABEL[at.region] ?? at.region})`;
  });
  return (
    <figure ref={ref} className={`chart-shell performance-chart${compact ? ' public-compact-torque-speed' : ''}`}>
      <div className="chart-heading performance-chart-heading">
        <span>{quantity === 'torque' ? 'Torque–speed' : 'Power–speed'} envelope</span>
        <span className="public-waveform-legend" aria-label="Envelope curves">
          {curves.map((curve) => (
            <span key={curve.limit}>
              <i style={{ backgroundColor: CURVE_COLORS[curve.limit] }} />
              {curve.limit === 'peak' ? 'Peak' : 'Continuous'} {formatCurrent(curve.limit === 'peak' ? envelope.limits.peak_current_A : envelope.limits.continuous_current_A ?? 0)}
            </span>
          ))}
          {solved && <SolvedLegend solved={solved} drawn={solvedDrawn} />}
        </span>
        {!compact && <span className="performance-toggle" role="group" aria-label="Envelope quantity">
          <button type="button" aria-pressed={quantity === 'torque'} onClick={() => setQuantity('torque')}>Torque</button>
          <button type="button" aria-pressed={quantity === 'power'} onClick={() => setQuantity('power')}>Power</button>
        </span>}
      </div>
      <p className="performance-readout" aria-live="polite">
        {pointer.speed === null ? '' : `${significant(pointer.speed)} rpm · ${readout?.join(' · ')}`}
      </p>
      <svg viewBox={`0 0 ${width} ${HEIGHT}`} role="img" aria-label={`${quantity === 'torque' ? 'Torque' : 'Power'} against speed for the drive limits`} onPointerMove={pointer.onMove} onPointerLeave={pointer.onLeave}>
        <Axes width={width} xMax={xMax} yMax={yMax} xTicks={xTicks} xLabel="speed, rpm" yUnit={unit} />
        {baseReached && (
          <>
            <line x1={x(peak.base_speed_rpm)} x2={x(peak.base_speed_rpm)} y1={MARGIN.top} y2={HEIGHT - MARGIN.bottom} className="performance-base-line" />
            <text x={x(peak.base_speed_rpm) + 4} y={MARGIN.top + 10} className="chart-label">base</text>
          </>
        )}
        {curves.map((curve) => (
          <path
            key={curve.limit}
            d={curve.speed_rpm.map((speed, index) => `${index ? 'L' : 'M'} ${x(speed).toFixed(1)} ${y(values(curve)[index]).toFixed(1)}`).join(' ')}
            fill="none"
            stroke={CURVE_COLORS[curve.limit]}
            strokeWidth={2}
            strokeLinejoin="round"
          />
        ))}
        {solved && <SolvedMarker width={width} cx={x(solved.speedRpm)} cy={solvedY} label="solved" />}
        {pointer.speed !== null && <line x1={x(pointer.speed)} x2={x(pointer.speed)} y1={MARGIN.top} y2={HEIGHT - MARGIN.bottom} className="performance-crosshair" />}
        {pointer.speed !== null && curves.map((curve) => {
          const at = curveAt(curve, pointer.speed as number);
          if (!at) return null;
          const value = quantity === 'torque' ? at.torque : at.power / 1000;
          return <circle key={curve.limit} cx={x(pointer.speed as number)} cy={y(value)} r={4} fill={CURVE_COLORS[curve.limit]} className="performance-marker" />;
        })}
      </svg>
    </figure>
  );
}

function PartialMapNotice({ analysis }: { analysis: TorqueSpeedAnalysisResult }) {
  const failed = analysis.map.points.filter((point) => point.status !== 'ok');
  const download = () => {
    const url = URL.createObjectURL(new Blob([mapCsv(analysis.map)], { type: 'text/csv' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'coilem-partial-flux-linkage-map.csv';
    link.click();
    URL.revokeObjectURL(url);
  };
  return <section className="performance-panel is-partial" aria-label="Incomplete torque–speed map">
    <h3>Torque–speed map incomplete</h3>
    <p className="performance-message">{analysis.status_reason ?? 'Some map points have no solved result.'}</p>
    <p className="performance-message">Completed analyses and map points are saved. Curves need every point to succeed. Run the same analysis again to retry failed points.</p>
    <ul className="performance-partial-points">{failed.map((point) => <li key={`${point.current_peak_A}-${point.gamma_deg}`}>
      {point.current_peak_A} A peak, {point.gamma_deg}°: {point.error ?? point.status}
    </li>)}</ul>
    <div className="performance-actions"><button type="button" onClick={download}>Export partial map CSV</button></div>
  </section>;
}

export function CompactTorqueSpeedChart({ analysis, currentConvention }: {
  analysis: TorqueSpeedAnalysisResult;
  currentConvention?: string | null;
}) {
  const units = currentUnits(currentConvention);
  if (!analysis.envelope) return <PartialMapNotice analysis={analysis} />;
  return <TorqueSpeedChart envelope={analysis.envelope} solved={null} compact
    formatCurrent={(peakA) => `${compact(units.fromPeak(peakA))} ${units.unit}`} />;
}

function EfficiencyMapChart({ map, envelope, solved, formatCurrent }: {
  map: EfficiencyMap; envelope: TorqueSpeedEnvelope; solved: SolvedPoint | null; formatCurrent: (peakA: number) => string;
}) {
  const { ref, width } = useChartWidth();
  const bands = useMemo(() => efficiencyBands(map), [map]);
  const [hover, setHover] = useState<{ row: number; column: number } | null>(null);
  const speeds = map.speed_rpm;
  const torques = map.torque_Nm;
  const xTicks = width < 480 ? 3 : 6;
  const xMax = axisTop(speeds[speeds.length - 1], xTicks);
  const yMax = axisTop(torques[torques.length - 1] * 1.05, 5);
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (speed: number) => MARGIN.left + plotW * (speed / xMax);
  const y = (torque: number) => MARGIN.top + plotH * (1 - torque / yMax);
  const cellW = plotW * ((speeds[1] - speeds[0]) / xMax);
  const cellH = plotH * ((torques[1] - torques[0]) / yMax);
  const peak = envelope.curves.find((curve) => curve.limit === 'peak') ?? envelope.curves[0];
  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const speed = (((event.clientX - rect.left) / rect.width) * width - MARGIN.left) / plotW * xMax;
    const torque = (1 - (((event.clientY - rect.top) / rect.height) * HEIGHT - MARGIN.top) / plotH) * yMax;
    const column = Math.round((speed - speeds[0]) / (speeds[1] - speeds[0]));
    const row = Math.round((torque - torques[0]) / (torques[1] - torques[0]));
    setHover(row >= 0 && row < torques.length && column >= 0 && column < speeds.length && map.efficiency_pct[row][column] !== null ? { row, column } : null);
  };
  const cell = hover ? {
    eta: map.efficiency_pct[hover.row][hover.column] as number,
    copper: map.copper_loss_W[hover.row][hover.column],
    iron: map.iron_loss_W[hover.row][hover.column],
    current: currentAt(map, speeds[hover.column], torques[hover.row]),
  } : null;
  const describeCurrent = (current: ReturnType<typeof currentAt>) => (current
    ? `${formatCurrent(current.rmsA * Math.SQRT2)}${current.gammaDeg !== null ? `, γ ${Math.round(current.gammaDeg)}°` : ''}`
    : '');
  const legendStops = [];
  for (let value = bands.floor; value < bands.top; value += bands.step) legendStops.push(value);
  const solvedEta = solved ? efficiencyAt(map, solved.speedRpm, solved.torqueNm) : null;
  const solvedCurrent = solved ? currentAt(map, solved.speedRpm, solved.torqueNm) : null;
  const solvedAngleNote = solved?.gammaDeg != null && solvedCurrent?.gammaDeg != null && Math.abs(solved.gammaDeg - solvedCurrent.gammaDeg) > 3
    ? ` Your solve used γ ${Math.round(solved.gammaDeg)}°, so its efficiency on the Losses card differs.`
    : '';
  return (
    <figure ref={ref} className="chart-shell performance-chart">
      <div className="chart-heading performance-chart-heading">
        <span>Efficiency map</span>
        <InfoTip label="About the efficiency map">
          <p>{CONTROL_NOTE[map.control ?? 'mtpa']}. Blank above the peak envelope. Hover the map for the efficiency, current and losses at a point.</p>
          {solved && solvedEta !== null && (
            <p>
              Solved point ({significant(solved.speedRpm)} rpm, {significant(solved.torqueNm)} N·m): {solvedEta.toFixed(1)}%
              {solvedCurrent ? ` at ${describeCurrent(solvedCurrent)}` : ''}.{solvedAngleNote}
            </p>
          )}
        </InfoTip>
        <span
          className="performance-band-legend"
          role="img"
          aria-label={`Efficiency bands of ${bands.step} points from ${bands.floor}% to ${bands.top}%`}
          title={`Efficiency bands of ${bands.step} points`}
        >
          <small>≤ {bands.floor}</small>
          <span>{legendStops.map((value) => <span key={value} style={{ background: efficiencyColor(value, bands) }} />)}</span>
          <small>{bands.top} %</small>
        </span>
      </div>
      <p className="performance-readout" aria-live="polite">
        {cell && hover
          ? `${significant(cell.eta, 3)}% at ${significant(speeds[hover.column])} rpm, ${significant(torques[hover.row])} N·m · ${cell.current ? `${describeCurrent(cell.current)} · ` : ''}copper ${significant(cell.copper ?? 0)} W · iron ${significant(cell.iron ?? 0)} W`
          : ''}
      </p>
      <svg viewBox={`0 0 ${width} ${HEIGHT}`} role="img" aria-label={`Efficiency over speed and torque, from ${bands.floor}% to ${bands.top}%`} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        {map.efficiency_pct.map((row, rowIndex) => row.map((eta, columnIndex) => (eta === null ? null : (
          <rect
            key={`${rowIndex}-${columnIndex}`}
            x={x(speeds[columnIndex]) - cellW / 2}
            y={y(torques[rowIndex]) - cellH / 2}
            width={cellW + 0.6}
            height={cellH + 0.6}
            fill={efficiencyColor(eta, bands)}
          />
        ))))}
        <Axes width={width} xMax={xMax} yMax={yMax} xTicks={xTicks} xLabel="speed, rpm" yUnit="N·m" />
        <path d={peak.speed_rpm.map((speed, index) => `${index ? 'L' : 'M'} ${x(speed).toFixed(1)} ${y(peak.torque_Nm[index]).toFixed(1)}`).join(' ')} fill="none" className="performance-envelope-line" />
        {hover && <rect x={x(speeds[hover.column]) - cellW / 2} y={y(torques[hover.row]) - cellH / 2} width={cellW} height={cellH} className="performance-cell-focus" />}
        {solved && <SolvedMarker width={width} cx={x(solved.speedRpm)} cy={y(solved.torqueNm)} label={solvedEta !== null ? `solved, ${solvedEta.toFixed(1)}%` : 'solved'} />}
      </svg>
    </figure>
  );
}

/** The four downloads behind one button; each item names what it holds. */
function ExportMenu({ disabled, downloading, onReport, onMapCsv }: {
  disabled: boolean;
  downloading: PerformanceReportKind | null;
  onReport: (kind: PerformanceReportKind) => void;
  onMapCsv: () => void;
}) {
  const [open, setOpen] = useState(false);
  // Opens leftward from the button, or rightward when the button sits near the window's left edge.
  const [alignStart, setAlignStart] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  useEffect(() => {
    if (!open) return undefined;
    const close = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [open]);
  const items: Array<{ key: string; label: string; busy: string; description: string; run: () => void; needsDrive: boolean }> = [
    { key: 'pdf', label: 'PDF report', busy: 'Preparing PDF…', description: 'Inputs, curves, efficiency map, MTPA trajectory and Ld/Lq as a PDF report', run: () => onReport('pdf'), needsDrive: true },
    { key: 'csv', label: 'Performance CSV', busy: 'Preparing CSV…', description: 'Every number and curve sample of the report, long-form like the run CSV', run: () => onReport('csv'), needsDrive: true },
    { key: 'idiq', label: 'id/iq table', busy: 'Preparing table…', description: 'λd, λq and torque on a rectangular id × iq grid, for drive-control models', run: () => onReport('idiq'), needsDrive: true },
    { key: 'map', label: 'Map points CSV', busy: '', description: "The map's solved points as they are", run: onMapCsv, needsDrive: false },
  ];
  return (
    <div
      ref={rootRef}
      className="performance-export"
      onKeyDown={(event) => { if (event.key === 'Escape' && open) { event.stopPropagation(); setOpen(false); } }}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={(event) => {
          setAlignStart(event.currentTarget.getBoundingClientRect().right < 312);
          setOpen((value) => !value);
        }}
      >
        {downloading ? 'Preparing…' : 'Export'}<span aria-hidden="true"> ▾</span>
      </button>
      <div id={menuId} className={`performance-export-menu${alignStart ? ' is-start' : ''}`} role="group" aria-label="Downloads" hidden={!open}>
        {items.map((item) => (
          <button
            key={item.key}
            type="button"
            aria-describedby={`${menuId}-${item.key}`}
            disabled={(item.needsDrive && disabled) || downloading !== null}
            onClick={() => { setOpen(false); item.run(); }}
          >
            <span>{downloading === item.key ? item.busy : item.label}</span>
            <small id={`${menuId}-${item.key}`} aria-hidden="true">{item.description}</small>
          </button>
        ))}
      </div>
    </div>
  );
}

/** Read the immutable map and drive curves saved with this analysis. */
export function PerformancePanel({ config, result, designName }: { config: MotorConfig; result: SolveResult; designName: string | null }) {
  const headingId = useId();
  const [downloading, setDownloading] = useState<PerformanceReportKind | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const analysis = result.torque_speed_analysis;
  if (!analysis) return null;
  const { settings, map, envelope, efficiency_map: efficiency, winding_resistance: winding } = analysis;
  if (!envelope || !efficiency) return <PartialMapNotice analysis={analysis} />;
  const drive = { envelope, efficiency_map: efficiency };
  const units = currentUnits(config.solve_params.current_amplitude_convention);
  const formatCurrent = (peakA: number) => `${compact(units.fromPeak(peakA))} ${units.unit}`;
  const resistance = winding?.phase_resistance_ohm ?? 0;
  const temperature = winding?.winding_temperature_C ?? 20;
  const resistanceStatus = recordStatus(winding, PHASE_RESISTANCE_UNRECORDED_STATUS_REASON);
  const magnetsDerated = isDeratedRun(result.solve_metadata);
  const solvedPoint: SolvedPoint | null = typeof result.summary.avg_torque_Nm === 'number' && result.summary.avg_torque_Nm > 0
    ? { speedRpm: config.solve_params.rated_speed_rpm, torqueNm: result.summary.avg_torque_Nm,
      gammaDeg: config.solve_params.excitation_mode === 'sinusoidal' ? config.solve_params.current_angle_deg : null }
    : null;
  const agreement = analysis.torque_agreement_pct.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  const agreementText = agreement.length > 0
    ? `FEM torque is ${Math.min(...agreement).toFixed(1)}–${Math.max(...agreement).toFixed(1)}% of the d/q torque across ${agreement.length} map points.`
    : null;
  const inductances = inductanceTable(map);
  const peak = envelope.curves.find((curve) => curve.limit === 'peak') ?? null;
  const bestEfficiency = Math.max(...efficiency.efficiency_pct.flat().filter((value): value is number => value !== null));
  const baseReached = peak !== null && peak.base_speed_rpm < envelope.limits.max_speed_rpm * (1 - 1e-6);
  const statuses: NamedOutputStatus[] = [
    { key: 'envelope', label: 'Torque–speed envelope', status: envelope.status, reason: envelope.status_reason ?? '' },
    { key: 'efficiency', label: 'Efficiency map', status: efficiency.status, reason: efficiency.status_reason ?? '' },
    { key: 'dq', label: 'Map flux linkage, MTPA and Ld, Lq', status: 'experimental', reason: FLUX_LINKAGE_MAP_STATUS_REASON },
    ...(winding ? [{ key: 'resistance', label: 'Phase resistance and copper loss', ...resistanceStatus }] : []),
  ];
  const downloadCsv = () => {
    const url = URL.createObjectURL(new Blob([mapCsv(map)], { type: 'text/csv' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(designName ?? 'coilem-design').replace(/[^A-Za-z0-9._-]+/g, '-')}-flux-linkage-map.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };
  const downloadReport = async (kind: PerformanceReportKind) => {
    const context: PerformanceReportContext = {
      design_name: designName, current_unit: units.unit, dc_bus_source: 'entered', map_preset: settings.preset,
      solved_point: solvedPoint ? { speed_rpm: solvedPoint.speedRpm, torque_Nm: solvedPoint.torqueNm, current_angle_deg: solvedPoint.gammaDeg } : null,
      magnet_temperature_derated: magnetsDerated,
      phase_resistance: winding ? resistanceStatus : null,
      magnet_temperature: magnetsDerated ? {
        status: result.solve_metadata.magnet_temperature_status ?? 'experimental',
        reason: result.solve_metadata.magnet_temperature_status_reason ?? MAGNET_TEMPERATURE_STATUS_REASON,
      } : null,
    };
    setDownloading(kind);
    setMessage(null);
    try {
      await downloadPerformanceReport(kind, {
        map, limits: settings.limits, control: settings.control, phase_resistance_ohm: resistance,
        winding_temperature_C: temperature, mechanical_loss_W: analysis.mechanical_loss_W, context,
      });
    } catch (error) { setMessage(errorText(error)); }
    finally { setDownloading(null); }
  };
  return (
    <section className="performance-panel" aria-labelledby={headingId}>
      <header className="performance-header results-card-heading">
        <h3 id={headingId}>Torque–speed and efficiency</h3>
        <StatusSummary statuses={statuses} />
        <InfoTip label="How the curves are computed">
          <p>This design was solved over sinusoidal currents and current angles, then evaluated within the saved drive limits.</p>
          <p>Change the limits or grid in Solve → Analysis → Torque–speed map. Completed points are reused.</p>
        </InfoTip>
        <span className="performance-header-spacer" />
        <span className="performance-map-chip">Map · {map.points.length} pts</span>
        <ExportMenu disabled={false} downloading={downloading} onReport={(kind) => void downloadReport(kind)} onMapCsv={downloadCsv} />
      </header>
      <dl className="performance-settings-summary" aria-label="Saved map settings">
        <div><dt>Peak current</dt><dd>{formatCurrent(settings.limits.peak_current_A)}</dd></div>
        <div><dt>Continuous current</dt><dd>{settings.limits.continuous_current_A ? formatCurrent(settings.limits.continuous_current_A) : '—'}</dd></div>
        <div><dt>DC bus</dt><dd>{settings.limits.dc_bus_V} V</dd></div>
        <div><dt>Top speed</dt><dd>{settings.limits.max_speed_rpm} rpm</dd></div>
        <div><dt>Control</dt><dd>{settings.control === 'mtpa' ? 'MTPA' : 'Least loss'}</dd></div>
        <div><dt>Grid</dt><dd>{settings.preset === 'preview' ? 'Preview 5×7' : 'Standard 7×10'}</dd></div>
      </dl>
      {message && <p className="performance-message is-error" role="alert">{message}</p>}
      {drive && peak && (
        <>
          <div className="performance-stats">
            <div><span>Peak torque</span><strong>{significant(peak.torque_Nm[0])}<small>N·m</small></strong></div>
            <div><span>Peak power</span><strong>{significant(peak.peak_power_W / 1000)}<small>kW</small></strong></div>
            <div title={baseReached ? undefined : `Base speed lies above the ${significant(drive.envelope.limits.max_speed_rpm)} rpm top speed: MTPA holds over the whole range.`}>
              <span>Base → top speed</span>
              <strong>
                {baseReached ? `${significant(peak.base_speed_rpm)} → ${significant(peak.max_speed_rpm)}` : `> ${significant(peak.max_speed_rpm)}`}
                <small>rpm</small>
              </strong>
            </div>
            <div><span>Best efficiency</span><strong>{bestEfficiency !== null && Number.isFinite(bestEfficiency) ? bestEfficiency.toFixed(1) : '—'}<small>%</small></strong></div>
          </div>
          <TorqueSpeedChart envelope={drive.envelope} formatCurrent={formatCurrent} solved={solvedPoint} />
          <EfficiencyMapChart map={drive.efficiency_map} envelope={drive.envelope} solved={solvedPoint} formatCurrent={formatCurrent} />
          {inductances.length > 0 && (
            <details className="performance-details">
              <summary>Map details: Ld, Lq and torque check</summary>
              <table className="performance-inductance">
                <caption>
                  Apparent inductance against current
                  <InfoTip label="How Ld and Lq are found">
                    <p>Ld from the 90° points, (λd − λpm) / id; Lq from the 0° points, λq / iq. Both are secant values and include saturation.</p>
                  </InfoTip>
                </caption>
                <thead><tr><th scope="col">Current</th><th scope="col">Ld</th><th scope="col">Lq</th></tr></thead>
                <tbody>
                  {inductances.map((row) => (
                    <tr key={row.currentA}>
                      <th scope="row">{formatCurrent(row.currentA)}</th>
                      <td>{row.ldH === null ? '—' : <>{significant(row.ldH * 1000)} <small>mH</small></>}</td>
                      <td>{row.lqH === null ? '—' : <>{significant(row.lqH * 1000)} <small>mH</small></>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {agreementText && <p className="performance-details-note">{agreementText}</p>}
            </details>
          )}
        </>
      )}
    </section>
  );
}
