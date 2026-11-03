/**
 * Whether each 0.5.0 output is qualified or experimental, and why (public
 * issue 143): qualified outputs pass a benchmark gate against a reference,
 * experimental outputs can have limited reference coverage that does not
 * qualify their full scope.
 *
 * Records carry their own status (backend/models/performance.py). These
 * reasons mirror the backend's for records stored before they carried one,
 * and for the Solve page before a run exists; tests/test_output_status.py
 * checks they match.
 */

import type { PerformanceOutputStatus } from './performance';

export const DQ_FLUX_LINKAGE_STATUS_REASON = 'Reference checks pass at 12 registered SPM and flat-IPM points. '
  + 'The general d/q output remains experimental, including inductances, maps and unmeasured operating points.';
export const PHASE_RESISTANCE_STATUS_REASON = 'Passes the phase-resistance gate of benchmark protocol 1.6.0: within 1% of independent hand calculations '
  + '(half-circle end turns, IEC conductor data) for a concentrated and a distributed winding. '
  + 'Not compared with a measured winding.';
export const PHASE_RESISTANCE_UNRECORDED_STATUS_REASON = 'Recorded without a status, before the phase-resistance gate; '
  + 'solve the design again to see whether the gate covers it.';
export const MAGNET_TEMPERATURE_STATUS_REASON = 'Br and HcJ use cited reversible coefficients. Reference checks pass for four declared-Br N42 cases at 60 C and 100 C; '
  + 'general temperature behavior and material coefficients remain experimental.';

export const STATUS_LABEL: Record<PerformanceOutputStatus, string> = {
  qualified: 'Qualified',
  experimental: 'Experimental',
  unavailable: 'Unavailable',
};

export interface OutputStatus {
  status: PerformanceOutputStatus;
  reason: string;
}

/** One output's status, named for a card's status list. */
export interface NamedOutputStatus extends OutputStatus {
  key: string;
  label: string;
}

/**
 * A record's status and reason. A record stored before it carried one was
 * experimental, for the fallback reason: the one the current records give, or
 * for the phase resistance, that the record predates its gate.
 */
export function recordStatus(
  record: { status?: PerformanceOutputStatus | null; status_reason?: string | null } | null | undefined,
  fallbackReason: string,
): OutputStatus {
  if (!record?.status) return { status: 'experimental', reason: record?.status_reason || fallbackReason };
  return { status: record.status, reason: record.status_reason ?? '' };
}
