import type { ReactNode } from 'react';

import type { PublicExampleId } from './exampleDesigns';
import { PUBLIC_MOTOR_COLORS } from './motorPalette';

type MotorTypeStatus = 'supported' | 'experimental' | 'soon';
type MotorTypeArt = 'spm' | 'flatIpm' | 'vShapeIpm' | 'outrunner' | 'axialFlux';

interface MotorType {
  art: MotorTypeArt;
  name: string;
  detail: string;
  status: MotorTypeStatus;
  /** The shipped example the tile opens; none while the type is not in the app. */
  exampleId?: PublicExampleId;
}

// Each status follows the rating Design Health gives that type's example
// (backend/qualification.py): "Supported" is a qualified design.
const MOTOR_TYPES: readonly MotorType[] = [
  { art: 'spm', name: 'SPM', detail: 'Surface magnets, inner rotor', status: 'supported', exampleId: 'spm-8p12s' },
  { art: 'flatIpm', name: 'Flat IPM', detail: 'Bar magnets buried in the rotor', status: 'supported', exampleId: 'ipm-14p-flat-buried-large' },
  { art: 'vShapeIpm', name: 'V-shape IPM', detail: 'Buried magnets in V pairs', status: 'experimental', exampleId: 'ipm-10p-v-shape-medium' },
  { art: 'outrunner', name: 'Outrunner', detail: 'Outer rotor, sine or BLDC drive', status: 'experimental', exampleId: 'spm-outrunner-14p12s' },
  { art: 'axialFlux', name: 'Axial Flux', detail: 'Disc rotor', status: 'soon' },
];

const STATUS_LABELS: Record<MotorTypeStatus, string> = {
  supported: 'Supported',
  experimental: 'Experimental',
  soon: 'Coming soon',
};

const STEEL = PUBLIC_MOTOR_COLORS.statorSteel;
const STEEL_DARK = PUBLIC_MOTOR_COLORS.rotorSteel;
const COPPER = PUBLIC_MOTOR_COLORS.winding;
const BORE = '#0e1117';
const C = 60;

const polar = (radius: number, angle: number) => (
  `${(C + radius * Math.cos(angle)).toFixed(2)} ${(C + radius * Math.sin(angle)).toFixed(2)}`
);

/** An annular sector between two radii, centred on `angle` and `span` radians wide. */
function sector(inner: number, outer: number, angle: number, span: number): string {
  const a0 = angle - span / 2;
  const a1 = angle + span / 2;
  return `M${polar(inner, a0)} L${polar(outer, a0)} A${outer} ${outer} 0 0 1 ${polar(outer, a1)} `
    + `L${polar(inner, a1)} A${inner} ${inner} 0 0 0 ${polar(inner, a0)} Z`;
}

const around = (count: number, draw: (angle: number, index: number) => ReactNode) => (
  Array.from({ length: count }, (_, index) => draw((index * Math.PI * 2) / count - Math.PI / 2, index))
);

const magnetFill = (index: number) => (index % 2 === 0 ? PUBLIC_MOTOR_COLORS.magnetNorth : PUBLIC_MOTOR_COLORS.magnetSouth);

/** A stator ring with its slots filled with copper, bore at `inner`. */
function Stator({ inner, outer, slots }: { inner: number; outer: number; slots: number }) {
  const slotDepth = (outer - inner) * 0.58;
  return (
    <>
      <circle cx={C} cy={C} r={outer} fill={STEEL} />
      {around(slots, (angle, index) => (
        <path key={index} d={sector(inner + 1.6, inner + 1.6 + slotDepth, angle, (Math.PI * 2) / slots * 0.56)} fill={COPPER} />
      ))}
      <circle cx={C} cy={C} r={inner} fill={BORE} />
    </>
  );
}

/** A bar magnet buried at `radius`, its long side `tilt` radians off the tangent. */
function Bar({ radius, angle, tilt, length, index }: { radius: number; angle: number; tilt: number; length: number; index: number }) {
  const degrees = ((angle + Math.PI / 2 + tilt) * 180) / Math.PI;
  const cx = C + radius * Math.cos(angle);
  const cy = C + radius * Math.sin(angle);
  return (
    <rect
      x={cx - length / 2}
      y={cy - 1.7}
      width={length}
      height={3.4}
      rx={0.5}
      fill={magnetFill(index)}
      transform={`rotate(${degrees.toFixed(2)} ${cx.toFixed(2)} ${cy.toFixed(2)})`}
    />
  );
}

