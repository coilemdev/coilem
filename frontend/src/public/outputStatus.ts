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

export const DQ_FLUX_LINKAGE_STATUS_REASON = 'Outside the loaded d/q gates of benchmark protocol 1.6.0, which cover qualified inner-rotor SPM and flat-buried IPM designs '
  + 'with a single-layer concentrated winding under sinusoidal current, at current angles from 0 to 60 degrees.';
export const DQ_INDUCTANCE_STATUS_REASON = 'The d/q gates bound each flux linkage within 3% of its magnitude, which can leave the apparent Ld and Lq, '
  + 'and the saliency and characteristic current from them, tens of percent uncertain.';
export const FLUX_LINKAGE_MAP_STATUS_REASON = "The d/q gates cover 12 operating points, not a map's full range of currents and angles, "
  + 'and do not bound the inductances.';
export const PHASE_RESISTANCE_STATUS_REASON = 'Passes the phase-resistance gate of benchmark protocol 1.6.0: within 1% of independent hand calculations '
  + '(half-circle end turns, IEC conductor data) for a concentrated and a distributed winding. '
  + 'Not compared with a measured winding.';
export const PHASE_RESISTANCE_UNRECORDED_STATUS_REASON = 'Recorded without a status, before the phase-resistance gate; '
  + 'solve the design again to see whether the gate covers it.';
export const MAGNET_TEMPERATURE_STATUS_REASON = "Br and HcJ derated linearly with the grade's cited reversible coefficients; the temperature gates of "
  + 'benchmark protocol 1.6.0 cover qualified inner-rotor designs from 20 to 100 deg C only.';
export const MAGNET_TEMPERATURE_QUALIFIED_REASON = "Br and HcJ derated linearly with the grade's cited reversible coefficients; passes the temperature gates of "
  + 'benchmark protocol 1.6.0 (back EMF and torque at the derated Br, N42 at 60 and 100 deg C on two qualified designs). '
  + 'The coefficients are catalogue values, and irreversible demagnetisation is not modelled.';
export const COGGING_TORQUE_STATUS_REASON = 'The cogging gates of benchmark protocol 1.10.0 (Phase E) cover qualified inner-rotor designs only, with very-fine mesh '
  + 'required for distributed windings. The sweep uses per-position '
  + 'meshes with slot-pitch reuse, without a sliding band, so mesh noise sets a floor under small cogging values.';
export const COGGING_TORQUE_QUALIFIED_REASON = 'Passes the cogging gates of benchmark protocol 1.10.0 (Phase E: 12 cogging cases on SPM and flat-buried IPM rotors). The sweep '
  + 'uses per-position meshes with slot-pitch reuse, without a sliding band, so mesh noise sets a floor under small cogging values.';

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
