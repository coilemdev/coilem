import React from 'react';
import { SATURATION_THRESHOLD_T, formatTesla, isSaturationSteelRegion } from './magneticCircuit';

interface SaturationFieldProps {
  nodesMm: [number, number][];
  triangles: [number, number, number][];
  regions: string[];
  elementBMagT: number[] | null | undefined;
  threshold?: number;
  scaleMaxT?: number;
  shaftRadiusMm?: number;
}

const VIEW = 520;
const PAD = 18;

// Cool -> warm ramp for sub-saturation |B|; saturated elements are forced to a
// hot band so they pop out of the cross-section.
const RAMP: Array<[number, string]> = [
  [0.0, '#0b1f3a'],
  [0.25, '#1d4ed8'],
  [0.5, '#0891b2'],
  [0.7, '#22c55e'],
  [0.85, '#eab308'],
  [1.0, '#f97316'],
];

function lerpColor(a: string, b: string, t: number): string {
  const pa = [parseInt(a.slice(1, 3), 16), parseInt(a.slice(3, 5), 16), parseInt(a.slice(5, 7), 16)];
  const pb = [parseInt(b.slice(1, 3), 16), parseInt(b.slice(3, 5), 16), parseInt(b.slice(5, 7), 16)];
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

function rampColor(fraction: number): string {
  const f = Math.max(0, Math.min(1, fraction));
  for (let i = 0; i < RAMP.length - 1; i += 1) {
    const [stop0, color0] = RAMP[i];
    const [stop1, color1] = RAMP[i + 1];
    if (f >= stop0 && f <= stop1) {
      const span = stop1 - stop0;
      return lerpColor(color0, color1, span > 1e-9 ? (f - stop0) / span : 0);
    }
  }
  return RAMP[RAMP.length - 1][1];
}

export const SaturationField: React.FC<SaturationFieldProps> = ({
  nodesMm,
  triangles,
  regions,
  elementBMagT,
  threshold = SATURATION_THRESHOLD_T,
  scaleMaxT,
  shaftRadiusMm,
}) => {
  const [zoom, setZoom] = React.useState(1);
  const projection = React.useMemo(() => {
    if (nodesMm.length === 0) return null;
    const xs = nodesMm.map((n) => n[0]);
    const ys = nodesMm.map((n) => n[1]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const range = Math.max(maxX - minX, maxY - minY) || 1;
    const scale = (VIEW - PAD * 2) / range;
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    // Center the geometry and flip Y for SVG screen space.
    const project = (x: number, y: number): [number, number] => [
      VIEW / 2 + (x - cx) * scale,
      VIEW / 2 - (y - cy) * scale,
    ];
    return { project, scale };
  }, [nodesMm]);

  const hasField = Array.isArray(elementBMagT) && elementBMagT.length === triangles.length;
  const hasRegions = regions.length === triangles.length;
  const scaleMax = Math.max(scaleMaxT ?? 0, threshold, 1.0);
  const viewSize = VIEW / zoom;
  const viewOffset = (VIEW - viewSize) / 2;

  const zoomIn = () => setZoom((current) => Math.min(4, current * 1.25));
  const zoomOut = () => setZoom((current) => Math.max(0.75, current / 1.25));
  const fitToView = () => setZoom(1);

  if (!projection) {
    return (
      <div className="tutorial-saturation-empty">
        <strong>No cross-section to color yet</strong>
        <span>Run the balanced solve to load the |B| field.</span>
      </div>
    );
  }

  const shaftR = shaftRadiusMm ? shaftRadiusMm * projection.scale : 0;

  return (
    <figure className="tutorial-saturation-figure">
      <div className="tutorial-saturation-viewport">
        <svg
          className="tutorial-saturation-svg"
          viewBox={`${viewOffset} ${viewOffset} ${viewSize} ${viewSize}`}
          role="img"
          aria-label="Iron saturation colormap of the motor cross-section"
        >
          <g>
            {triangles.map((tri, index) => {
              const a = nodesMm[tri[0]];
              const b = nodesMm[tri[1]];
              const c = nodesMm[tri[2]];
              if (!a || !b || !c) return null;
              const pa = projection.project(a[0], a[1]);
              const pb = projection.project(b[0], b[1]);
              const pc = projection.project(c[0], c[1]);
              const bMag = hasField ? elementBMagT![index] : NaN;
              const isSteel = hasRegions && isSaturationSteelRegion(regions[index]);
              const saturated = isSteel && Number.isFinite(bMag) && bMag >= threshold;
              const fill = isSteel && hasField && Number.isFinite(bMag)
                ? (saturated ? '#ef4444' : rampColor(bMag / scaleMax))
                : '#111827';
              return (
                <polygon
                  key={index}
                  points={`${pa[0].toFixed(1)},${pa[1].toFixed(1)} ${pb[0].toFixed(1)},${pb[1].toFixed(1)} ${pc[0].toFixed(1)},${pc[1].toFixed(1)}`}
                  fill={fill}
                  stroke={saturated ? '#fecaca' : 'none'}
                  strokeWidth={saturated ? 0.6 : 0}
                  opacity={isSteel && hasField ? 0.96 : 0.42}
                />
              );
            })}
          </g>
          {shaftR > 0 ? (
            <circle cx={VIEW / 2} cy={VIEW / 2} r={shaftR} fill="#0b1220" stroke="#334155" strokeWidth="1.5" />
          ) : null}
        </svg>

        <div className="mesh-viewer-toolbar is-zoom-only tutorial-saturation-toolbar" aria-label="Saturation view controls">
          <div className="mesh-viewer-controls">
            <button onClick={zoomIn} title="Zoom in" type="button">+</button>
            <button onClick={zoomOut} title="Zoom out" type="button">−</button>
            <button onClick={fitToView} title="Fit to view" type="button">Fit</button>
          </div>
          <span className="mesh-viewer-toolbar-label">|B| saturation</span>
        </div>
      </div>
      <figcaption className="tutorial-saturation-legend">
        <span className="tutorial-saturation-ramp" aria-hidden="true" />
        <div className="tutorial-saturation-legend-row">
          <span>0 T</span>
          <span className="tutorial-saturation-threshold-mark">
            ≥ {formatTesla(threshold)} saturating
          </span>
          <span>{formatTesla(scaleMax)}</span>
        </div>
        {!hasField || !hasRegions ? (
          <p className="tutorial-saturation-note">
            Steel-region |B| is not available for this frame — showing muted geometry only.
          </p>
        ) : null}
      </figcaption>
    </figure>
  );
};
