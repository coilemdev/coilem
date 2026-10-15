import { type ReactNode, useId } from 'react';
import {
  CONSISTENCY_TOLERANCE_PCT,
  hasMotorConstants,
  motorConstantsView,
  type MotorConstantsSummary,
  type MotorConstantValue,
} from './machineConstants';

const CONSISTENCY_HELP = 'Average torque divided by the torque the back EMF predicts, Kt / (1.5·Ke). '
  + '100% is ideal for magnet torque with the current on the q-axis (0° current angle); a few percent low '
  + 'under load is normal. Saturation, reluctance torque or another current angle move it. '
  + `OK within ±${CONSISTENCY_TOLERANCE_PCT} points of 100%.`;

function Value({ item, children }: { item: MotorConstantValue; children?: ReactNode }) {
  return (
    <>
      <td className="motor-constants-value">{item.text}</td>
      <td className="motor-constants-unit">{item.unit}{children}</td>
    </>
  );
}

function Label({ symbol, name }: { symbol: string; name: string }) {
  return <><span className="motor-constants-symbol">{symbol}</span> <span className="motor-constants-name">{name}</span></>;
}

/**
 * Kt, Ke, λpm and the torque–EMF consistency of a completed run (#99), as a
 * table whose numbers share one right-aligned column. Renders nothing for a
 * run that reported none of them.
 */
export function MotorConstants({ summary }: { summary: MotorConstantsSummary }) {
  const headingId = useId();
  if (!hasMotorConstants(summary)) return null;
  const view = motorConstantsView(summary);
  return (
    <section className="motor-constants" aria-labelledby={headingId}>
      <h3 id={headingId}>Motor constants</h3>
      <table>
        <tbody>
          <tr>
            <th scope="row" rowSpan={2}><Label symbol="Kt" name="torque constant" /></th>
            <Value item={view.kt[0]} />
          </tr>
          <tr><Value item={view.kt[1]} /></tr>
          <tr>
            <th scope="row" rowSpan={2}><Label symbol="Ke" name="back-EMF constant" /></th>
            <Value item={view.ke[0]} />
          </tr>
          <tr><Value item={view.ke[1]} /></tr>
          <tr>
            <th scope="row"><Label symbol="λpm" name="magnet flux linkage" /></th>
            <Value item={view.lambdaPm} />
          </tr>
          <tr className="motor-constants-consistency" title={CONSISTENCY_HELP}>
            <th scope="row"><Label symbol="Torque–EMF" name="consistency" /></th>
            <Value item={view.consistency}>
              {view.consistencyStatus !== 'unavailable' && (
                <span className={`motor-constants-status is-${view.consistencyStatus}`}>
                  {view.consistencyStatus === 'ok' ? 'OK' : 'Check'}
                </span>
              )}
            </Value>
          </tr>
        </tbody>
      </table>
      {view.kt[0].value === null && (
        <p className="motor-constants-note">Kt and the consistency check need a loaded run with sinusoidal current.</p>
      )}
    </section>
  );
}
