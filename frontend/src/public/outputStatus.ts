/**
 * Whether each 0.5.0 output is qualified or experimental, and why (public
 * issue 143): qualified outputs pass a benchmark gate against a reference,
 * experimental ones have none yet.
 *
 * Records carry their own status (backend/models/performance.py). These
 * reasons mirror the backend's for records stored before they carried one,
 * and for the Solve page before a run exists; tests/test_output_status.py
 * checks they match.
 */

import type { PerformanceOutputStatus } from './performance';

export const DQ_FLUX_LINKAGE_STATUS_REASON = 'Not yet compared with a reference solution: the benchmark measures torque and back EMF, '
  + "so the design's qualification does not cover the d/q flux linkage or the inductances from it.";
export const PHASE_RESISTANCE_STATUS_REASON = 'Calculated from the wire, turns and mean turn length (half-circle end turns, IEC conductor data); '
  + 'not yet checked against a hand calculation or a measured winding.';
export const MAGNET_TEMPERATURE_STATUS_REASON = "Br and HcJ derated linearly with the grade's cited reversible coefficients; "
  + 'back EMF and torque at temperature are not yet compared with a reference.';

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
 * experimental, for the reason the current records give.
 */
export function recordStatus(
  record: { status?: PerformanceOutputStatus | null; status_reason?: string | null } | null | undefined,
  fallbackReason: string,
): OutputStatus {
  if (!record?.status) return { status: 'experimental', reason: record?.status_reason || fallbackReason };
  return { status: record.status, reason: record.status_reason ?? '' };
}
