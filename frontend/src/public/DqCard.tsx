import { useId, useState } from 'react';
import type { DqFluxLinkage } from './performance';
import { dqView, type DqCurrentUnit, type DqRow } from './dqView';
import { StatusSummary } from './OutputStatusBadge';

function Row({ row }: { row: DqRow }) {
  return (
    <tr title={row.hint}>
      <th scope="row">
        <span className="motor-constants-symbol">{row.symbol}</span> <span className="motor-constants-name">{row.name}</span>
      </th>
      <td className="motor-constants-value">{row.value}</td>
      <td className="motor-constants-unit">{row.unit}</td>
    </tr>
  );
}

/**
 * The loaded d/q operating point of a completed run (#113): the inductances,
 * saliency and characteristic current first, then the torque check, with the
 * full record one click away. Renders nothing for a run without a d/q record.
 */
export function DqCard({ dq, currentUnit = 'A peak', variant = 'panel' }: {
  dq?: DqFluxLinkage | null;
  currentUnit?: DqCurrentUnit;
  variant?: 'panel' | 'report';
}) {
  const headingId = useId();
  const detailId = useId();
  const [expanded, setExpanded] = useState(false);
  const view = dqView(dq, currentUnit);
  if (!view) return null;
  return (
    <section className={`motor-constants dq-card${variant === 'report' ? ' is-report' : ''}`} aria-labelledby={headingId}>
      <div className="results-card-heading">
        <h3 id={headingId}>d/q operating point</h3>
        <StatusSummary statuses={[{ key: 'dq', label: 'd/q flux linkage and inductances', ...view.status }]} />
      </div>
      <table>
        <tbody>
          {view.main.map((row) => <Row key={row.key} row={row} />)}
          {view.agreement && (
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
          )}
        </tbody>
        {expanded && (
          <tbody id={detailId} className="dq-card-detail">
            {view.detail.map((row) => <Row key={row.key} row={row} />)}
          </tbody>
        )}
      </table>
      {view.note && <p className="motor-constants-note">{view.note}</p>}
      <button type="button" className="dq-card-toggle" aria-expanded={expanded} aria-controls={detailId} onClick={() => setExpanded((open) => !open)}>
        {expanded ? 'Show fewer' : `Show all d/q values (${view.detail.length} more)`}
      </button>
    </section>
  );
}
