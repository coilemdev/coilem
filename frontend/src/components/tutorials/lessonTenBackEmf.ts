export const BEMF_LAB_BASELINE = { dcBusV: 48, keVPerKrpm: 5.6, rpm: 4200, reservePct: 15 } as const;
export const BEMF_ANGLE_CHECKPOINTS = [0, 90, 180] as const;
export const BEMF_RECOVERY_RPM = 6000;

export interface BackEmfInputs {
  dcBusV: number;
  keVPerKrpm: number;
  rpm: number;
  reservePct: number;
}

export function calculateBackEmfState(inputs: BackEmfInputs) {
  // This analytic lesson assumes ideal linear SVPWM and sinusoidal BEMF.
  // Ke and both limits use line-line RMS volts; phase plots use phase peak.
  const inverterLineLineRmsV = inputs.dcBusV * Math.SQRT1_2;
  const reservedLineLineRmsV = inverterLineLineRmsV * (1 - inputs.reservePct / 100);
  const bemfV = inputs.keVPerKrpm * inputs.rpm / 1000;
  const headroomV = reservedLineLineRmsV - bemfV;
  const status = bemfV > inverterLineLineRmsV + 1e-9
    ? 'inverter-exceeded'
    : headroomV <= 1e-9
      ? 'reserve-exhausted'
      : headroomV / reservedLineLineRmsV < 0.15 ? 'low-headroom' : 'headroom-ok';
  return {
    inverterLineLineRmsV, reservedLineLineRmsV, bemfV, headroomV, status,
    phasePeakV: bemfV * Math.sqrt(2 / 3),
    reservedPhasePeakV: reservedLineLineRmsV * Math.sqrt(2 / 3),
    voltagePhasePeakV: inverterLineLineRmsV * Math.sqrt(2 / 3),
    baseSpeedRpm: reservedLineLineRmsV / inputs.keVPerKrpm * 1000,
    inverterLimitRpm: inverterLineLineRmsV / inputs.keVPerKrpm * 1000,
  };
}

export function backEmfPhaseVoltage(angleDeg: number, shiftDeg: number, phasePeakV: number) {
  return phasePeakV * Math.sin((angleDeg + shiftDeg) * Math.PI / 180);
}

export interface BackEmfLabProgress {
  inspectedAngles: number[];
  reserveCrossed: boolean;
  recovered: boolean;
}

export const createBackEmfLabProgress = (): BackEmfLabProgress => ({
  inspectedAngles: [], reserveCrossed: false, recovered: false,
});

export function backEmfAnglesInspected(progress: BackEmfLabProgress) {
  return BEMF_ANGLE_CHECKPOINTS.every((angle) => progress.inspectedAngles.includes(angle));
}

export function backEmfLabComplete(progress: BackEmfLabProgress) {
  return backEmfAnglesInspected(progress) && progress.reserveCrossed && progress.recovered;
}

type BackEmfLabAction =
  | { type: 'angle'; angleDeg: number; source: 'user' | 'playback' }
  | { type: 'speed'; inputs: BackEmfInputs }
  | { type: 'match'; inputs: BackEmfInputs }
  | { type: 'reset' };

export function backEmfLabReducer(progress: BackEmfLabProgress, action: BackEmfLabAction): BackEmfLabProgress {
  if (action.type === 'reset') return createBackEmfLabProgress();
  if (action.type === 'angle') {
    if (action.source !== 'user') return progress;
    const normalized = ((action.angleDeg % 360) + 360) % 360;
    const checkpoint = BEMF_ANGLE_CHECKPOINTS.find((angle) => (
      Math.min(Math.abs(normalized - angle), 360 - Math.abs(normalized - angle)) <= 2
    ));
    if (checkpoint === undefined || progress.inspectedAngles.includes(checkpoint)) return progress;
    return { ...progress, inspectedAngles: [...progress.inspectedAngles, checkpoint] };
  }
  if (!backEmfAnglesInspected(progress)) return progress;
  const { inputs } = action;
  if (!Object.values(inputs).every(Number.isFinite)) return progress;
  const model = calculateBackEmfState(inputs);
  if (action.type === 'speed' && inputs.dcBusV === BEMF_LAB_BASELINE.dcBusV
    && inputs.keVPerKrpm === BEMF_LAB_BASELINE.keVPerKrpm && inputs.reservePct === BEMF_LAB_BASELINE.reservePct
    && inputs.rpm > BEMF_LAB_BASELINE.rpm && model.headroomV <= 1e-9) {
    return progress.reserveCrossed ? progress : { ...progress, reserveCrossed: true };
  }
  if (action.type === 'match' && progress.reserveCrossed && inputs.rpm === BEMF_RECOVERY_RPM
    && inputs.reservePct === BEMF_LAB_BASELINE.reservePct && model.headroomV > 1e-9
    && (inputs.dcBusV !== BEMF_LAB_BASELINE.dcBusV || inputs.keVPerKrpm !== BEMF_LAB_BASELINE.keVPerKrpm)) {
    return progress.recovered ? progress : { ...progress, recovered: true };
  }
  return progress;
}
