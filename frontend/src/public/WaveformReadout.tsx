import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
} from 'react';
import {
  formatWaveformReadoutAngle,
  formatWaveformReadoutDifference,
  formatWaveformReadoutValue,
  nearestWaveformReadoutIndex,
  steppedWaveformReadoutIndex,
  type WaveformReadoutValue,
} from './chartReadout';

interface WaveformReadoutOptions {
  /** Distinct solved angles of the visible series, in increasing order. */
  angles: readonly number[];
  /** The electrical angle at an x coordinate of the SVG's viewBox. */
  angleAtX: (svgX: number) => number;
  /** Changes when the plotted data does, which clears the selection. */
  dataKey: string;
}

/**
 * Selection state for a plot's readout. A click or tap selects the nearest
 * solved angle and a mouse hover previews one; arrow keys, Home and End step
 * through them when the plot has focus. Clicking the same point again, clicking
 * outside the chart or pressing Escape clears the selection.
 */
export function useWaveformReadout({ angles, angleAtX, dataKey }: WaveformReadoutOptions) {
  const [selectedAngle, setSelectedAngle] = useState<number | null>(null);
  const [previewAngle, setPreviewAngle] = useState<number | null>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const readoutId = useId();

  useEffect(() => {
    setSelectedAngle(null);
    setPreviewAngle(null);
  }, [dataKey]);

  const hasSelection = selectedAngle !== null;
  useEffect(() => {
    if (!hasSelection) return undefined;
    const clearOutside = (event: globalThis.PointerEvent) => {
      const chart = plotRef.current?.closest('.chart-shell');
      if (chart && event.target instanceof Node && !chart.contains(event.target)) setSelectedAngle(null);
    };
    document.addEventListener('pointerdown', clearOutside);
    return () => document.removeEventListener('pointerdown', clearOutside);
  }, [hasSelection]);

  // A stored angle snaps to the visible series, so hiding one keeps a solved position.
  const snapped = (angle: number | null) => {
    if (angle === null) return null;
    const index = nearestWaveformReadoutIndex(angles, angle);
    return index >= 0 ? index : null;
  };
  const selectedIndex = snapped(selectedAngle);
  const previewIndex = snapped(previewAngle);
  const shownIndex = previewIndex ?? selectedIndex;

  const indexAtPointer = (clientX: number, clientY: number) => {
    const matrix = svgRef.current?.getScreenCTM();
    if (!matrix) return -1;
    const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
    return nearestWaveformReadoutIndex(angles, angleAtX(point.x));
  };

  const plotProps = {
    ref: plotRef,
    tabIndex: 0,
    'aria-describedby': readoutId,
    onClick: (event: MouseEvent<HTMLDivElement>) => {
      const index = indexAtPointer(event.clientX, event.clientY);
      if (index < 0) return;
      setPreviewAngle(null);
      setSelectedAngle(index === selectedIndex ? null : angles[index]);
    },
    onPointerMove: (event: PointerEvent<HTMLDivElement>) => {
      if (event.pointerType !== 'mouse') return;
      const index = indexAtPointer(event.clientX, event.clientY);
      setPreviewAngle(index >= 0 ? angles[index] : null);
    },
    onPointerLeave: () => setPreviewAngle(null),
    onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Escape') {
        if (selectedAngle === null) return;
        event.preventDefault();
        event.stopPropagation();
        setSelectedAngle(null);
        return;
      }
      if (steppedWaveformReadoutIndex(null, angles.length, event.key) === null) return;
      event.preventDefault();
      setPreviewAngle(null);
      // Step from the latest selection, so key repeats never skip a position.
      setSelectedAngle((previous) => {
        const next = steppedWaveformReadoutIndex(snapped(previous), angles.length, event.key);
        return next === null ? previous : angles[next];
      });
    },
  };

  return {
    plotProps,
    svgRef,
    readoutId,
    shownAngle: shownIndex === null ? null : angles[shownIndex],
    previewing: previewIndex !== null && previewIndex !== selectedIndex,
  };
}

interface WaveformReadoutMarkerProps {
  x: number;
  top: number;
  bottom: number;
  points: Array<{ key: string; y: number; color: string }>;
  previewing: boolean;
}

/** The marker line and a dot on each shown trace at the selected angle. */
export function WaveformReadoutMarker({ x, top, bottom, points, previewing }: WaveformReadoutMarkerProps) {
  return (
    <g className={`public-waveform-marker${previewing ? ' is-preview' : ''}`} aria-hidden="true">
      <line x1={x} x2={x} y1={top} y2={bottom} />
      {points.map((point) => <circle key={point.key} cx={x} cy={point.y} r="4" fill={point.color} />)}
    </g>
  );
}

interface WaveformReadoutBarProps {
  id: string;
  angleDeg: number | null;
  angleNote?: string;
  values: readonly WaveformReadoutValue[];
  difference?: { label: string; value: number; unit: string } | null;
  previewing: boolean;
}

/** The angle and stored values of the shown position, under the plot header. */
export function WaveformReadoutBar({ id, angleDeg, angleNote, values, difference, previewing }: WaveformReadoutBarProps) {
  return (
    <div id={id} className={`public-waveform-readout${previewing ? ' is-preview' : ''}`} role="status" aria-live="polite">
      {angleDeg === null
        ? <span className="public-waveform-readout-hint">Click the plot to read a solved position · arrow keys step, Esc clears</span>
        : <>
            <strong>{formatWaveformReadoutAngle(angleDeg)} electrical{angleNote ? ` · ${angleNote}` : ''}</strong>
            {values.map((item) => (
              <span key={item.key}>
                <i style={{ backgroundColor: item.color }} aria-hidden="true" />
                {item.label}
                <b title={item.value === null ? undefined : `Stored value: ${item.value} ${item.unit}`}>
                  {item.value === null ? 'not solved at this angle' : formatWaveformReadoutValue(item.value, item.unit)}
                </b>
              </span>
            ))}
            {difference && (
              <span className="public-waveform-readout-difference">
                {difference.label}
                <b>{formatWaveformReadoutDifference(difference.value, difference.unit)}</b>
              </span>
            )}
          </>}
    </div>
  );
}
