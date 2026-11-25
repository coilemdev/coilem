import type { MotorConfig, SolveResult } from './model';
import { ThermalPanel } from './ThermalPanel';

/**
 * Thermal estimates for a solved run, as their own Results tab.
 *
 * Thermal starts from the losses of the solved run, so a run solved without
 * them is told how to get them instead of being offered buttons that fail.
 */
export function ThermalResultsTab({ config, result, designName }: { config: MotorConfig; result: SolveResult; designName: string | null }) {
  if (!result.summary.iron_loss) {
    return (
      <section className="thermal-panel" aria-label="Thermal setup">
        <h3>Steady-state thermal estimates</h3>
        <p>Thermal estimates use this run&apos;s losses, and this run was solved without them. Turn on <strong>Losses &amp; efficiency</strong> under Solve → Analysis, then solve again.</p>
      </section>
    );
  }
  return <ThermalPanel key={JSON.stringify([config, result.summary.solve_time_s])} config={config} result={result} designName={designName} />;
}
