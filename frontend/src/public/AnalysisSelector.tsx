import { useId } from 'react';
import { coggingPlanNote } from './coggingView';
import type { AnalysisKey } from './analysisOptions';
import type { MotorConfig, PublicSolverId } from './model';

export function AnalysisOptions({ config, solver, busy, coggingPositions, onChange }: {
  config: MotorConfig;
  solver: PublicSolverId;
  busy: boolean;
  coggingPositions?: number;
  onChange: (key: AnalysisKey, enabled: boolean) => void;
}) {
  const id = useId();
  const options = config.solve_options;
  const elmer = solver === 'elmer';
  const rows: Array<{ key: AnalysisKey; label: string; hint: string; unavailable?: boolean }> = [
    { key: 'torque_sweep', label: 'Torque', hint: 'Loaded torque waveform, mean torque and ripple.' },
    { key: 'back_emf', label: 'Back EMF', hint: 'No-current voltage waveform at the rated speed. Can run on its own.' },
    { key: 'cogging_torque', label: 'Cogging torque', hint: elmer ? 'Available with Magneto2D.' : 'No-current torque over one cogging period.', unavailable: elmer },
    { key: 'losses_efficiency', label: 'Losses & efficiency', hint: elmer ? 'Available with Magneto2D.' : 'Estimated copper and iron losses, and efficiency. Includes the loaded fields needed for losses.', unavailable: elmer },
  ];
  return (
    <div className="public-analysis-options" role="group" aria-label="Analyses to run">
      {rows.map((row) => (
        <div className="public-analysis-option" key={row.key}>
          <label className="public-check-row">
            <input type="checkbox" checked={!row.unavailable && options[row.key]} disabled={busy || row.unavailable}
              aria-describedby={`${id}-${row.key}`} onChange={(event) => onChange(row.key, event.target.checked)} />
            <span>{row.label}</span>
          </label>
          <p id={`${id}-${row.key}`} className="public-analysis-hint">{row.hint}</p>
          {row.key === 'cogging_torque' && !elmer && options.cogging_torque && (
            <p className="public-plan-advisory">{coggingPlanNote(config.stator.slot_count, config.rotor.pole_count, coggingPositions, config.solve_params.corner_refinement)}</p>
          )}
        </div>
      ))}
    </div>
  );
}
