import { useId } from 'react';
import type { RotorLayout } from './model';
import { PUBLIC_MOTOR_COLORS as COLORS } from './motorPalette';

const CX = 105;
const CY = 114;
const polar = (radius: number, degrees: number) => {
  const angle = degrees * Math.PI / 180;
  return [CX + radius * Math.cos(angle), CY + radius * Math.sin(angle)] as const;
};
const point = (radius: number, degrees: number) => polar(radius, degrees).map((n) => n.toFixed(3)).join(' ');

function sector(inner: number, outer: number, start: number, end: number): string {
  return `M ${point(outer, start)} A ${outer} ${outer} 0 0 1 ${point(outer, end)} L ${point(inner, end)} A ${inner} ${inner} 0 0 0 ${point(inner, start)} Z`;
}

function ring(outer: number, inner: number): string {
  return `M ${CX + outer} ${CY} A ${outer} ${outer} 0 1 0 ${CX - outer} ${CY} A ${outer} ${outer} 0 1 0 ${CX + outer} ${CY} Z M ${CX + inner} ${CY} A ${inner} ${inner} 0 1 1 ${CX - inner} ${CY} A ${inner} ${inner} 0 1 1 ${CX + inner} ${CY} Z`;
}

export type MotorPreviewVariant = 'arrangement' | 'spm' | 'flat_buried' | 'v_shape';

// As in the geometry builder, the V opens toward the airgap, with an inward
// apex and a steel web between its two rectangular slabs.
function vMagnet(side: number): string {
  const angle = 50 * Math.PI / 180;
  const axis = [Math.cos(angle), side * Math.sin(angle)];
  const normal = [Math.sin(angle), -side * Math.cos(angle)];
  return [
    [0, -2.5], [15, -2.5], [15, 2.5], [0, 2.5],
  ].map(([along, across]) => `${CX + 33 + along * axis[0] + across * normal[0]},${CY + side * 3 + along * axis[1] + across * normal[1]}`).join(' ');
}

