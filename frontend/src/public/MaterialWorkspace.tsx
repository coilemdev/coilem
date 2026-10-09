import {
  useMemo,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';

import type {
  MaterialCatalog,
  MotorConfig,
  PublicMaterialCurve,
  PublicMaterialModel,
  PublicMotorComponentKind,
} from './model';
import { steelDisplayName } from './customSteel';

export type PublicMaterialSubview = 'assignment' | 'behavior';
export type PublicMaterialTarget = 'stator' | 'rotor' | 'magnet' | 'winding';

interface MaterialTargetDefinition {
  target: PublicMaterialTarget;
  label: string;
  materialId: string;
  swatchClass: string;
}

interface MaterialBehaviorOption {
  target: PublicMaterialTarget;
  targets: PublicMaterialTarget[];
  materialId: string;
  label: string;
  usage: string;
  swatchClass: string;
}

const CHART_WIDTH = 760;
const CHART_HEIGHT = 390;
const COMPACT_PLOT = { left: 48, right: 344, top: 18, bottom: 218 };
const PLOT = {
  left: 72,
  right: 720,
  top: 35,
  bottom: 324,
};

function materialTargets(config: MotorConfig): MaterialTargetDefinition[] {
  return [
    {
      target: 'stator',
      label: 'Stator steel',
      materialId: config.materials.stator_steel,
      swatchClass: 'material-stator',
    },
    {
      target: 'rotor',
      label: 'Rotor steel',
      materialId: config.materials.rotor_steel,
      swatchClass: 'material-rotor',
    },
    {
      target: 'magnet',
      label: 'Magnets',
      materialId: config.materials.magnet_grade,
      swatchClass: 'material-magnet',
    },
    {
      target: 'winding',
      label: 'Windings',
      materialId: config.materials.conductor,
      swatchClass: 'material-copper',
    },
  ];
}

function behaviorOptions(config: MotorConfig): MaterialBehaviorOption[] {
  const sharedSteel = config.materials.stator_steel === config.materials.rotor_steel;
  const steelOptions: MaterialBehaviorOption[] = sharedSteel
    ? [{
      target: 'stator',
      targets: ['stator', 'rotor'],
      materialId: config.materials.stator_steel,
      label: config.materials.stator_steel,
      usage: 'Stator + rotor',
      swatchClass: 'material-shared-steel',
    }]
    : [
      {
        target: 'stator',
        targets: ['stator'],
        materialId: config.materials.stator_steel,
        label: config.materials.stator_steel,
        usage: 'Stator steel',
        swatchClass: 'material-stator',
      },
      {
        target: 'rotor',
        targets: ['rotor'],
        materialId: config.materials.rotor_steel,
        label: config.materials.rotor_steel,
        usage: 'Rotor steel',
        swatchClass: 'material-rotor',
      },
    ];
  return [
    ...steelOptions,
    {
      target: 'magnet',
      targets: ['magnet'],
      materialId: config.materials.magnet_grade,
      label: config.materials.magnet_grade,
      usage: 'Magnets',
      swatchClass: 'material-magnet',
    },
    {
      target: 'winding',
      targets: ['winding'],
      materialId: config.materials.conductor,
      label: config.materials.conductor,
      usage: 'Windings',
      swatchClass: 'material-copper',
    },
  ];
}

export function materialTargetKind(
  target: PublicMaterialTarget,
): PublicMotorComponentKind {
  return target === 'winding' ? 'winding' : target;
}

export function MaterialAssignmentStrip({
  config,
  activeTarget,
  previewTarget,
  onTargetChange,
  onPreviewTargetChange,
}: {
  config: MotorConfig;
  activeTarget: PublicMaterialTarget;
  previewTarget: PublicMaterialTarget | null;
  onTargetChange: (target: PublicMaterialTarget) => void;
  onPreviewTargetChange: (target: PublicMaterialTarget | null) => void;
}) {
  return (
    <section className="public-material-assignment-strip" aria-label="Material assignment">
      <div className="public-material-strip-heading">
        <span>Material assignment</span>
        <small>Select an assignment to highlight it in the motor.</small>
      </div>
      <div className="public-material-assignment-grid">
        {materialTargets(config).map((item) => {
          const active = (previewTarget ?? activeTarget) === item.target;
          return (
            <button
              type="button"
              className={active ? 'is-active' : ''}
              aria-pressed={activeTarget === item.target}
              onClick={() => onTargetChange(item.target)}
              onPointerEnter={() => onPreviewTargetChange(item.target)}
              onPointerLeave={() => onPreviewTargetChange(null)}
              onFocus={() => onPreviewTargetChange(item.target)}
              onBlur={() => onPreviewTargetChange(null)}
              key={item.target}
            >
              <i className={item.swatchClass} aria-hidden="true" />
              <span>
                <small>{item.label}</small>
                <strong>{steelDisplayName(config, item.materialId)}</strong>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function propertyNumber(model: PublicMaterialModel, property: string): number | null {
  const value = model.properties[property];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function propertyRange(
  model: PublicMaterialModel,
  property: string,
): [number, number] | null {
  const value = model.properties[property];
  return Array.isArray(value)
    && value.length === 2
    && value.every((entry) => typeof entry === 'number' && Number.isFinite(entry))
    ? [value[0], value[1]]
    : null;
}

function compactFieldStrength(value: number): string {
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (absolute >= 1_000) return `${Math.round(value / 1_000)}k`;
  return `${Math.round(value)}`;
}

function xTickValues(
  scale: PublicMaterialCurve['x_scale'],
  minimum: number,
  maximum: number,
): number[] {
  if (scale === 'log1p') {
    return [0, 10, 100, 1_000, 10_000, 100_000, 1_000_000]
      .filter((tick) => tick <= maximum * 1.1);
  }
  const rawStep = Math.max(1, (maximum - minimum) / 5);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalizedStep = rawStep / magnitude;
  const niceStep = (
    normalizedStep <= 1 ? 1
      : normalizedStep <= 2 ? 2
        : normalizedStep <= 2.5 ? 2.5
          : normalizedStep <= 5 ? 5
            : 10
  ) * magnitude;
  const ticks: number[] = [];
  for (
    let tick = Math.ceil(minimum / niceStep) * niceStep;
    tick <= maximum + niceStep * 0.01;
    tick += niceStep
  ) {
    ticks.push(Math.abs(tick) < niceStep * 0.001 ? 0 : tick);
  }
  return ticks;
}

export function MaterialCurveChart({
  model,
  compact = false,
}: {
  model: PublicMaterialModel;
  compact?: boolean;
}) {
  const plot = compact ? COMPACT_PLOT : PLOT;
  const chartWidth = compact ? 360 : CHART_WIDTH;
  const chartHeight = compact ? 270 : CHART_HEIGHT;
  const curve = model.curve;
  const [hoveredPoint, setHoveredPoint] = useState<[number, number] | null>(null);
  const [steelXScale, setSteelXScale] = useState<PublicMaterialCurve['x_scale']>('log1p');
  const displayXScale = model.kind === 'electrical_steel'
    ? steelXScale
    : curve?.x_scale ?? 'linear';
  const kneeRange = propertyRange(model, 'saturation_knee_range_T');
  const chart = useMemo(() => {
    if (!curve?.points.length) return null;
    const sourcePoints = curve.points;
    const lastPoint = sourcePoints[sourcePoints.length - 1] ?? null;
    const previousPoint = sourcePoints[sourcePoints.length - 2] ?? null;
    const extrapolatedPoint: [number, number] | null = (
      model.kind === 'electrical_steel'
      && lastPoint
      && previousPoint
      && lastPoint[1] > previousPoint[1]
    )
      ? [
        lastPoint[0]
          + (lastPoint[0] - previousPoint[0])
          / (lastPoint[1] - previousPoint[1])
          * 0.15,
        lastPoint[1] + 0.15,
      ]
      : null;
    const plottedPoints = extrapolatedPoint
      ? [...sourcePoints, extrapolatedPoint]
      : sourcePoints;
    const xValues = plottedPoints.map(([x]) => x);
    const yValues = plottedPoints.map(([, y]) => y);
    const xMinimum = Math.min(...xValues);
    const xMaximum = Math.max(...xValues);
    const yMaximum = Math.max(...yValues);
    const roundedYMaximum = Math.max(0.5, Math.ceil(yMaximum * 4) / 4);
    const transformedMinimum = displayXScale === 'log1p'
      ? Math.log10(1 + Math.max(0, xMinimum))
      : xMinimum;
    const transformedMaximum = displayXScale === 'log1p'
      ? Math.log10(1 + Math.max(0, xMaximum))
      : xMaximum;
    const xScale = (value: number) => {
      const transformed = displayXScale === 'log1p'
        ? Math.log10(1 + Math.max(0, value))
        : value;
      const ratio = (transformed - transformedMinimum)
        / Math.max(1e-12, transformedMaximum - transformedMinimum);
      return plot.left + ratio * (plot.right - plot.left);
    };
    const yScale = (value: number) => (
      plot.bottom - (value / roundedYMaximum) * (plot.bottom - plot.top)
    );
    const pathForPoints = (points: Array<[number, number]>) => points
      .map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${xScale(x).toFixed(2)} ${yScale(y).toFixed(2)}`)
      .join(' ');
    const kneePoints = kneeRange
      ? sourcePoints.filter(([, b]) => b >= kneeRange[0] && b <= kneeRange[1])
      : [];
    return {
      xScale,
      yScale,
      xMinimum,
      xMaximum,
      yMaximum: roundedYMaximum,
      sourcePath: pathForPoints(sourcePoints),
      kneePath: kneePoints.length > 1 ? pathForPoints(kneePoints) : null,
      kneeMidpoint: kneePoints.length
        ? kneePoints[Math.floor(kneePoints.length / 2)]
        : null,
      sourceLimitPoint: lastPoint,
      extrapolatedPoint,
      extrapolationPath: lastPoint && extrapolatedPoint
        ? pathForPoints([lastPoint, extrapolatedPoint])
        : null,
    };
  }, [curve, displayXScale, kneeRange, model.kind, plot]);

  if (!curve || !chart) return null;
  const yTicks = Array.from(
    { length: Math.floor(chart.yMaximum / 0.5) + 1 },
    (_, index) => index * 0.5,
  );
  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const pointerX = (event.clientX - bounds.left) * chartWidth / bounds.width;
    if (pointerX < plot.left || pointerX > plot.right) {
      setHoveredPoint(null);
      return;
    }
    const nearest = curve.points.reduce((best, point) => (
      Math.abs(chart.xScale(point[0]) - pointerX)
        < Math.abs(chart.xScale(best[0]) - pointerX)
        ? point
        : best
    ));
    setHoveredPoint(nearest);
  };
  const chartLabel = model.kind === 'electrical_steel'
    ? `${model.display_name} static nonlinear B-H curve. Field strength is shown on a ${displayXScale === 'log1p' ? 'logarithmic' : 'linear'} axis. The source table ends at ${propertyNumber(model, 'curve_max_T')?.toFixed(2)} tesla and the dashed segment shows solver extrapolation.`
    : `${model.display_name} linear recoil approximation from its implied coercive field to ${propertyNumber(model, 'remanence_T')?.toFixed(2)} tesla remanence.`;
  const hoveredRelativePermeability = hoveredPoint && hoveredPoint[0] > 0
    ? hoveredPoint[1] / (4 * Math.PI * 1e-7 * hoveredPoint[0])
    : null;

  return (
    <div className="public-material-chart-shell">
      <div className="public-material-chart-toolbar">
        <span>
          <strong>
            {model.kind === 'electrical_steel'
              ? 'Static nonlinear B–H curve'
              : 'Linear recoil line'}
          </strong>
          <small>
            {model.kind === 'electrical_steel'
              ? 'Used for permeability and saturation; magnetic history is not tracked.'
              : 'The straight-line magnetic approximation used by the solver.'}
          </small>
        </span>
        {model.kind === 'electrical_steel' && (
          <div className="public-material-axis-toggle" role="group" aria-label="Steel curve H axis">
            <span>H axis</span>
            <button
              type="button"
              aria-pressed={displayXScale === 'log1p'}
              className={displayXScale === 'log1p' ? 'is-active' : ''}
              onClick={() => setSteelXScale('log1p')}
            >
              Log
            </button>
            <button
              type="button"
              aria-pressed={displayXScale === 'linear'}
              className={displayXScale === 'linear' ? 'is-active' : ''}
              onClick={() => setSteelXScale('linear')}
            >
              Linear
            </button>
          </div>
        )}
      </div>
      <svg
        className="public-material-curve-chart"
        viewBox={`0 0 ${chartWidth} ${chartHeight}`}
        role="img"
        aria-label={chartLabel}
        onPointerMove={onPointerMove}
        onPointerLeave={() => setHoveredPoint(null)}
      >
        {yTicks.map((tick) => (
          <g className="public-material-chart-grid" key={`y-${tick}`}>
            <line x1={plot.left} x2={plot.right} y1={chart.yScale(tick)} y2={chart.yScale(tick)} />
            <text x={plot.left - 12} y={chart.yScale(tick) + 4}>{tick.toFixed(1)}</text>
          </g>
        ))}
        {xTickValues(displayXScale, chart.xMinimum, chart.xMaximum).map((tick) => (
          <g className="public-material-chart-grid" key={`x-${tick}`}>
            <line x1={chart.xScale(tick)} x2={chart.xScale(tick)} y1={plot.top} y2={plot.bottom} />
            <text x={chart.xScale(tick)} y={plot.bottom + 24}>{compactFieldStrength(tick)}</text>
          </g>
        ))}
        <line className="public-material-chart-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
        <line className="public-material-chart-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={plot.bottom} />
        <text className="public-material-chart-axis-label y" x={18} y={(plot.top + plot.bottom) / 2}>B (T)</text>
        <text className="public-material-chart-axis-label" x={(plot.left + plot.right) / 2} y={chartHeight - 15}>
          H (A/m) · {displayXScale === 'log1p' ? 'logarithmic' : 'linear'} scale
        </text>
        <path className={`public-material-curve-line ${model.kind}`} d={chart.sourcePath} />
        {chart.kneePath && chart.kneeMidpoint && kneeRange && (
          <g className="public-material-knee-segment">
            <path d={chart.kneePath} />
            <text
              x={chart.xScale(chart.kneeMidpoint[0]) + 10}
              y={chart.yScale(chart.kneeMidpoint[1]) - 12}
            >
              knee · {kneeRange[0].toFixed(1)}–{kneeRange[1].toFixed(1)} T
            </text>
          </g>
        )}
        {chart.extrapolationPath && chart.extrapolatedPoint && (
          <g className="public-material-extrapolation">
            <path d={chart.extrapolationPath} />
            <text
              x={chart.xScale(chart.extrapolatedPoint[0]) - 5}
              y={chart.yScale(chart.extrapolatedPoint[1]) + 18}
            >
              solver extrapolation
            </text>
          </g>
        )}
        {model.kind === 'electrical_steel' && chart.sourceLimitPoint && (
          <g className="public-material-source-limit">
            <circle
              cx={chart.xScale(chart.sourceLimitPoint[0])}
              cy={chart.yScale(chart.sourceLimitPoint[1])}
              r={4}
            />
            <text
              x={chart.xScale(chart.sourceLimitPoint[0]) - 7}
              y={chart.yScale(chart.sourceLimitPoint[1]) + 20}
            >
              source limit · {chart.sourceLimitPoint[1].toFixed(2)} T
            </text>
          </g>
        )}
        {model.kind === 'permanent_magnet' && (
          <g className="public-material-remanence-marker">
            <line
              x1={plot.left}
              x2={chart.xScale(0)}
              y1={chart.yScale(propertyNumber(model, 'remanence_T') ?? 0)}
              y2={chart.yScale(propertyNumber(model, 'remanence_T') ?? 0)}
            />
            <text
              x={chart.xScale(0) - 8}
              y={chart.yScale(propertyNumber(model, 'remanence_T') ?? 0) - 9}
            >
              Br
            </text>
          </g>
        )}
        {hoveredPoint && (
          <g className="public-material-chart-hover">
            <line
              x1={chart.xScale(hoveredPoint[0])}
              x2={chart.xScale(hoveredPoint[0])}
              y1={plot.top}
              y2={plot.bottom}
            />
            <circle
              cx={chart.xScale(hoveredPoint[0])}
              cy={chart.yScale(hoveredPoint[1])}
              r={5}
            />
          </g>
        )}
      </svg>
      <div className="public-material-chart-readout" aria-live="polite">
        {hoveredPoint
          ? <>
            <span>H <strong>{compactFieldStrength(hoveredPoint[0])} A/m</strong></span>
            <span>B <strong>{hoveredPoint[1].toFixed(3)} T</strong></span>
            {model.kind === 'electrical_steel' && (
              <span>
                effective μr
                <strong>
                  {hoveredRelativePermeability !== null
                    ? hoveredRelativePermeability.toLocaleString(undefined, { maximumFractionDigits: 0 })
                    : '—'}
                </strong>
              </span>
            )}
          </>
          : <span>Move over the curve to inspect the modeled B and H values.</span>}
      </div>
      {model.kind === 'electrical_steel' && (
        <div className="public-material-chart-contract">
          <span><i className="source" /> Source table: 0–{chart.sourceLimitPoint?.[1].toFixed(2)} T</span>
          <span><i className="extrapolated" /> Dashed: final-slope solver extrapolation</span>
        </div>
      )}
    </div>
  );
}

function ConductorBehavior({ model }: { model: PublicMaterialModel }) {
  const conductorCenters: Array<[number, number]> = [
    [168, 88], [192, 88],
    [168, 112], [192, 112],
    [168, 136], [192, 136],
    [168, 160], [192, 160],
  ];
  return (
    <div className="public-conductor-behavior">
      <svg
        viewBox="0 0 560 265"
        role="img"
        aria-label={`${model.display_name} is shown in two adjacent stator slots joined by one continuous yoke. The outer yoke and bore-facing surface are drawn as concentric arcs. A shared center tooth separates conductors carrying current into and out of the motor cross-section, and both slot openings face the air gap and rotor.`}
      >
        <defs>
          <linearGradient id="public-slot-steel-gradient" x1="0" x2="1">
            <stop offset="0" stopColor="#344050" />
            <stop offset="0.5" stopColor="#657386" />
            <stop offset="1" stopColor="#344050" />
          </linearGradient>
        </defs>
        <g className="public-adjacent-slots">
          <path
            className="public-adjacent-slot-steel"
            d="M30 32 Q280 -12 530 32 L505 222 Q280 178 55 222 Z"
          />
          <path className="public-slot-yoke-seam" d="M36 74 Q280 30 524 74" />
          <path
            className="public-slot-cutout"
            d="M135 61 H225 L210 168 L190 181 V230 H170 V181 L150 168 Z"
          />
          <path
            className="public-slot-cutout"
            d="M335 61 H425 L410 168 L390 181 V230 H370 V181 L350 168 Z"
          />
          <path
            className="public-slot-cavity"
            d="M135 61 H225 M135 61 L150 168 L170 181 V211 M190 211 V181 L210 168 L225 61"
          />
          <path
            className="public-slot-cavity"
            d="M335 61 H425 M335 61 L350 168 L370 181 V211 M390 211 V181 L410 168 L425 61"
          />
          <path
            className="public-slot-winding-region"
            d="M145 73 H215 L203 166 H157 Z"
          />
          <path
            className="public-slot-winding-region"
            d="M345 73 H415 L403 166 H357 Z"
          />
          {conductorCenters.map(([x, y]) => (
            <g className="public-slot-conductor out" key={`out-${x}-${y}`}>
              <circle cx={x} cy={y} r={9.5} />
              <circle className="public-slot-conductor-mark" cx={x} cy={y} r={2.2} />
            </g>
          ))}
          {conductorCenters.map(([x, y]) => {
            const rightX = x + 200;
            return (
              <g className="public-slot-conductor in" key={`in-${rightX}-${y}`}>
                <circle cx={rightX} cy={y} r={9.5} />
                <path
                  className="public-slot-conductor-mark"
                  d={`M${rightX - 3.2} ${y - 3.2} L${rightX + 3.2} ${y + 3.2} M${rightX + 3.2} ${y - 3.2} L${rightX - 3.2} ${y + 3.2}`}
                />
              </g>
            );
          })}
          <text className="public-slot-annotation yoke" x={280} y={40}>CONTINUOUS STATOR YOKE</text>
          <text className="public-slot-annotation shared-tooth" x={280} y={119}>SHARED TOOTH</text>
          <path
            className="public-slot-opening-dimension"
            d="M170 201 V209 M190 201 V209 M170 205 H190 M180 209 V226 M175 221 L180 227 L185 221"
          />
          <path
            className="public-slot-opening-dimension"
            d="M370 201 V209 M390 201 V209 M370 205 H390 M380 209 V226 M375 221 L380 227 L385 221"
          />
          <text className="public-slot-annotation opening" x={180} y={241}>SLOT OPENING</text>
          <text className="public-slot-annotation opening" x={380} y={241}>SLOT OPENING</text>
        </g>
        <text className="public-slot-airgap-label" x={280} y={262}>
          openings face the air gap / rotor ↓
        </text>
      </svg>
      <div className="public-conductor-current-key" aria-label="Current direction legend">
        <span><i>⊙</i> Current out of plane</span>
        <span><i>⊗</i> Current into plane</span>
      </div>
      <strong>Applied-current regions · no B–H curve</strong>
      <p>
        Opposite current directions are shown in neighboring slots on either side
        of one shared tooth. Each copper region stops before its bore-facing slot
        opening and is treated as approximately nonmagnetic (μr ≈ 1).
      </p>
    </div>
  );
}

function modelMetricRows(model: PublicMaterialModel): Array<[string, string]> {
  if (model.kind === 'electrical_steel') {
    const initialMu = propertyNumber(model, 'initial_relative_permeability');
    const minimum = propertyNumber(model, 'curve_min_T');
    const maximum = propertyNumber(model, 'curve_max_T');
    const maximumH = propertyNumber(model, 'curve_max_H_A_per_m');
    const knee = propertyRange(model, 'saturation_knee_range_T');
    return [
      ['Initial μr', initialMu?.toFixed(0) ?? '—'],
      ['Saturation knee', knee ? `${knee[0].toFixed(1)}–${knee[1].toFixed(1)} T` : '—'],
      [
        'Source table',
        minimum !== null && maximum !== null && maximumH !== null
          ? `${minimum.toFixed(1)}–${maximum.toFixed(2)} T · ${Math.round(maximumH / 1_000)} kA/m`
          : '—',
      ],
    ];
  }
  if (model.kind === 'permanent_magnet') {
    const remanence = propertyNumber(model, 'remanence_T');
    const recoilMu = propertyNumber(model, 'relative_permeability');
    const coerciveField = propertyNumber(model, 'implied_coercive_field_kA_per_m');
    return [
      ['Remanence Br', remanence !== null ? `${remanence.toFixed(2)} T` : '—'],
      ['Recoil μr', recoilMu?.toFixed(2) ?? '—'],
      ['Implied HcB', coerciveField !== null ? `${coerciveField.toFixed(0)} kA/m` : '—'],
    ];
  }
  return [
    ['Relative μr', propertyNumber(model, 'relative_permeability')?.toFixed(1) ?? '—'],
    ['Solver role', String(model.properties.solver_role ?? 'Current-carrying region')],
    ['Material curve', 'Not used'],
  ];
}

function modelSubtitle(model: PublicMaterialModel, usage: string): string {
  if (model.kind === 'electrical_steel') {
    return `${usage} · static nonlinear B–H · no hysteresis history`;
  }
  if (model.kind === 'permanent_magnet') {
    return `${usage} · linear recoil model`;
  }
  return `${usage} · applied current region · no B–H curve`;
}

export function MaterialBehaviorView({
  config,
  catalog,
  activeTarget,
  onTargetChange,
}: {
  config: MotorConfig;
  catalog: MaterialCatalog;
  activeTarget: PublicMaterialTarget;
  onTargetChange: (target: PublicMaterialTarget) => void;
}) {
  const options = behaviorOptions(config);
  const selectedOption = options.find((option) => option.targets.includes(activeTarget))
    ?? options[0];
  const model = catalog.models?.[selectedOption.materialId];

  return (
    <section className="public-material-behavior-view" aria-label="Material behavior">
      <header className="public-material-behavior-header">
        <div>
          <span className="public-section-kicker">Material behavior</span>
          <h2>{model?.display_name ?? selectedOption.materialId}</h2>
          <p>
            {model
              ? modelSubtitle(model, selectedOption.usage)
              : `${selectedOption.usage} · model details unavailable`}
          </p>
        </div>
        <div className="public-material-behavior-tabs" role="tablist" aria-label="Material to inspect">
          {options.map((option) => (
            <button
              type="button"
              role="tab"
              aria-selected={option.targets.includes(activeTarget)}
              className={option.targets.includes(activeTarget) ? 'is-active' : ''}
              onClick={() => onTargetChange(option.target)}
              key={`${option.target}-${option.materialId}`}
            >
              <i className={option.swatchClass} aria-hidden="true" />
              <span><strong>{steelDisplayName(config, option.label)}</strong><small>{option.usage}</small></span>
            </button>
          ))}
        </div>
      </header>
      {model ? (
        <div className="public-material-behavior-body">
          <div className="public-material-behavior-visual">
            {model.curve
              ? <MaterialCurveChart key={model.id} model={model} />
              : <ConductorBehavior model={model} />}
          </div>
          <aside className="public-material-model-card">
            <span className="public-section-kicker">Solver model</span>
            <dl>
              {modelMetricRows(model).map(([label, value]) => (
                <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
              ))}
            </dl>
            <div className="public-material-model-identity">
              <span>Revision <strong>{model.model_revision}</strong></span>
              <span>Model hash <code>{model.model_hash.slice(0, 10)}…</code></span>
            </div>
            <div className="public-material-capability-list" aria-label="Material model capabilities">
              {model.kind === 'electrical_steel' && <>
                {model.capabilities.saturation_visualization && <span className="positive">Saturation modeled</span>}
                {!model.capabilities.hysteresis_loop && <span>No hysteresis loop</span>}
                {model.capabilities.core_loss && <span className="info">Generic Steinmetz loss estimate</span>}
              </>}
              {model.kind === 'permanent_magnet' && <>
                {model.capabilities.material_curve && <span className="positive">Linear recoil model</span>}
                {!model.capabilities.demagnetization_assessment && <span>No demagnetization check</span>}
              </>}
              {model.kind === 'conductor' && <span className="info">No B–H curve used</span>}
            </div>
            <ul>
              {model.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
            </ul>
            {model.source && (
              <a href={model.source.url} target="_blank" rel="noreferrer">
                Review source and limitations ↗
              </a>
            )}
          </aside>
        </div>
      ) : (
        <div className="public-material-behavior-empty" role="status">
          <strong>Material model details unavailable</strong>
          <p>Reconnect the local backend to load the curve, revision, and provenance for {selectedOption.materialId}.</p>
        </div>
      )}
    </section>
  );
}
