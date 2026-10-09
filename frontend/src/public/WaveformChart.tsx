import { useState } from 'react';

export interface WaveformSeries {
  id?: string;
  label: string;
  legendLabel?: string;
  groupLabel?: string;
  angles?: number[];
  values: number[];
  color: string;
  dashArray?: string;
}

interface WaveformChartProps {
  angles: number[];
  values?: number[];
  series?: WaveformSeries[];
  label: string;
  unit: string;
  samplingLabel?: string;
  toggleableSeries?: boolean;
  hiddenSeriesKeys?: string[];
  onHiddenSeriesKeysChange?: (keys: string[]) => void;
}

function periodicAxisEnd(angles: number[]) {
  const sortedAngles = [...new Set(angles)].sort((left, right) => left - right);
  if (sortedAngles.length < 2) return sortedAngles[0] || 0;
  const finalAngle = sortedAngles[sortedAngles.length - 1];
  const finalStep = finalAngle - sortedAngles[sortedAngles.length - 2];
  const inferredEnd = finalAngle + finalStep;
  const tolerance = Math.max(Math.abs(finalStep) * 0.05, 0.01);
  return Math.abs(sortedAngles[0]) <= tolerance && Math.abs(inferredEnd - 360) <= tolerance
    ? 360
    : finalAngle;
}

