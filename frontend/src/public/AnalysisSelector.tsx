import { useId } from 'react';
import { coggingPlanNote } from './coggingView';
import type { AnalysisKey } from './analysisOptions';
import type { MotorConfig, PublicSolverId } from './model';
import { Popover } from './Popover';
import { TorqueSpeedSettings } from './TorqueSpeedSettings';
import type { TorqueSpeedAnalysisSettings } from './performance';

export function AnalysisOptions({ config, solver, busy, coggingPositions, onChange, onTorqueSpeedChange }: {
  config: MotorConfig;
  solver: PublicSolverId;
  busy: boolean;
  coggingPositions?: number;
  onChange: (key: AnalysisKey, enabled: boolean) => void;
  onTorqueSpeedChange: (settings: TorqueSpeedAnalysisSettings) => void;
}) {
  const id = useId();
  const options = config.solve_options;
  const elmer = solver === 'elmer';
  const rows: Array<{ key: AnalysisKey; label: string; hint: string; unavailable?: boolean }> = [
    { key: 'torque_sweep', label: 'Torque', hint: 'Loaded torque waveform, mean torque and ripple.' },
    { key: 'back_emf', label: 'Back EMF', hint: 'No-current voltage waveform at the rated speed. Can run on its own.' },
    { key: 'cogging_torque', label: 'Cogging torque', hint: elmer ? 'Available with Magneto2D.' : 'No-current torque over one cogging period.', unavailable: elmer },
    { key: 'losses_efficiency', label: 'Losses & efficiency', hint: elmer ? 'Available with Magneto2D.' : 'Estimated copper and iron losses, and efficiency. Includes the loaded fields needed for losses.', unavailable: elmer },
    { key: 'torque_speed_envelope', label: 'Torque–speed map', hint: elmer ? 'Available with Magneto2D.' : 'Torque, power and efficiency across speeds and loads. Can run on its own.', unavailable: elmer },
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
          <div id={`${id}-${row.key}`} className="public-analysis-hint">
            {row.key === 'cogging_torque' && !elmer ? (
              <Popover trigger={(props) => <button type="button" className="public-analysis-hint-trigger" {...props}>{row.hint}</button>}>
                {coggingPlanNote(config.stator.slot_count, config.rotor.pole_count, coggingPositions, config.solve_params.corner_refinement)}
              </Popover>
            ) : row.hint}
          </div>
          {row.key === 'torque_speed_envelope' && !elmer && options.torque_speed_envelope && (
            <TorqueSpeedSettings config={config} busy={busy} onChange={onTorqueSpeedChange} />
          )}
        </div>
      ))}
    </div>
  );
}