/** Small explanatory cross-sections, independent of the user's unfinished motor. */
export function RotorArrangementPreview({ layout, variant = 'arrangement' }: { layout: RotorLayout; variant?: MotorPreviewVariant }) {
  const id = useId().replace(/:/g, '');
  const buried = variant === 'flat_buried' || variant === 'v_shape';
  const outer = !buried && layout === 'outer';
  const name = variant === 'arrangement' ? outer ? 'Outrunner' : 'Inrunner'
    : variant === 'spm' ? 'SPM' : variant === 'flat_buried' ? 'IPM · flat buried' : 'IPM · V-shape';
  const summary = variant === 'arrangement' ? outer ? 'Rotor outside. Stator stays inside.' : 'Rotor inside. Stator stays outside.'
    : variant === 'spm' ? 'Permanent magnets sit on the rotor surface.'
    : variant === 'flat_buried' ? 'Straight magnet bars sit inside the rotor steel.' : 'Paired magnets form a V inside each rotor pole.';
  const magnetLocation = buried ? variant === 'v_shape' ? 'Paired inside rotor' : 'Buried inside rotor'
    : outer ? 'Inner face of rotor' : 'Outer face of rotor';
  const accessibleDescription = buried ? `fixed outer stator, rotating inner rotor, ${variant === 'v_shape' ? 'two angled magnets per pole forming a V' : 'one straight tangential magnet bar per pole'} enclosed in rotor steel`
    : outer ? 'fixed inner stator, rotating outer rotor, magnets on the rotor’s inner face' : 'fixed outer stator, rotating inner rotor, magnets on the rotor’s outer face';
  const steel = `url(#${id}-steel)`;
  const rotor = `url(#${id}-rotor)`;
  const label = (title: string, subtitle: string, radius: number, angle: number, y: number, color: string) => {
    const [x, py] = polar(radius, angle);
    return <g className="arrangement-preview-callout">
      <path d={`M ${x} ${py} L 207 ${y} H 219`} />
      <circle cx={x} cy={py} r="2.5" fill={color} />
      <text x="227" y={y - 2} className="arrangement-preview-part">{title}</text>
      <text x="227" y={y + 12} className="arrangement-preview-detail">{subtitle}</text>
    </g>;
  };
  return <>
    <div className="arrangement-preview-heading">
      <h3>{name}</h3><span>8 poles · 12 slots</span>
    </div>
    <p className="arrangement-preview-summary">{summary}</p>
    <svg viewBox="0 0 352 228" role="img" data-arrangement={outer ? 'outer' : 'inner'}
      data-topology={buried ? 'IPM' : 'SPM'} data-ipm-layout={buried ? variant : undefined}
      aria-label={`${name} ${buried ? 'interior-PM' : 'surface-PM'} motor cross-section: ${accessibleDescription}. Eight poles and twelve slots.`}>
      <defs>
        <linearGradient id={`${id}-steel`} gradientUnits="userSpaceOnUse" x1="35" y1="35" x2="181" y2="205">
          <stop stopColor="#b1c0ce" /><stop offset="1" stopColor={COLORS.statorSteel} />
        </linearGradient>
        <linearGradient id={`${id}-rotor`} gradientUnits="userSpaceOnUse" x1="48" y1="38" x2="174" y2="206">
          <stop stopColor="#697d95" /><stop offset="1" stopColor="#3e4c61" />
        </linearGradient>
      </defs>
      <circle cx={CX} cy={CY} r="91" fill="none" stroke="rgba(143,163,184,.1)" />
      <g stroke="#111822" strokeWidth="0.9" strokeLinejoin="round">
        {Array.from({ length: 12 }, (_, i) => <path key={`tooth-${i}`} data-part="stator-tooth"
          d={sector(outer ? 36 : 58, outer ? 60 : 74, i * 30 - 8.5, i * 30 + 8.5)} fill={steel} />)}
        <path data-part="stator" d={ring(outer ? 38 : 85, outer ? 25 : 73)} fill={steel} fillRule="evenodd" />
        {Array.from({ length: 12 }, (_, i) => <path key={`coil-${i}`}
          d={sector(outer ? 40 : 62, outer ? 56 : 71.5, i * 30 + 10.5, i * 30 + 19.5)} fill={COLORS.winding} opacity="0.9" />)}
        <path data-part="rotor" d={ring(outer ? 85 : buried ? 53 : 43, outer ? 74 : 14)} fill={rotor} fillRule="evenodd" />
        {Array.from({ length: 8 }, (_, i) => {
          const fill = i % 2 === 0 ? COLORS.magnetNorth : COLORS.magnetSouth;
          return buried ? <g key={`pole-${i}`} data-pole={i} transform={`rotate(${i * 45} ${CX} ${CY})`}>
            {variant === 'flat_buried'
              ? <rect data-part="magnet" x={CX + 40} y={CY - 13} width="7" height="26" fill={fill} />
              : [1, -1].map((side) => <polygon key={side} data-part="magnet" points={vMagnet(side)} fill={fill} />)}
          </g> : <path key={`magnet-${i}`} data-part="magnet"
            d={sector(outer ? 65 : 43, outer ? 74 : 53, i * 45 - 16.5, i * 45 + 16.5)} fill={fill} />;
        })}
      </g>
      {label('Stator', 'Fixed', outer ? 48 : 80, outer ? -60 : -48, 45, COLORS.statorSteel)}
      {label('Magnets', magnetLocation, outer ? 69.5 : variant === 'flat_buried' ? 43.5 : variant === 'v_shape' ? 39 : 48, variant === 'v_shape' ? 13 : 0, 114, COLORS.magnetNorth)}
      {label('Rotor', 'Rotates', outer ? 80 : buried ? 26 : 34, 48, 185, COLORS.rotorSteel)}
    </svg>
    <div className="arrangement-preview-footer">{buried ? variant === 'v_shape' ? 'V-shaped interior magnets' : 'Flat buried magnets' : 'Surface permanent magnets'} · illustrative cross-section</div>
  </>;
}