export function WaveformChart({ angles, values, series, label, unit, samplingLabel, toggleableSeries = false, hiddenSeriesKeys: controlledHiddenSeriesKeys, onHiddenSeriesKeysChange }: WaveformChartProps) {
  const [internalHiddenSeriesKeys, setInternalHiddenSeriesKeys] = useState<string[]>([]);
  const hiddenSeriesKeys = controlledHiddenSeriesKeys || internalHiddenSeriesKeys;
  const eligibleSeries = (series || (values ? [{ label, values, color: '#de7948' }] : []))
    .map((item) => ({ ...item, angles: item.angles || angles }))
    .filter((item) => item.angles.length >= 2 && item.values.length === item.angles.length);
  const seriesKey = (item: WaveformSeries, index: number) => item.id || `${index}:${item.label}`;
  const plottedSeries = toggleableSeries
    ? eligibleSeries.filter((item, index) => !hiddenSeriesKeys.includes(seriesKey(item, index)))
    : eligibleSeries;
  if (plottedSeries.length === 0) return null;

  const toggleSeries = (item: WaveformSeries, index: number) => {
    const key = seriesKey(item, index);
    const visible = !hiddenSeriesKeys.includes(key);
    if (visible && plottedSeries.length === 1) return;
    const next = hiddenSeriesKeys.includes(key)
      ? hiddenSeriesKeys.filter((candidate) => candidate !== key)
      : [...hiddenSeriesKeys, key];
    if (onHiddenSeriesKeysChange) onHiddenSeriesKeysChange(next);
    else setInternalHiddenSeriesKeys(next);
  };

  const width = 760;
  const height = 250;
  const margin = { top: 22, right: 24, bottom: 38, left: 56 };
  const allAngles = plottedSeries.flatMap((item) => item.angles);
  const minX = Math.min(...allAngles);
  const maxX = Math.max(...allAngles);
  const axisMaxX = Math.max(maxX, ...plottedSeries.map((item) => periodicAxisEnd(item.angles)));
  const allValues = plottedSeries.flatMap((item) => item.values);
  const rawMinY = Math.min(...allValues);
  const rawMaxY = Math.max(...allValues);
  const yPadding = Math.max((rawMaxY - rawMinY) * 0.15, Math.abs(rawMaxY) * 0.05, 0.01);
  const minY = rawMinY - yPadding;
  const maxY = rawMaxY + yPadding;
  const x = (value: number) => margin.left + ((value - minX) / Math.max(axisMaxX - minX, 1)) * (width - margin.left - margin.right);
  const y = (value: number) => margin.top + ((maxY - value) / Math.max(maxY - minY, 1)) * (height - margin.top - margin.bottom);
  const pathFor = (seriesAngles: number[], seriesValues: number[]) => seriesValues
    .map((value, index) => `${index === 0 ? 'M' : 'L'} ${x(seriesAngles[index]).toFixed(2)} ${y(value).toFixed(2)}`)
    .join(' ');
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const fillId = `wave-fill-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  const positionCounts = [...new Set(eligibleSeries.map((item) => item.angles.length))];
  const renderedSeries = [...plottedSeries].sort((left, right) => Number(Boolean(left.dashArray)) - Number(Boolean(right.dashArray)));
  const groupedLegend = eligibleSeries.length > 1 && eligibleSeries.every((item) => Boolean(item.groupLabel));
  const legendGroups: Array<{ label: string; entries: Array<{ item: WaveformSeries; index: number }> }> = [];
  if (groupedLegend) {
    eligibleSeries.forEach((item, index) => {
      const groupLabel = item.groupLabel || '';
      let group = legendGroups.find((candidate) => candidate.label === groupLabel);
      if (!group) {
        group = { label: groupLabel, entries: [] };
        legendGroups.push(group);
      }
      group.entries.push({ item, index });
    });
  }

  const legendControl = (item: WaveformSeries, index: number) => {
    const key = seriesKey(item, index);
    const visible = !toggleableSeries || !hiddenSeriesKeys.includes(key);
    const text = item.legendLabel || item.label;
    const swatchStyle = item.dashArray
      ? { background: `repeating-linear-gradient(90deg, ${item.color} 0 6px, transparent 6px 10px)` }
      : { backgroundColor: item.color };
    return toggleableSeries
      ? <button
          type="button"
          key={key}
          aria-label={item.label}
          aria-pressed={visible}
          disabled={visible && plottedSeries.length === 1}
          title={`${visible ? 'Hide' : 'Show'} ${item.label}`}
          onClick={() => toggleSeries(item, index)}
        ><i style={swatchStyle} />{text}</button>
      : <span key={key} aria-label={item.label}><i style={swatchStyle} />{text}</span>;
  };

  return (
    <div className="chart-shell">
      <div className="chart-heading">
        <span>{label}</span>
        <span>{samplingLabel || `${positionCounts.join(' / ')} positions`}</span>
      </div>
      {eligibleSeries.length > 1 && (
        <div className={`public-waveform-legend${groupedLegend ? ' public-waveform-legend-grouped' : ''}`} aria-label={`${label} series`}>
          {groupedLegend
            ? legendGroups.map((group) => <div className="public-waveform-legend-row" role="group" aria-label={group.label} key={group.label}>
                <strong>{group.label}</strong>
                {group.entries.map(({ item, index }) => legendControl(item, index))}
              </div>)
            : eligibleSeries.map((item, index) => legendControl(item, index))}
        </div>
      )}
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label} waveform`}>
        <defs>
          <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={plottedSeries[0].color} stopOpacity="0.34" />
            <stop offset="1" stopColor={plottedSeries[0].color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((tick) => {
          const tickY = margin.top + tick * (height - margin.top - margin.bottom);
          const value = maxY - tick * (maxY - minY);
          return (
            <g key={tick}>
              <line x1={margin.left} x2={width - margin.right} y1={tickY} y2={tickY} className="chart-grid" />
              <text x={margin.left - 10} y={tickY + 4} textAnchor="end" className="chart-label">{value.toFixed(2)}</text>
            </g>
          );
        })}
        {plottedSeries.length === 1 && (
          <path
            d={`${pathFor(plottedSeries[0].angles, plottedSeries[0].values)} L ${x(plottedSeries[0].angles[plottedSeries[0].angles.length - 1]).toFixed(2)} ${height - margin.bottom} L ${x(plottedSeries[0].angles[0]).toFixed(2)} ${height - margin.bottom} Z`}
            fill={`url(#${fillId})`}
          />
        )}
        {renderedSeries.map((item, index) => (
          <path key={item.id || `${item.label}-${index}`} d={pathFor(item.angles, item.values)} fill="none" stroke={item.color} strokeWidth="2" strokeDasharray={item.dashArray} strokeLinecap="round" strokeLinejoin="round" />
        ))}
        <text x={margin.left} y={height - 12} className="chart-label">{minX.toFixed(0)}°</text>
        <text x={width - margin.right} y={height - 12} textAnchor="end" className="chart-label">{axisMaxX.toFixed(0)}° electrical</text>
        <text x={margin.left} y="12" className="chart-label chart-unit-label">{unit}</text>
      </svg>
    </div>
  );
}
