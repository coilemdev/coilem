import type { ReactNode } from 'react';
import type { PerformanceOutputStatus } from './performance';
import { STATUS_LABEL, type NamedOutputStatus } from './outputStatus';
import { Popover } from './Popover';

export function StatusBadge({ status, title }: { status: PerformanceOutputStatus; title?: string }) {
  return <span className={`losses-status is-${status}`} title={title}>{STATUS_LABEL[status]}</span>;
}

/** Each output's status with its reason in words (public issue 143). */
export function OutputStatusList({ statuses }: { statuses: NamedOutputStatus[] }) {
  if (!statuses.length) return null;
  return (
    <ul className="output-status-list">
      {statuses.map((item) => (
        <li key={item.key}>
          <StatusBadge status={item.status} />
          <span><strong>{item.label}.</strong> {item.reason}</span>
        </li>
      ))}
    </ul>
  );
}

const STATUS_ORDER: PerformanceOutputStatus[] = ['qualified', 'experimental', 'unavailable'];

/** "Experimental · 3", or "1 qualified · 2 experimental" when a card mixes them. */
export function statusSummaryText(statuses: NamedOutputStatus[]): string {
  const counts = STATUS_ORDER.map((status) => [status, statuses.filter((item) => item.status === status).length] as const)
    .filter(([, count]) => count > 0);
  if (counts.length === 1) {
    const [status, count] = counts[0];
    return count > 1 ? `${STATUS_LABEL[status]} · ${count}` : STATUS_LABEL[status];
  }
  return counts.map(([status, count]) => `${count} ${STATUS_LABEL[status].toLowerCase()}`).join(' · ');
}

/**
 * A card's statuses as one pill in its header. The pill opens every output's
 * status with its reason in words, the list each card used to print below it,
 * so no status or reason is dropped (public issue 143).
 */
export function StatusSummary({ statuses, children, align }: { statuses: NamedOutputStatus[]; children?: ReactNode; align?: 'start' | 'end' }) {
  if (!statuses.length) return null;
  const least = STATUS_ORDER.slice().reverse().find((status) => statuses.some((item) => item.status === status)) ?? 'experimental';
  const mixed = statuses.some((item) => item.status !== statuses[0].status);
  return (
    <Popover
      align={align}
      className="status-summary"
      trigger={(props) => (
        <button type="button" className={`losses-status is-${mixed ? 'mixed' : least}`} {...props}>
          {statusSummaryText(statuses)}<span aria-hidden="true"> ▾</span>
        </button>
      )}
    >
      <OutputStatusList statuses={statuses} />
      {children}
    </Popover>
  );
}

/** One output's status as a dot beside its value; the dot opens the status and its reason. */
export function StatusDot({ status, label, reason }: { status: PerformanceOutputStatus; label: string; reason: string }) {
  return (
    <Popover
      align="end"
      trigger={(props) => <button type="button" className={`status-dot is-${status}`} aria-label={`${label}: ${STATUS_LABEL[status]}`} {...props} />}
    >
      <p className="popover-status"><StatusBadge status={status} /> {reason}</p>
    </Popover>
  );
}
