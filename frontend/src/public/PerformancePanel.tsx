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

// Categorical slots 1 and 2 of the validated dark palette.
const CURVE_COLORS = { peak: '#3987e5', continuous: '#d95926' } as const;
const REGION_LABEL: Record<string, string> = { mtpa: 'MTPA', field_weakening: 'field weakening', mtpv: 'MTPV' };
const WIDTH = 760;
const HEIGHT = 260;
const MARGIN = { top: 16, right: 20, bottom: 40, left: 58 };

const significant = (value: number, digits = 3) => Number(value.toPrecision(digits)).toLocaleString();

function errorText(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) return String((error as PublicApiError).message);
  return 'The local API could not compute the performance map.';
}

function Axes({ xMax, yMax, xLabel, yLabel, yFormat = (value: number) => significant(value) }: {
  xMax: number; yMax: number; xLabel: string; yLabel: string; yFormat?: (value: number) => string;
}) {
  const plotW = WIDTH - MARGIN.left - MARGIN.right;
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  return (
    <g className="performance-axes">
      {niceTicks(yMax, 5).filter((tick) => tick <= yMax + 1e-9).map((tick) => {
        const y = MARGIN.top + plotH * (1 - tick / yMax);
        return (
          <g key={`y${tick}`}>
            <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={y} y2={y} className="chart-grid" />
            <text x={MARGIN.left - 8} y={y + 4} textAnchor="end" className="chart-label">{yFormat(tick)}</text>
          </g>
        );
      })}
      {niceTicks(xMax, 6).filter((tick) => tick <= xMax + 1e-9).map((tick) => {
        const x = MARGIN.left + plotW * (tick / xMax);
        return <text key={`x${tick}`} x={x} y={HEIGHT - MARGIN.bottom + 16} textAnchor="middle" className="chart-label">{tick.toLocaleString()}</text>;
      })}
      <text x={MARGIN.left + plotW / 2} y={HEIGHT - 6} textAnchor="middle" className="chart-label">{xLabel}</text>
      <text x={14} y={MARGIN.top + plotH / 2} textAnchor="middle" className="chart-label" transform={`rotate(-90 14 ${MARGIN.top + plotH / 2})`}>{yLabel}</text>
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

function SolvedMarker({ cx, cy, label }: { cx: number; cy: number; label: string }) {
  if (!Number.isFinite(cx) || !Number.isFinite(cy) || cx < MARGIN.left || cx > WIDTH - MARGIN.right || cy < MARGIN.top || cy > HEIGHT - MARGIN.bottom) return null;
  const right = cx < WIDTH - MARGIN.right - 90;
  return (
    <g className="performance-solved-marker" aria-hidden="true">
      <circle cx={cx} cy={cy} r={6} className="performance-solved-ring" />
      <circle cx={cx} cy={cy} r={2} className="performance-solved-dot" />
      <text x={right ? cx + 9 : cx - 9} y={cy - 8} textAnchor={right ? 'start' : 'end'} className="performance-solved-label">{label}</text>
    </g>
  );
}

function usePlotPointer(xMax: number) {
  const [speed, setSpeed] = useState<number | null>(null);
  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * WIDTH;
    const fraction = (svgX - MARGIN.left) / (WIDTH - MARGIN.left - MARGIN.right);
    setSpeed(fraction >= 0 && fraction <= 1 ? fraction * xMax : null);
  };
  return { speed, onMove, onLeave: () => setSpeed(null) };
}

function TorqueSpeedChart({ envelope, formatCurrent, solved }: { envelope: TorqueSpeedEnvelope; formatCurrent: (peakA: number) => string; solved: SolvedPoint | null }) {
  const [quantity, setQuantity] = useState<'torque' | 'power'>('torque');
  const curves = envelope.curves;
  const xMax = axisTop(Math.max(...curves.map((curve) => curve.max_speed_rpm), 1), 6);
  const values = (curve: TorqueSpeedEnvelope['curves'][number]) => (quantity === 'torque' ? curve.torque_Nm : curve.power_W.map((watts) => watts / 1000));
  const yMax = axisTop(Math.max(...curves.flatMap(values), 1e-6) * 1.05, 5);
  const plotW = WIDTH - MARGIN.left - MARGIN.right;
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (speed: number) => MARGIN.left + plotW * (speed / xMax);
  const y = (value: number) => MARGIN.top + plotH * (1 - value / yMax);
  const pointer = usePlotPointer(xMax);
  const peak = curves.find((curve) => curve.limit === 'peak') ?? curves[0];
  const unit = quantity === 'torque' ? 'N·m' : 'kW';
  const readout = pointer.speed === null ? null : curves.map((curve) => {
    const at = curveAt(curve, pointer.speed as number);
    if (!at) return `${curve.limit === 'peak' ? 'Peak' : 'Continuous'} —`;
    const value = quantity === 'torque' ? at.torque : at.power / 1000;
    return `${curve.limit === 'peak' ? 'Peak' : 'Continuous'} ${significant(value)} ${unit} at ${formatCurrent(at.currentPeakA)}, γ ${Math.round(at.gammaDeg)}° (${REGION_LABEL[at.region] ?? at.region})`;
  });
  return (
    <figure className="performance-chart">
      <div className="performance-chart-heading">
        <span>{quantity === 'torque' ? 'Torque–speed' : 'Power–speed'} envelope</span>
        <div className="performance-toggle" role="group" aria-label="Envelope quantity">
          <button type="button" aria-pressed={quantity === 'torque'} onClick={() => setQuantity('torque')}>Torque</button>
          <button type="button" aria-pressed={quantity === 'power'} onClick={() => setQuantity('power')}>Power</button>
        </div>
      </div>
      <div className="public-waveform-legend" aria-label="Envelope curves">
        {curves.map((curve) => (
          <span key={curve.limit}>
            <i style={{ backgroundColor: CURVE_COLORS[curve.limit] }} />
            {curve.limit === 'peak' ? 'Peak' : 'Continuous'}, {formatCurrent(curve.limit === 'peak' ? envelope.limits.peak_current_A : envelope.limits.continuous_current_A ?? 0)}
          </span>
        ))}
        {solved && <span><i className="performance-solved-swatch" />Solved point, {significant(solved.torqueNm)} N·m at {significant(solved.speedRpm)} rpm</span>}
      </div>
      <p className="performance-readout" aria-live="polite">
        {pointer.speed === null ? `Base speed ${significant(peak.base_speed_rpm)} rpm · top speed ${significant(peak.max_speed_rpm)} rpm. Hover for values.` : `${significant(pointer.speed)} rpm · ${readout?.join(' · ')}`}
      </p>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`${quantity === 'torque' ? 'Torque' : 'Power'} against speed for the drive limits`} onPointerMove={pointer.onMove} onPointerLeave={pointer.onLeave}>
        <Axes xMax={xMax} yMax={yMax} xLabel="Speed (rpm)" yLabel={quantity === 'torque' ? 'Torque (N·m)' : 'Power (kW)'} />
        <line x1={x(peak.base_speed_rpm)} x2={x(peak.base_speed_rpm)} y1={MARGIN.top} y2={HEIGHT - MARGIN.bottom} className="performance-base-line" />
        <text x={x(peak.base_speed_rpm) + 4} y={MARGIN.top + 10} className="chart-label">base</text>
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
        {solved && (
          <SolvedMarker
            cx={x(solved.speedRpm)}
            cy={y(quantity === 'torque' ? solved.torqueNm : (solved.torqueNm * solved.speedRpm * 2 * Math.PI) / 60 / 1000)}
            label="solved"
          />
        )}
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
  const bands = useMemo(() => efficiencyBands(map), [map]);
  const [hover, setHover] = useState<{ row: number; column: number } | null>(null);
  const speeds = map.speed_rpm;
  const torques = map.torque_Nm;
  const xMax = axisTop(speeds[speeds.length - 1], 6);
  const yMax = axisTop(torques[torques.length - 1] * 1.05, 5);
  const plotW = WIDTH - MARGIN.left - MARGIN.right;
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (speed: number) => MARGIN.left + plotW * (speed / xMax);
  const y = (torque: number) => MARGIN.top + plotH * (1 - torque / yMax);
  const cellW = plotW * ((speeds[1] - speeds[0]) / xMax);
  const cellH = plotH * ((torques[1] - torques[0]) / yMax);
  const peak = envelope.curves.find((curve) => curve.limit === 'peak') ?? envelope.curves[0];
  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const speed = (((event.clientX - rect.left) / rect.width) * WIDTH - MARGIN.left) / plotW * xMax;
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
    ? ` (your solve used γ ${Math.round(solved.gammaDeg)}°, so its efficiency on the Losses card differs)`
    : '';
  return (
    <figure className="performance-chart">
      <div className="performance-chart-heading"><span>Efficiency map</span><span className="performance-chart-note">{CONTROL_NOTE[map.control ?? 'mtpa']}; hover for the current</span></div>
      <p className="performance-readout" aria-live="polite">
        {cell && hover
          ? `${significant(cell.eta, 3)}% at ${significant(speeds[hover.column])} rpm, ${significant(torques[hover.row])} N·m · ${cell.current ? `${describeCurrent(cell.current)} · ` : ''}copper ${significant(cell.copper ?? 0)} W · iron ${significant(cell.iron ?? 0)} W`
          : `${solvedEta !== null && solved ? `Solved point (${significant(solved.speedRpm)} rpm, ${significant(solved.torqueNm)} N·m): ${solvedEta.toFixed(1)}%${solvedCurrent ? ` at ${describeCurrent(solvedCurrent)}` : ''}${solvedAngleNote}. ` : ''}Hover the map for efficiency, current and losses at a point. Blank above the peak envelope.`}
      </p>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`Efficiency over speed and torque, from ${bands.floor}% to ${bands.top}%`} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
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
        <Axes xMax={xMax} yMax={yMax} xLabel="Speed (rpm)" yLabel="Torque (N·m)" />
        <path d={peak.speed_rpm.map((speed, index) => `${index ? 'L' : 'M'} ${x(speed).toFixed(1)} ${y(peak.torque_Nm[index]).toFixed(1)}`).join(' ')} fill="none" className="performance-envelope-line" />
        {hover && <rect x={x(speeds[hover.column]) - cellW / 2} y={y(torques[hover.row]) - cellH / 2} width={cellW} height={cellH} className="performance-cell-focus" />}
        {solved && <SolvedMarker cx={x(solved.speedRpm)} cy={y(solved.torqueNm)} label={solvedEta !== null ? `solved, ${solvedEta.toFixed(1)}%` : 'solved'} />}
      </svg>
      <div className="performance-band-legend" aria-label={`Efficiency bands of ${bands.step} points from ${bands.floor}% to ${bands.top}%`}>
        <div>{legendStops.map((value) => <span key={value} style={{ background: efficiencyColor(value, bands) }} title={`${value}–${value + bands.step}%`} />)}</div>
        <div><small>≤ {bands.floor}%</small><small>{bands.top}%</small></div>
      </div>
    </figure>
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
  const formatCurrent = useCallback((peakA: number) => `${significant(units.fromPeak(peakA))} ${units.unit}`, [units]);
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
  const inOtherUnit = (peakA: number) => `${significant(units.unit === 'A rms' ? peakA : peakA / Math.SQRT2)} ${otherUnit}`;

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
  const agreement = (mapPayload?.torque_agreement_pct ?? []).filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  const inductances = mapPayload ? inductanceTable(mapPayload.map) : [];
  const peak = drive?.envelope.curves.find((curve) => curve.limit === 'peak') ?? null;
  const bestEfficiency = drive ? Math.max(...drive.efficiency_map.efficiency_pct.flat().filter((value): value is number => value !== null)) : null;
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

  return (
    <section className="performance-panel" aria-labelledby={headingId}>
      <header className="performance-header">
        <h3 id={headingId}>Torque–speed and efficiency</h3>
        <span className="losses-status is-experimental" title="Interpolated from a flux-linkage map; not yet compared with measured data.">Experimental</span>
      </header>
      <p className="performance-intro">
        coilEM solves this design over currents up to the peak and current angles from 0° to 90° (a flux-linkage map), then finds the most torque at each speed within the drive limits.
        Currents are phase currents in {units.unit}, as on the Solve page.
        Torque is electromagnetic; copper loss uses the winding at {significant(windingTemperature)} °C{resistance === null ? ' (no phase resistance recorded: copper loss and IR drop are left out)' : ''}.
      </p>
      <div className="performance-limits">
        <label>
          <span>Peak current</span>
          <input type="number" min={0.1} step="any" defaultValue={shownCurrent(limits.peak_current_A)} onBlur={setLimit('peak_current_A', true)} />
          <small>{units.unit}</small>
          <em className="performance-limit-note">Short-term limit: inverter, demagnetisation, heating. {inOtherUnit(limits.peak_current_A)}.</em>
        </label>
        <label>
          <span>Continuous current</span>
          <input type="number" min={0.1} step="any" defaultValue={shownCurrent(limits.continuous_current_A)} onBlur={setLimit('continuous_current_A', true)} />
          <small>{units.unit}</small>
          <em className="performance-limit-note">
            {solvedShown !== null && limits.continuous_current_A !== null && limits.continuous_current_A !== undefined
              && Math.abs(units.fromPeak(limits.continuous_current_A) - solvedShown) < 0.26
              ? `= your solved operating point (${significant(solvedShown)} ${units.unit}).`
              : solvedShown !== null ? `Your solved operating point is ${significant(solvedShown)} ${units.unit}.` : 'What the cooling carries indefinitely.'}
          </em>
        </label>
        <label className={busEstimated ? 'is-estimated' : undefined}>
          <span>DC bus</span>
          <input type="number" min={1} step="any" defaultValue={limits.dc_bus_V} onBlur={setLimit('dc_bus_V')} />
          <small>V</small>
          <em className="performance-limit-note">
            {busFromDesign ? 'From the design.' : busEstimated ? 'Estimated from the back EMF: enter your supply voltage.' : 'As entered.'}
          </em>
        </label>
        <label><span>Top speed</span><input type="number" min={100} step="any" defaultValue={limits.max_speed_rpm} onBlur={setLimit('max_speed_rpm')} /><small>rpm</small></label>
        <label>
          <span>Drive control</span>
          <select
            value={control}
            onChange={(event) => {
              const next = event.target.value as DriveControl;
              setControl(next);
              if (mapPayload) void computeDrive(mapPayload, limits, next);
            }}
          >
            <option value="mtpa">MTPA, then field weakening (typical drive)</option>
            <option value="least_loss">Least loss (efficiency-optimised drive)</option>
          </select>
        </label>
        <label><span>Map grid</span>
          <select value={preset} onChange={(event) => setPreset(event.target.value as MapSettings['preset'])}>
            <option value="preview">Preview: 5 currents × 7 angles, 12 positions each</option>
            <option value="standard">Standard: 7 currents × 10 angles, 24 positions each</option>
          </select>
        </label>
      </div>
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
          <>
            {!mapPayload && phase !== 'checking' && (
              <button type="button" className="performance-primary" onClick={solveMap} disabled={otherSolving}>
                Solve map ({remaining ?? '…'} solve{remaining === 1 ? '' : 's'}{status && status.solves_finished > 0 ? `, ${status.solves_finished} kept` : ''}
                {estimate ? `, ${formatDuration(estimate)}` : ''})
              </button>
            )}
            {mapPayload && (
              <>
                <button type="button" className="performance-primary" onClick={() => void computeDrive(mapPayload, limits)} disabled={phase === 'computing'}>Apply limits</button>
                {failed > 0 && <button type="button" onClick={solveMap}>Retry {failed} failed point{failed === 1 ? '' : 's'}</button>}
                <span className="performance-downloads" role="group" aria-label="Downloads">
                  <button type="button" onClick={() => void downloadReport('pdf')} disabled={!driveBody || downloading !== null}
                    title="Inputs, curves, efficiency map, MTPA trajectory and Ld/Lq as a PDF report">
                    {downloading === 'pdf' ? 'Preparing PDF…' : 'PDF report'}
                  </button>
                  <button type="button" onClick={() => void downloadReport('csv')} disabled={!driveBody || downloading !== null}
                    title="Every number and curve sample of the report, long-form like the run CSV">
                    {downloading === 'csv' ? 'Preparing CSV…' : 'Performance CSV'}
                  </button>
                  <button type="button" onClick={() => void downloadReport('idiq')} disabled={!driveBody || downloading !== null}
                    title="λd, λq and torque on a rectangular id × iq grid, for drive-control models">
                    {downloading === 'idiq' ? 'Preparing table…' : 'id/iq table'}
                  </button>
                  <button type="button" onClick={downloadCsv} title="The map's solved points as they are">Map points CSV</button>
                </span>
              </>
            )}
            <p>
              {otherSolving ? 'Another map is solving (the solver runs one at a time). '
                : phase === 'checking' ? 'Looking for a stored map…'
                  : phase === 'computing' ? 'Computing the curves…'
                    : mapPayload ? `Map of ${mapPayload.map.points.length} points up to ${formatCurrent(mapPayload.map.current_peak_A[mapPayload.map.current_peak_A.length - 1])}, ${mapPayload.map.rotor_positions} rotor positions each.`
                      : 'Each point is a solve of this design; the first also runs the no-load sweep. It keeps running if you switch tabs.'}
            </p>
          </>
        )}
      </div>
      {message && <p className={`performance-message${phase === 'error' ? ' is-error' : ''}`} role={phase === 'error' ? 'alert' : 'status'}>{message}</p>}
      {drive && peak && (
        <>
          <div className="performance-stats">
            <div><span>Peak torque</span><strong>{significant(peak.torque_Nm[0])} <small>N·m</small></strong></div>
            <div><span>Base speed</span><strong>{significant(peak.base_speed_rpm)} <small>rpm</small></strong></div>
            <div><span>Peak power</span><strong>{significant(peak.peak_power_W / 1000)} <small>kW</small></strong></div>
            <div><span>Top speed reached</span><strong>{significant(peak.max_speed_rpm)} <small>rpm</small></strong></div>
            <div><span>Best efficiency</span><strong>{bestEfficiency !== null && Number.isFinite(bestEfficiency) ? `${bestEfficiency.toFixed(1)}` : '—'} <small>%</small></strong></div>
          </div>
          <TorqueSpeedChart envelope={drive.envelope} formatCurrent={formatCurrent} solved={solvedPoint} />
          <EfficiencyMapChart map={drive.efficiency_map} envelope={drive.envelope} solved={solvedPoint} formatCurrent={formatCurrent} />
          <div className="performance-footer">
            {inductances.length > 0 && (
              <table className="performance-inductance">
                <caption>Apparent inductance against current</caption>
                <thead><tr><th scope="col">Current</th><th scope="col">Ld</th><th scope="col">Lq</th></tr></thead>
                <tbody>
                  {inductances.map((row) => (
                    <tr key={row.currentA}>
                      <th scope="row">{formatCurrent(row.currentA)}</th>
                      <td>{row.ldH === null ? '—' : `${significant(row.ldH * 1000)} mH`}</td>
                      <td>{row.lqH === null ? '—' : `${significant(row.lqH * 1000)} mH`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <ul className="performance-notes">
              {agreement.length > 0 && <li>FEM torque is {Math.min(...agreement).toFixed(1)}–{Math.max(...agreement).toFixed(1)}% of the d/q torque across {agreement.length} map points.</li>}
              <li>Ld from the 90° points, (λd − λpm) / id; Lq from the 0° points, λq / iq. Both are secant values and include saturation.</li>
              {drive.envelope.status_reason && <li>{drive.envelope.status_reason}</li>}
              {drive.efficiency_map.status_reason && <li>{drive.efficiency_map.status_reason}</li>}
            </ul>
          </div>
        </>
      )}
    </section>
  );
}
