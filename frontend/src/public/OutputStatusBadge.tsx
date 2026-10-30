import type { PerformanceOutputStatus } from './performance';
import { STATUS_LABEL, type NamedOutputStatus } from './outputStatus';

export function StatusBadge({ status, title }: { status: PerformanceOutputStatus; title?: string }) {
  return <span className={`losses-status is-${status}`} title={title}>{STATUS_LABEL[status]}</span>;
}

/** Each output's status with its reason in words, under the card that shows it (public issue 143). */
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
