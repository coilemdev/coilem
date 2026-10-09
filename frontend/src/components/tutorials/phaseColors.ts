/**
 * Phase identity + waveform colours shared by the tutorial lessons and the
 * private workspace.
 *
 * `BackEmfPhaseId` used to be declared in utils/backEmfFluxLinkage.ts and
 * `BACK_EMF_PHASE_COLORS` in live-solve/constants.ts. Both now live here (one
 * declaration each) and those modules re-export them, so existing consumers
 * are unchanged.
 */
export type BackEmfPhaseId = 'A' | 'B' | 'C';

export const BACK_EMF_PHASE_COLORS: Record<BackEmfPhaseId, string> = {
  A: '#f0a030',
  B: '#34d399',
  C: '#a78bfa',
};
