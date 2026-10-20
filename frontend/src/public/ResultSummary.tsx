import { useId, type ReactNode } from 'react';
import { MotorConstants } from './MotorConstants';
import { LossesCard } from './LossesCard';
import { DqCard } from './DqCard';
import type { MaterialCatalog, MotorConfig, SolveResult } from './model';
import {
  electricalFrequencyHz,
  electromagneticPower,
  formatFrequencyHz,
  loadingScaleMaxT,
  saturationKneeRangeT,
  sharedSparklinePaths,
  sparklinePath,
  torqueRange,
} from './resultMetrics';

const TIMING_HELP = 'Solver time is the wall-clock time for meshing, solving and building the result. '
  + 'Total elapsed also covers playback images and saving, measured in the browser through receipt of the saved result.';
const SPARKLINE_WIDTH = 132;
const SPARKLINE_HEIGHT = 36;
// The Back EMF value is smaller than the torque hero's, so its sparkline is
// shorter and keeps the three headline values on one line.
const EMF_SPARKLINE_HEIGHT = 26;

function fixed(value: number | null | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

interface ResultSummaryProps {
  result: SolveResult;
  config: MotorConfig;
  /** The catalog with the project's custom steels, for the stator steel's knee. */
  materials: MaterialCatalog;
  sixStep: boolean;
  completeLoadedCycle: boolean;
  thdLabel: string;
  /** Every run setting, label then value, shown when Run settings is expanded. */
  settings: Array<{ label: string; value: string }>;
  /** The model assumptions note, shown under the settings when expanded. */
  assumptions: ReactNode;
}

function LoadingBar({ label, valueT, scaleMaxT, knee }: { label: string; valueT: number; scaleMaxT: number; knee: [number, number] | null }) {
  const share = (value: number) => `${(Math.min(Math.max(value, 0), scaleMaxT) / scaleMaxT) * 100}%`;
  return (
    <div className="public-loading-row">
      <div><span>{label}</span><strong>{fixed(valueT)} <small>T</small></strong></div>
      <div className="public-loading-track" role="img" aria-label={`${label} ${fixed(valueT)} T on a 0 to ${scaleMaxT} T scale`}>
        {knee && <span className="public-loading-knee" style={{ left: share(knee[0]), width: `calc(${share(knee[1])} - ${share(knee[0])})` }} />}
        <span className="public-loading-fill" style={{ width: share(valueT) }} />
      </div>
    </div>
  );
}

/**
 * The Results summary (#99 part B): the run settings and model assumptions as
 * one collapsed line (#110), the headline numbers with their conventions, motor constants beside
 * magnetic loading, and the run timings demoted to one footer line.
 */
export function ResultSummary({
  result,
  config,
  materials,
  sixStep,
  completeLoadedCycle,
  thdLabel,
  settings,
  assumptions,
}: ResultSummaryProps) {
  const loadingHeadingId = useId();
  const assumptionsHeadingId = useId();
  const { summary, solve_metadata: metadata } = result;
  const rpm = config.solve_params.rated_speed_rpm;
  const preview = sixStep && !completeLoadedCycle ? ' · preview only' : '';
  const range = torqueRange(result.torque_waveform.torque_Nm);
  const sparkline = sparklinePath(result.torque_waveform.torque_Nm, SPARKLINE_WIDTH, SPARKLINE_HEIGHT);
  // Phases A, B and C on one scale, in the Back EMF chart's colours.
  const emfSparklines = sharedSparklinePaths(
    [result.back_emf_waveform.phase_a_V, result.back_emf_waveform.phase_b_V, result.back_emf_waveform.phase_c_V],
    SPARKLINE_WIDTH,
    EMF_SPARKLINE_HEIGHT,
  );
  const power = electromagneticPower(summary.avg_torque_Nm, rpm);
  const scaleMaxT = loadingScaleMaxT([summary.peak_flux_density_teeth_T, summary.peak_flux_density_yoke_T]);
  const knee = saturationKneeRangeT(materials, config.materials.stator_steel);
  const thd = summary.back_emf_thd_pct;
  const chips = [
    sixStep
      ? `${fixed(config.solve_params.current_amplitude_A)} A plateau`
      : `${fixed(config.solve_params.current_amplitude_A)} A ${config.solve_params.current_amplitude_convention}`,
    `${rpm.toLocaleString()} rpm · ${formatFrequencyHz(electricalFrequencyHz(rpm, config.rotor.pole_count))} Hz`,
    sixStep
      ? `${fixed(metadata.commutation_advance_deg ?? config.solve_params.commutation_advance_deg, 0)}° advance`
      : `${fixed(config.solve_params.current_angle_deg, 0)}° current angle`,
    sixStep ? 'Ideal six-step (120°)' : 'Sinusoidal',
    `${metadata.rotor_positions} positions · ${metadata.mesh_density || 'native'} mesh`,
  ];
  // Solver, torque method and positions are in Run settings, so the footer
  // keeps only the timings.
  const timings = [
    `Solver ${fixed(summary.solve_time_s, 1)} s`,
    ...(result.workflow_elapsed_s != null ? [`total elapsed ${fixed(result.workflow_elapsed_s, 1)} s`] : []),
  ];

  return (
    <div className="public-result-summary">
      <details className="public-run-settings">
        <summary>
          <span className="public-run-settings-label">Run settings</span>
          <ul className="public-operating-point" aria-label="Operating point">
            {chips.map((chip) => <li key={chip}>{chip}</li>)}
          </ul>
          <span className="public-run-settings-toggle" aria-hidden="true">Settings &amp; assumptions</span>
        </summary>
        <dl className="public-report-provenance">
          {settings.map(({ label, value }) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
        <section className="public-run-settings-assumptions" role="note" aria-labelledby={assumptionsHeadingId}>
          <h4 id={assumptionsHeadingId}>Model assumptions</h4>
          <div className="public-report-assumptions-body">{assumptions}</div>
        </section>
      </details>
      <div className="public-result-headline">
        <article className="public-result-hero">
          <span>Average torque{preview}</span>
          <div>
            <strong>{fixed(summary.avg_torque_Nm)} <small>N·m</small></strong>
            {sparkline && (
              <svg viewBox={`0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}`} width={SPARKLINE_WIDTH} height={SPARKLINE_HEIGHT} aria-hidden="true">
                <path d={sparkline} />
              </svg>
            )}
          </div>
          <p>
            Ripple {fixed(summary.torque_ripple_pct, 1)}%{preview}
            {range ? ` · ${fixed(range.min)} – ${fixed(range.max)} N·m` : ''}
          </p>
        </article>
        <article className="public-result-emf">
          <span>Back EMF</span>
          <div>
            <strong>{fixed(summary.back_emf_fundamental_V)} <small>V</small></strong>
            {emfSparklines.some(Boolean) && (
              <svg viewBox={`0 0 ${SPARKLINE_WIDTH} ${EMF_SPARKLINE_HEIGHT}`} width={SPARKLINE_WIDTH} height={EMF_SPARKLINE_HEIGHT} aria-hidden="true">
                {emfSparklines.map((path, index) => path && <path key={index} className={`phase-${'abc'[index]}`} d={path} />)}
              </svg>
            )}
          </div>
          <p>Fundamental, rms line-to-neutral at {rpm.toLocaleString()} rpm</p>
        </article>
        <article>
          <span>Electromagnetic power{preview}</span>
          <strong>{power ? power.text : '—'} <small>{power?.unit ?? ''}</small></strong>
          <p>Torque × speed, before losses</p>
        </article>
      </div>
      <div className="public-result-detail">
        <MotorConstants summary={summary} variant="report" />
        <DqCard dq={summary.dq_flux_linkage} variant="report" />
        <LossesCard
          loss={summary.loss_breakdown}
          iron={summary.iron_loss}
          density={result.iron_loss_density}
          plot={result.field_line_plot}
          variant="report"
        />
        <section className="public-magnetic-loading" aria-labelledby={loadingHeadingId}>
          <h3 id={loadingHeadingId}>Magnetic loading</h3>
          <LoadingBar label="Peak tooth B" valueT={summary.peak_flux_density_teeth_T} scaleMaxT={scaleMaxT} knee={knee} />
          <LoadingBar label="Peak yoke B" valueT={summary.peak_flux_density_yoke_T} scaleMaxT={scaleMaxT} knee={knee} />
          <p>
            Scale 0–{scaleMaxT} T.
            {knee ? ` Shaded: the stator steel's saturation knee, ${knee[0]}–${knee[1]} T.` : ' This steel declares no saturation knee.'}
          </p>
          <p>{thd != null && Number.isFinite(thd) ? `${thdLabel} ${fixed(thd, 1)}%` : 'Back-EMF THD: not computed for this run'}</p>
        </section>
      </div>
      <p className="public-result-timings" title={TIMING_HELP}>{timings.join(' · ')}</p>
    </div>
  );
}
