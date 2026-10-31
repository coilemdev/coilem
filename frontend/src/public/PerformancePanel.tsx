import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  cancelPublicSolve,
  computeDrivePerformance,
  downloadPerformanceReport,
  getPerformanceMapStatus,
  type PublicApiError,
  type PublicSolveRequest,
} from './api';
import {
  currentMapJob,
  mapJobKey,
  recallPanelInputs,
  rememberPanelInputs,
  startMapJob,
  subscribeMapJob,
  type MapJob,
} from './mapJob';
import type { MotorConfig, SolveResult } from './model';
import type {
  DriveControl,
  DriveLimits,
  DrivePerformance,
  EfficiencyMap,
  FluxLinkageMapPayload,
  MapSettings,
  PerformanceMapStatus,
  PerformanceReportContext,
  PerformanceReportKind,
  TorqueSpeedEnvelope,
} from './performance';
import {
  axisTop,
  currentAt,
  currentUnits,
  curveAt,
  defaultDriveLimits,
  efficiencyAt,
  efficiencyBands,
  efficiencyColor,
  estimateMapSeconds,
  formatDuration,
  inductanceTable,
  mapCsv,
  niceTicks,
} from './performanceView';
import { asPublicConfig } from './publicRequest';
import { isDeratedRun } from './magnetTemperature';
import { formatSignificant } from './numberFormat';
import { StatusSummary } from './OutputStatusBadge';
import { InfoTip, Popover } from './Popover';
import {
  DQ_FLUX_LINKAGE_STATUS_REASON,
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
const ENVELOPE_STATUS_REASON = 'Interpolated from a flux-linkage map; not yet compared with measured data.';

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

function TorqueSpeedChart({ envelope, formatCurrent, solved }: { envelope: TorqueSpeedEnvelope; formatCurrent: (peakA: number) => string; solved: SolvedPoint | null }) {
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
    <figure ref={ref} className="chart-shell performance-chart">
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
        <span className="performance-toggle" role="group" aria-label="Envelope quantity">
          <button type="button" aria-pressed={quantity === 'torque'} onClick={() => setQuantity('torque')}>Torque</button>
          <button type="button" aria-pressed={quantity === 'power'} onClick={() => setQuantity('power')}>Power</button>
        </span>
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

/**
 * A drive-limit input with its label, its explanation behind an "i", and its
 * unit and any tag (estimated, = solved) inside the field, so every label row
 * stays one short line and the inputs line up.
 */
function LimitField({ label, unit, hint, tag, estimated, children }: {
  label: string;
  unit?: string;
  hint?: React.ReactNode;
  tag?: React.ReactNode;
  estimated?: boolean;
  children: (id: string) => React.ReactNode;
}) {
  const id = useId();
  return (
    <div className={`performance-field${estimated ? ' is-estimated' : ''}`}>
      <div className="performance-field-label">
        <label htmlFor={id}>{label}</label>
        {hint && <InfoTip label={`About ${label}`}>{hint}</InfoTip>}
      </div>
      <div className="performance-input">
        {children(id)}
        {tag}
        {unit && <span className="performance-input-unit">{unit}</span>}
      </div>
    </div>
  );
}

type Phase = 'checking' | 'idle' | 'solving' | 'computing' | 'ready' | 'error';

/**
 * Torque–speed, power–speed and efficiency over the operating range (#142),
 * from a flux-linkage map of this design (#139) and the drive limits.
 */
export function PerformancePanel({ config, result, designName }: { config: MotorConfig; result: SolveResult; designName: string | null }) {
  const headingId = useId();
  const summary = result.summary;
  const winding = summary.winding_resistance;
  const losses = summary.loss_breakdown;
  const request: PublicSolveRequest = useMemo(() => ({
    config: asPublicConfig(config),
    solver: 'magneto2d',
    project_name: designName ?? `coilEM-${config.topology.toLowerCase()}-${config.rotor.pole_count}p${config.stator.slot_count}s`,
  }), [config, designName]);
  const designKey = useMemo(() => JSON.stringify(request), [request]);
  // Currents are shown in the Solve page's units; limits stay in peak amperes for the API.
  const units = useMemo(() => currentUnits(config.solve_params.current_amplitude_convention), [config.solve_params.current_amplitude_convention]);
  const formatCurrent = useCallback((peakA: number) => `${compact(units.fromPeak(peakA))} ${units.unit}`, [units]);
  const designBus = config.solve_params.motor_input_dc_bus_V;
  const busFromDesign = typeof designBus === 'number' && designBus > 0;
  // Inputs survive the panel closing (another plot tab, or back to Solve).
  const [limits, setLimits] = useState<DriveLimits>(() => recallPanelInputs(designKey)?.limits ?? defaultDriveLimits({
    ratedSpeedRpm: config.solve_params.rated_speed_rpm,
    phaseCurrentRmsA: losses?.phase_current_rms_A,
    backEmfRmsV: summary.back_emf_fundamental_V,
    dcBusV: designBus,
    shownUnitPeakA: units.toPeak(1),
  }));
  const [preset, setPreset] = useState<MapSettings['preset']>(() => recallPanelInputs(designKey)?.preset ?? 'preview');
  const [busEdited, setBusEdited] = useState<boolean>(() => recallPanelInputs(designKey)?.busEdited ?? false);
  const [control, setControl] = useState<DriveControl>(() => recallPanelInputs(designKey)?.control ?? 'mtpa');
  useEffect(() => { rememberPanelInputs(designKey, { limits, preset, busEdited, control }); }, [designKey, limits, preset, busEdited, control]);
  const busEstimated = !busFromDesign && !busEdited;
  const solvedRmsA = losses?.phase_current_rms_A ?? null;
  const solvedShown = solvedRmsA !== null ? units.fromPeak(solvedRmsA * Math.SQRT2) : null;
  const ratedSpeed = config.solve_params.rated_speed_rpm;
  const solvedPoint: SolvedPoint | null = ratedSpeed > 0 && Number.isFinite(summary.avg_torque_Nm) && summary.avg_torque_Nm > 0
    ? {
      speedRpm: ratedSpeed,
      torqueNm: summary.avg_torque_Nm,
      gammaDeg: config.solve_params.excitation_mode === 'sinusoidal' ? config.solve_params.current_angle_deg : null,
    }
    : null;
  const [phase, setPhase] = useState<Phase>('checking');
  const [status, setStatus] = useState<PerformanceMapStatus | null>(null);
  const [mapPayload, setMapPayload] = useState<FluxLinkageMapPayload | null>(null);
  const [drive, setDrive] = useState<DrivePerformance | null>(null);
  // The request behind the curves on screen; the downloads rebuild exactly these.
  const [driveBody, setDriveBody] = useState<Record<string, unknown> | null>(null);
  const [downloading, setDownloading] = useState<PerformanceReportKind | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [job, setJob] = useState<MapJob | null>(() => currentMapJob());
  useEffect(() => subscribeMapJob(setJob), []);
  const settings: MapSettings = useMemo(() => ({ preset, peak_current_A: limits.peak_current_A }), [preset, limits.peak_current_A]);
  const jobKey = useMemo(() => mapJobKey(request, settings), [request, settings]);
  // The map for this design and grid, if one has run since the app opened; it keeps
  // running while this panel is closed.
  const myJob = job?.key === jobKey ? job : null;
  const solving = myJob?.phase === 'solving';
  const otherSolving = job?.phase === 'solving' && !myJob;
  const resistance = winding?.phase_resistance_ohm ?? losses?.phase_resistance_ohm ?? null;
  // The tab and its report both show the winding record's own status.
  const resistanceStatus = recordStatus(winding, PHASE_RESISTANCE_UNRECORDED_STATUS_REASON);
  const magnetsDerated = isDeratedRun(result.solve_metadata);
  const windingTemperature = winding?.winding_temperature_C ?? losses?.winding_temperature_C ?? 20;
  const driveRequestId = useRef(0);
  useEffect(() => () => { driveRequestId.current += 1; }, []);

  const computeDrive = useCallback(async (payload: FluxLinkageMapPayload, driveLimits: DriveLimits, driveControl: DriveControl = control) => {
    const requestId = ++driveRequestId.current;
    setPhase('computing');
    setMessage(null);
    const body = {
      map: payload.map,
      limits: driveLimits,
      phase_resistance_ohm: resistance ?? 0,
      winding_temperature_C: windingTemperature,
      mechanical_loss_W: losses?.mechanical_loss_W ?? 0,
      control: driveControl,
    };
    try {
      const next = await computeDrivePerformance(body);
      if (requestId !== driveRequestId.current) return;
      setDrive(next);
      setDriveBody(body);
      setPhase('ready');
    } catch (error) {
      if (requestId !== driveRequestId.current) return;
      setDrive(null);
      setDriveBody(null);
      setMessage(errorText(error));
      setPhase('error');
    }
  }, [resistance, windingTemperature, losses?.mechanical_loss_W, control]);

  // Look up a stored map whenever the grid changes; a finished one goes straight to the curves.
  useEffect(() => {
    let current = true;
    driveRequestId.current += 1;
    setDrive(null);
    setDriveBody(null);
    if (solving) return () => { current = false; };
    setPhase('checking');
    const timer = window.setTimeout(() => {
      getPerformanceMapStatus(request, settings).then((next) => {
        if (!current) return;
        setStatus(next);
        if (next.map) {
          const payload = { map: next.map, torque_agreement_pct: next.torque_agreement_pct ?? [] };
          setMapPayload(payload);
          void computeDrive(payload, limits);
        } else {
          setMapPayload(null);
          setDrive(null);
          setPhase('idle');
        }
      }).catch((error) => {
        if (!current) return;
        setMessage(errorText(error));
        setPhase('error');
      });
    }, 300);
    return () => { current = false; window.clearTimeout(timer); };
    // Limits other than the peak current only need the curves recomputed (Apply).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request, settings, solving]);

  // A map that finished, failed or was cancelled while this panel was open or closed.
  const handledJob = useRef<MapJob | null>(null);
  useEffect(() => {
    if (!myJob || myJob.phase === 'solving' || handledJob.current === myJob) return;
    handledJob.current = myJob;
    if (myJob.phase === 'done' && myJob.payload) {
      setMapPayload(myJob.payload);
      setStatus((previous) => (previous ? { ...previous, map: myJob.payload!.map, solves_finished: previous.solves_total } : previous));
      void computeDrive(myJob.payload, limits);
    } else if (myJob.phase === 'cancelled') {
      setMessage('Map cancelled. Finished points are kept; solving the map again resumes from them.');
      setPhase('idle');
    } else if (myJob.phase === 'error') {
      setMessage(myJob.error?.message ?? 'The map stopped with an error.');
      setPhase('error');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [myJob]);

  const solveMap = () => {
    setMessage(null);
    if (!startMapJob(request, settings, { done: status?.solves_finished ?? 0, total: status?.solves_total ?? 0, elapsed_s: 0 })) {
      setMessage('Another map is solving; cancel it or wait for it to finish.');
    }
  };

  const setLimit = (key: keyof DriveLimits, current = false) => (event: React.ChangeEvent<HTMLInputElement>) => {
    if (key === 'continuous_current_A' && event.target.value.trim() === '') {
      setLimits((previous) => ({ ...previous, continuous_current_A: null }));
      setMessage(null);
      return;
    }
    const value = Number(event.target.value);
    if (!Number.isFinite(value) || value <= 0) {
      const committed = limits[key];
      event.target.value = committed == null ? '' : String(current ? units.fromPeak(committed) : committed);
      setMessage('Enter a positive limit, or leave Continuous current empty.');
      return;
    }
    const next = current ? units.toPeak(value) : value;
    if ((key === 'continuous_current_A' && next > limits.peak_current_A)
      || (key === 'peak_current_A' && limits.continuous_current_A != null && next < limits.continuous_current_A)) {
      const committed = limits[key];
      event.target.value = committed == null ? '' : String(units.fromPeak(committed));
      setMessage('Continuous current must not exceed Peak current.');
      return;
    }
    setMessage(null);
    if (key === 'dc_bus_V' && Math.abs(next - limits.dc_bus_V) > 1e-9) setBusEdited(true);
    setLimits((previous) => ({ ...previous, [key]: next }));
  };
  const shownCurrent = (peakA: number | null | undefined) => (typeof peakA === 'number' ? Number(units.fromPeak(peakA).toFixed(2)) : '');
  const otherUnit = units.unit === 'A rms' ? 'A peak' : 'A rms';
  const inOtherUnit = (peakA: number) => `${compact(units.unit === 'A rms' ? peakA : peakA / Math.SQRT2)} ${otherUnit}`;

  const downloadCsv = () => {
    if (!mapPayload) return;
    const url = URL.createObjectURL(new Blob([mapCsv(mapPayload.map)], { type: 'text/csv' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(designName ?? 'coilem-design').replace(/[^A-Za-z0-9._-]+/g, '-')}-flux-linkage-map.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const downloadReport = async (kind: PerformanceReportKind) => {
    if (!driveBody) return;
    const context: PerformanceReportContext = {
      design_name: designName ?? (typeof request.project_name === 'string' ? request.project_name : null),
      current_unit: units.unit,
      dc_bus_source: busFromDesign ? 'design' : busEstimated ? 'estimated' : 'entered',
      map_preset: preset,
      solved_point: solvedPoint ? { speed_rpm: solvedPoint.speedRpm, torque_Nm: solvedPoint.torqueNm, current_angle_deg: solvedPoint.gammaDeg } : null,
      magnet_temperature_derated: magnetsDerated,
      phase_resistance: resistance !== null && resistance > 0 ? resistanceStatus : null,
    };
    setDownloading(kind);
    try {
      await downloadPerformanceReport(kind, { ...driveBody, context });
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setDownloading(null);
    }
  };

  const failed = mapPayload?.map.points.filter((point) => point.status === 'failed').length ?? 0;
  // What each output on the tab rests on, as the performance report lists it (public issue 143).
  const statuses: NamedOutputStatus[] = drive ? [
    { key: 'envelope', label: 'Torque–speed envelope', status: drive.envelope.status, reason: drive.envelope.status_reason ?? '' },
    { key: 'efficiency', label: 'Efficiency map', status: drive.efficiency_map.status, reason: drive.efficiency_map.status_reason ?? '' },
    { key: 'dq', label: 'Map flux linkage, MTPA and Ld, Lq', status: 'experimental', reason: DQ_FLUX_LINKAGE_STATUS_REASON },
    ...(resistance !== null && resistance > 0
      ? [{ key: 'resistance', label: 'Phase resistance and copper loss', ...resistanceStatus }]
      : []),
    ...(magnetsDerated ? [{
      key: 'magnets',
      label: 'Magnet temperature derating',
      status: result.solve_metadata.magnet_temperature_status ?? 'experimental',
      reason: result.solve_metadata.magnet_temperature_status_reason ?? MAGNET_TEMPERATURE_STATUS_REASON,
    }] : []),
  ] : [];
  // Before the curves exist the tab still says what they will be.
  const headerStatuses: NamedOutputStatus[] = statuses.length
    ? statuses
    : [{ key: 'envelope', label: 'Torque–speed envelope', status: 'experimental', reason: ENVELOPE_STATUS_REASON }];
  const agreement = (mapPayload?.torque_agreement_pct ?? []).filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  const agreementText = agreement.length > 0
    ? `FEM torque is ${Math.min(...agreement).toFixed(1)}–${Math.max(...agreement).toFixed(1)}% of the d/q torque across ${agreement.length} map points.`
    : null;
  const inductances = mapPayload ? inductanceTable(mapPayload.map) : [];
  const peak = drive?.envelope.curves.find((curve) => curve.limit === 'peak') ?? null;
  const bestEfficiency = drive ? Math.max(...drive.efficiency_map.efficiency_pct.flat().filter((value): value is number => value !== null)) : null;
  // MTPA still holds at the top speed: base speed lies above it.
  const baseReached = peak !== null && drive !== null && peak.base_speed_rpm < drive.envelope.limits.max_speed_rpm * (1 - 1e-6);
  const remaining = status ? Math.max(status.solves_total - status.solves_finished, 0) : null;
  const estimate = status && remaining ? estimateMapSeconds({
    runSolveSeconds: summary.solve_time_s,
    runPositions: result.solve_metadata.rotor_positions,
    pointPositions: status.positions_per_point ?? 12,
    solves: remaining,
    zeroPointPending: status.solves_finished === 0,
  }) : null;
  // Show whichever map is solving, this one or another, with its progress and Cancel.
  const runningJob = job?.phase === 'solving' ? job : null;
  const progress = runningJob?.progress ?? null;
  const continuousIsSolved = solvedShown !== null && limits.continuous_current_A !== null && limits.continuous_current_A !== undefined
    && Math.abs(units.fromPeak(limits.continuous_current_A) - solvedShown) < 0.26;
  const gridNote = 'Each point is a solve of this design; the first also runs the no-load sweep. A map keeps solving if you switch tabs.';
  const mapChip = otherSolving ? 'Another map is solving'
    : phase === 'checking' ? 'Looking for a stored map…'
      : phase === 'computing' ? 'Computing the curves…'
        : null;

  return (
    <section className="performance-panel" aria-labelledby={headingId}>
      <header className="performance-header results-card-heading">
        <h3 id={headingId}>Torque–speed and efficiency</h3>
        <StatusSummary statuses={headerStatuses} />
        <InfoTip label="How the curves are computed">
          <p>
            coilEM solves this design over currents up to the peak and current angles from 0° to 90° (a flux-linkage map),
            then finds the most torque at each speed within the drive limits.
          </p>
          <p>Currents are phase currents in {units.unit}, as on the Solve page. Torque is electromagnetic; copper loss uses the winding at {significant(windingTemperature)} °C.</p>
        </InfoTip>
        {resistance === null && (
          <Popover trigger={(props) => <button type="button" className="performance-tag" {...props}>No resistance</button>}>
            <p>No phase resistance recorded: copper loss and IR drop are left out.</p>
          </Popover>
        )}
        <span className="performance-header-spacer" />
        {mapChip && <span className="performance-map-chip" role="status">{mapChip}</span>}
        {!mapChip && mapPayload && (
          <Popover
            align="end"
            trigger={(props) => (
              <button type="button" className="performance-map-chip" {...props}>
                Map · {mapPayload.map.points.length} pts · ≤ {formatCurrent(mapPayload.map.current_peak_A[mapPayload.map.current_peak_A.length - 1])}
              </button>
            )}
          >
            <p>
              Map of {mapPayload.map.points.length} points up to {formatCurrent(mapPayload.map.current_peak_A[mapPayload.map.current_peak_A.length - 1])},
              {' '}{mapPayload.map.rotor_positions} rotor positions each.
            </p>
            {agreementText && <p>{agreementText}</p>}
            {failed > 0 && <p>{failed} point{failed === 1 ? '' : 's'} failed; Retry solves {failed === 1 ? 'it' : 'them'} again.</p>}
          </Popover>
        )}
        {mapPayload && !runningJob && (
          <ExportMenu
            disabled={!driveBody}
            downloading={downloading}
            onReport={(kind) => void downloadReport(kind)}
            onMapCsv={downloadCsv}
          />
        )}
      </header>
      <div className="performance-limits">
        <LimitField
          label="Peak current"
          unit={units.unit}
          hint={<p>Short-term limit: inverter, demagnetisation, heating. {inOtherUnit(limits.peak_current_A)}.</p>}
        >
          {(id) => <input id={id} type="number" min={0.1} step="any" defaultValue={shownCurrent(limits.peak_current_A)} onBlur={setLimit('peak_current_A', true)} />}
        </LimitField>
        <LimitField
          label="Continuous current"
          unit={units.unit}
          tag={continuousIsSolved ? <span className="performance-tag is-quiet" title="Equals your solved operating point">= solved</span> : undefined}
          hint={(
            <p>
              What the cooling carries indefinitely.
              {solvedShown !== null ? ` Your solved operating point is ${compact(solvedShown)} ${units.unit}.` : ''}
            </p>
          )}
        >
          {(id) => <input id={id} type="number" min={0.1} step="any" defaultValue={shownCurrent(limits.continuous_current_A)} onBlur={setLimit('continuous_current_A', true)} />}
        </LimitField>
        <LimitField
          label="DC bus"
          unit="V"
          estimated={busEstimated}
          tag={busEstimated ? <span className="performance-tag">Est.</span> : undefined}
          hint={(
            <p>
              {busFromDesign ? 'From the design.' : busEstimated ? 'Estimated from the back EMF: enter your supply voltage.' : 'As entered.'}
              {' '}The peak phase voltage is limited to the bus ÷ √3 (space-vector modulation).
            </p>
          )}
        >
          {(id) => <input id={id} type="number" min={1} step="any" defaultValue={limits.dc_bus_V} onBlur={setLimit('dc_bus_V')} />}
        </LimitField>
        <LimitField label="Top speed" unit="rpm" hint={<p>The highest shaft speed the curves and the efficiency map cover.</p>}>
          {(id) => <input id={id} type="number" min={100} step="any" defaultValue={limits.max_speed_rpm} onBlur={setLimit('max_speed_rpm')} />}
        </LimitField>
        <LimitField
          label="Drive control"
          hint={(
            <>
              <p><strong>MTPA, then field weakening:</strong> {CONTROL_NOTE.mtpa.replace(/^MTPA: /, '')}; a typical drive.</p>
              <p><strong>Least loss:</strong> {CONTROL_NOTE.least_loss.replace(/^Least loss: /, '')}; an efficiency-optimised drive.</p>
            </>
          )}
        >
          {(id) => (
            <select
              id={id}
              value={control}
              onChange={(event) => {
                const next = event.target.value as DriveControl;
                setControl(next);
                if (mapPayload) void computeDrive(mapPayload, limits, next);
              }}
            >
              <option value="mtpa">MTPA</option>
              <option value="least_loss">Least loss</option>
            </select>
          )}
        </LimitField>
        <LimitField
          label="Map grid"
          hint={(
            <>
              <p><strong>Preview:</strong> 5 currents × 7 angles, 12 rotor positions each. <strong>Standard:</strong> 7 currents × 10 angles, 24 positions each.</p>
              <p>{gridNote}</p>
            </>
          )}
        >
          {(id) => (
            <select id={id} value={preset} onChange={(event) => setPreset(event.target.value as MapSettings['preset'])}>
              <option value="preview">Preview 5×7</option>
              <option value="standard">Standard 7×10</option>
            </select>
          )}
        </LimitField>
        {mapPayload && !runningJob && (
          <div className="performance-limits-actions">
            <button type="button" className="performance-primary" onClick={() => void computeDrive(mapPayload, limits)} disabled={phase === 'computing'}>Apply limits</button>
            {failed > 0 && <button type="button" onClick={solveMap}>Retry {failed} failed point{failed === 1 ? '' : 's'}</button>}
          </div>
        )}
      </div>
      {(runningJob || (!mapPayload && phase !== 'checking')) && (
        <div className="performance-actions">
          {runningJob && progress ? (
            <>
              <div className="performance-progress" role="progressbar" aria-valuemin={0} aria-valuemax={progress.total} aria-valuenow={progress.done}>
                <span style={{ width: `${progress.total ? (100 * progress.done) / progress.total : 0}%` }} />
              </div>
              <p>
                {otherSolving ? `A map up to ${formatCurrent(runningJob.settings.peak_current_A)} (${runningJob.settings.preset}) is solving: ` : ''}
                Solved {progress.done} of {progress.total}
                {progress.current_peak_A !== undefined ? ` · last ${formatCurrent(progress.current_peak_A)} at ${significant(progress.gamma_deg ?? 0)}°` : ''}
                {progress.eta_s ? ` · ${formatDuration(progress.eta_s)} left` : ''}
              </p>
              <button type="button" onClick={() => { void cancelPublicSolve(); }}>Cancel</button>
            </>
          ) : (
            <button type="button" className="performance-primary" onClick={solveMap} disabled={otherSolving} title={gridNote}>
              Solve map ({remaining ?? '…'} solve{remaining === 1 ? '' : 's'}{status && status.solves_finished > 0 ? `, ${status.solves_finished} kept` : ''}
              {estimate ? `, ${formatDuration(estimate)}` : ''})
            </button>
          )}
        </div>
      )}
      {message && <p className={`performance-message${phase === 'error' ? ' is-error' : ''}`} role={phase === 'error' ? 'alert' : 'status'}>{message}</p>}
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
