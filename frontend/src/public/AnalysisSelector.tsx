import { useId } from 'react';
import { coggingPlanNote } from './coggingView';
import type { AnalysisKey } from './analysisOptions';
import type { MotorConfig, PublicSolverId } from './model';
import { InfoTip } from './Popover';
import { StatusBadge } from './OutputStatusBadge';
import { COGGING_TORQUE_STATUS_REASON, FLUX_LINKAGE_MAP_STATUS_REASON } from './outputStatus';
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
  const rows: Array<{ key: AnalysisKey; label: string; hint: string; unavailable?: boolean; experimentalReason?: string }> = [
    { key: 'torque_sweep', label: 'Torque', hint: 'Loaded torque waveform, mean torque and ripple.' },
    { key: 'back_emf', label: 'Back EMF', hint: 'No-current voltage waveform at the rated speed.' },
    { key: 'cogging_torque', label: 'Cogging torque', hint: 'No-current torque over one cogging period.', unavailable: elmer,
      experimentalReason: COGGING_TORQUE_STATUS_REASON },
    { key: 'losses_efficiency', label: 'Losses & efficiency', hint: 'Estimated copper and iron losses, and efficiency. Includes the loaded fields needed for losses.', unavailable: elmer,
      experimentalReason: 'Includes experimental iron-loss and efficiency estimates. Copper-loss qualification is reported separately in Results.' },
    { key: 'torque_speed_envelope', label: 'Torque–speed map', hint: 'Torque, power and efficiency across speeds and loads.', unavailable: elmer,
      experimentalReason: FLUX_LINKAGE_MAP_STATUS_REASON },
  ];
  return (
    <div className="public-analysis-options" role="group" aria-label="Analyses to run">
      {rows.map((row) => (
        <div className="public-analysis-option" key={row.key}>
          <div className="public-analysis-heading">
            <label className="public-check-row">
              <input type="checkbox" checked={!row.unavailable && options[row.key]} disabled={busy || row.unavailable}
                aria-describedby={`${id}-${row.key}`} onChange={(event) => onChange(row.key, event.target.checked)} />
              <span>{row.label}</span>
            </label>
            {row.experimentalReason && <StatusBadge status="experimental" title={row.experimentalReason} />}
            <InfoTip label={`${row.label} analysis help`} align="end">
              <div id={`${id}-${row.key}`} className="public-analysis-help">
                <p>{row.key === 'cogging_torque' && !elmer
                  ? coggingPlanNote(config.stator.slot_count, config.rotor.pole_count, coggingPositions, config.solve_params.corner_refinement)
                  : row.hint}</p>
                {row.unavailable && <p className="popover-note">Available with Magneto2D.</p>}
                {row.experimentalReason && (row.key !== 'cogging_torque' || elmer) && <p className="popover-note">{row.experimentalReason}</p>}
              </div>
            </InfoTip>
          </div>
          {row.key === 'torque_speed_envelope' && !elmer && options.torque_speed_envelope && (
            <TorqueSpeedSettings config={config} busy={busy} onChange={onTorqueSpeedChange} />
          )}
        </div>
      ))}
    </div>
  );
}