function MotorTypeArtwork({ art }: { art: MotorTypeArt }) {
  let drawing: ReactNode;
  if (art === 'spm') {
    drawing = (
      <>
        <Stator inner={35} outer={56} slots={12} />
        {around(8, (angle, index) => <path key={index} d={sector(28.5, 33.5, angle, (Math.PI / 4) * 0.84)} fill={magnetFill(index)} />)}
        <circle cx={C} cy={C} r={28.5} fill={STEEL_DARK} />
        <circle cx={C} cy={C} r={7} fill={BORE} />
      </>
    );
  } else if (art === 'flatIpm' || art === 'vShapeIpm') {
    const poles = art === 'flatIpm' ? 8 : 6;
    drawing = (
      <>
        <Stator inner={35} outer={56} slots={art === 'flatIpm' ? 12 : 18} />
        <circle cx={C} cy={C} r={33.5} fill={STEEL_DARK} />
        {around(poles, (angle, index) => (art === 'flatIpm'
          ? <Bar key={index} radius={27} angle={angle} tilt={0} length={17} index={index} />
          : (
            <g key={index}>
              <Bar radius={25} angle={angle - 0.26} tilt={-0.62} length={12.5} index={index} />
              <Bar radius={25} angle={angle + 0.26} tilt={0.62} length={12.5} index={index} />
            </g>
          )))}
        <circle cx={C} cy={C} r={7} fill={BORE} />
      </>
    );
  } else if (art === 'outrunner') {
    drawing = (
      <>
        <circle cx={C} cy={C} r={56} fill={STEEL_DARK} />
        <circle cx={C} cy={C} r={51} fill={BORE} />
        {around(14, (angle, index) => <path key={index} d={sector(46.5, 51, angle, (Math.PI / 7) * 0.86)} fill={magnetFill(index)} />)}
        <circle cx={C} cy={C} r={44.5} fill={STEEL} />
        {around(12, (angle, index) => (
          <path key={index} d={sector(27, 41.5, angle, (Math.PI / 6) * 0.56)} fill={COPPER} />
        ))}
        <circle cx={C} cy={C} r={14} fill={BORE} />
      </>
    );
  } else {
    drawing = (
      <>
        <circle cx={C} cy={C} r={56} fill={STEEL_DARK} />
        {around(10, (angle, index) => <path key={index} d={sector(23, 51, angle, (Math.PI / 5) * 0.8)} fill={magnetFill(index)} />)}
        <circle cx={C} cy={C} r={17} fill={STEEL} />
        <circle cx={C} cy={C} r={7} fill={BORE} />
      </>
    );
  }
  return <svg className="landing-motor-type-art" viewBox="0 0 120 120" aria-hidden="true">{drawing}</svg>;
}

interface LandingMotorTypesProps {
  onLoadExample: (exampleId: PublicExampleId) => void;
}

/** The kinds of motor the app covers; each tile opens its shipped example. */
export function LandingMotorTypes({ onLoadExample }: LandingMotorTypesProps) {
  return (
    <section className="landing-motor-types" aria-labelledby="landing-motor-types-title">
      <h2 id="landing-motor-types-title">Motor Types</h2>
      <ul>
        {MOTOR_TYPES.map((type) => {
          const body = (
            <>
              <MotorTypeArtwork art={type.art} />
              <span className="landing-motor-type-text">
                <strong>{type.name}</strong>
                <small>{type.detail}</small>
                <em className={`landing-motor-type-status is-${type.status}`}>{STATUS_LABELS[type.status]}</em>
              </span>
            </>
          );
          const exampleId = type.exampleId;
          return (
            <li key={type.name}>
              {exampleId ? (
                <button
                  type="button"
                  className="landing-motor-type"
                  title={`Open the ${type.name} example`}
                  onClick={() => onLoadExample(exampleId)}
                >
                  {body}
                </button>
              ) : (
                <div className="landing-motor-type is-soon">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
