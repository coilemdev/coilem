import { Popover } from './Popover';

/** A small filled arrowhead pointing along (dx, dy) with its tip at (x, y). */
function Arrowhead({ x, y, dx, dy }: { x: number; y: number; dx: number; dy: number }) {
  const length = Math.hypot(dx, dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  const back = { x: x - ux * 6, y: y - uy * 6 };
  return <polygon className="convergence-help-arrow" points={`${x},${y} ${back.x - uy * 3.5},${back.y + ux * 3.5} ${back.x + uy * 3.5},${back.y - ux * 3.5}`} />;
}

/** Why the solver iterates: steel saturates, so how it carries flux depends on the field. */
function SaturationSketch() {
  return (
    <svg viewBox="0 0 360 70" role="img" aria-label="Sketch of a steel B–H curve: steep at low field, flat once saturated.">
      <rect x="136" y="4" width="214" height="54" className="convergence-help-saturated" />
      <line x1="30" y1="58" x2="350" y2="58" className="convergence-help-axis" />
      <line x1="30" y1="58" x2="30" y2="4" className="convergence-help-axis" />
      <path d="M30 58 L84 20 Q106 9 150 8 L350 5" className="convergence-help-curve" />
      <text x="24" y="12" textAnchor="end" className="convergence-help-text">B</text>
      <text x="350" y="68" textAnchor="end" className="convergence-help-text">field H</text>
      <text x="62" y="50" className="convergence-help-text">easy</text>
      <text x="244" y="26" textAnchor="middle" className="convergence-help-text">saturated: more field, little more flux</text>
    </svg>
  );
}

/** The loop each rotor position runs, and its exit. */
function LoopSketch({ stoppingRule }: { stoppingRule: string }) {
  const boxes = [
    { x: 2, label: 'Solve the field' },
    { x: 124, label: 'Read B in the steel' },
    { x: 246, label: 'Update the steel' },
  ];
  return (
    <svg viewBox="0 0 360 80" role="img" aria-label={`Loop: solve the field, read B in the steel, update the steel, repeat; stop once ${stoppingRule}.`}>
      {boxes.map(box => (
        <g key={box.label}>
          <rect x={box.x} y="4" width="112" height="28" rx="6" className="convergence-help-box" />
          <text x={box.x + 56} y="22" textAnchor="middle" className="convergence-help-text is-strong">{box.label}</text>
        </g>
      ))}
      <line x1="114" y1="18" x2="122" y2="18" className="convergence-help-axis" />
      <Arrowhead x={124} y={18} dx={1} dy={0} />
      <line x1="236" y1="18" x2="244" y2="18" className="convergence-help-axis" />
      <Arrowhead x={246} y={18} dx={1} dy={0} />
      <path d="M302 32 V50 H58 V36" className="convergence-help-loop" />
      <Arrowhead x={58} y={33} dx={0} dy={-1} />
      <text x="180" y="46" textAnchor="middle" className="convergence-help-text">repeat</text>
      <text x="180" y="70" textAnchor="middle" className="convergence-help-text is-ok">✓ stop once {stoppingRule}</text>
    </svg>
  );
}

/** When a position stops: the change falls each iteration until it is under the allowed error. */
function StoppingSketch({ allowed }: { allowed: string }) {
  const left = 30;
  const right = 300;
  const review = left + 0.8 * (right - left);
  return (
    <svg viewBox="0 0 360 96" role="img" aria-label={`Sketch: the change in the steel falls each iteration; the position stops at the first iteration under the allowed ${allowed}, before the 80% review mark and the iteration limit.`}>
      <line x1={left} y1="76" x2={right} y2="76" className="convergence-help-axis" />
      <line x1={left} y1="76" x2={left} y2="10" className="convergence-help-axis" />
      <line x1={review} y1="12" x2={review} y2="76" className="convergence-help-review" />
      <line x1={right} y1="12" x2={right} y2="76" className="convergence-help-axis" />
      <line x1={left} y1="58" x2={right} y2="58" className="convergence-help-allowed" />
      <path d="M30 14 C70 30 120 46 190 56 L204 58" className="convergence-help-curve" />
      <circle cx="204" cy="58" r="4" className="convergence-help-stop" />
      <text x="204" y="50" textAnchor="middle" className="convergence-help-text is-ok">converged</text>
      <text x={review} y="9" textAnchor="middle" className="convergence-help-text is-warning">80%</text>
      <text x={right} y="9" textAnchor="middle" className="convergence-help-text">limit</text>
      <text x={right + 6} y="61" className="convergence-help-text is-ok">allowed {allowed}</text>
      <text x="36" y="9" className="convergence-help-text">change in the steel</text>
      <text x={right} y="90" textAnchor="end" className="convergence-help-text">iterations →</text>
    </svg>
  );
}

/**
 * "How the solver converges": an info button beside the Solver convergence
 * title that opens, on hover, focus or tap, three small sketches of why the
 * solve repeats, the loop, and when a position stops.
 */
export function ConvergenceHelp({ stoppingRule, allowedError, iterationLimit }: {
  stoppingRule: string;
  allowedError: string | null;
  iterationLimit: number | null;
}) {
  const run = [
    allowedError ? `allowed change ${allowedError}` : null,
    iterationLimit ? `up to ${iterationLimit} iterations per position` : null,
  ].filter(Boolean).join(', ');
  return (
    <Popover
      className="convergence-help"
      trigger={(props) => <button type="button" className="info-tip" aria-label="How the solver converges" {...props}>i</button>}
    >
      <p><strong>Why it repeats.</strong> Steel saturates, so how easily it carries flux depends on the field being solved.</p>
      <SaturationSketch />
      <p><strong>At each rotor position</strong> the solver loops until the steel settles.</p>
      <LoopSketch stoppingRule={stoppingRule} />
      <p><strong>When it stops.</strong> At the first iteration under the allowed error, so it always ends just under it.</p>
      <StoppingSketch allowed={allowedError ?? 'error'} />
      <p>Past 80% of the limit it is <strong>Slow</strong>; reaching the limit first means <strong>Stopped early</strong>.</p>
      {run && <p className="popover-note">This run: {run}.</p>}
    </Popover>
  );
}
