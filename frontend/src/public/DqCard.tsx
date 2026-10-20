import { useId } from 'react';
import type { DqFluxLinkage } from './performance';
import { dqView } from './dqView';

/**
 * The loaded d/q operating point of a completed run (#113): currents, flux
 * linkages, apparent inductances and the d/q torque check. Renders nothing
 * for a run without a d/q record.
 */
export function DqCard({ dq, variant = 'panel' }: { dq?: DqFluxLinkage | null; variant?: 'panel' | 'report' }) {
  const headingId = useId();
  const view = dqView(dq);
  if (!view) return null;
  return (
    <section className={`motor-constants dq-card${variant === 'report' ? ' is-report' : ''}`} aria-labelledby={headingId}>
      <h3 id={headingId}>d/q operating point</h3>
      <table>
        <tbody>
          {view.rows.map((row) => (
            <tr key={row.key} title={row.hint}>
              <th scope="row">
                <span className="motor-constants-symbol">{row.symbol}</span> <span className="motor-constants-name">{row.name}</span>
              </th>
              <td className="motor-constants-value">{row.value}</td>
              <td className="motor-constants-unit">{row.unit}</td>
            </tr>
          ))}
          <tr className="motor-constants-consistency" title={view.agreement.hint}>
            <th scope="row">
              <span className="motor-constants-symbol">Torque–λdq</span> <span className="motor-constants-name">agreement</span>
            </th>
            <td className="motor-constants-value">{view.agreement.text}</td>
            <td className="motor-constants-unit">
              %
              {view.agreement.status !== 'unavailable' && (
                <span className={`motor-constants-status is-${view.agreement.status}`}>{view.agreement.status === 'ok' ? 'OK' : 'Check'}</span>
              )}
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}
