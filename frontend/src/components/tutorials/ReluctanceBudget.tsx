import React from 'react';
import {
  LESSON_TWO_IRON_MU_R,
  LESSON_TWO_IRON_PATH_MM,
  LESSON_TWO_MAGNET_BR_T,
  LESSON_TWO_MAGNET_MU_R,
  computeReluctanceBudget,
  formatPercent,
  formatTesla,
} from './magneticCircuit';

interface ReluctanceBudgetProps {
  airgapMm: number;
  magnetThicknessMm: number;
  /** Peak radial airgap B from the last solved field frame, if one exists. */
  solvedPeakT: number | null;
}

/** Student answers within this relative error of the circuit model count as a match. */
const MATCH_TOLERANCE = 0.05;

const diagnoseMiss = (ratio: number): string => {
  if (ratio > 0.4 && ratio < 0.6) {
    return 'That is about half the model value — did you count both magnets and both airgaps? The loop crosses two of each.';
  }
  if (ratio > 1.7 && ratio < 2.4) {
    return 'That is about double the model value — the MMF source already includes both magnets, so divide by the full path only once.';
  }
  if (ratio < 0.1 || ratio > 10) {
    return 'That is orders of magnitude off — keep every length in mm so the units cancel, and divide magnet thickness by mu_r = 1.05.';
  }
  return 'Check the air-equivalence conversions: magnets 2*h_m/1.05, gaps 2*g, iron 150/2000 — then B_gap = 1.30 x (magnet mm) / (total mm).';
};

// Crash-course Day 1 lab: the student hand-calcs the series-reluctance budget
// of the Lesson-1 motor from the givens below, enters their predicted airgap
// flux, and only then sees the worked model answer and the FEM comparison.
export const ReluctanceBudget: React.FC<ReluctanceBudgetProps> = ({
  airgapMm,
  magnetThicknessMm,
  solvedPeakT,
}) => {
  const budget = computeReluctanceBudget(airgapMm, magnetThicknessMm);
  const [draft, setDraft] = React.useState('');
  const [studentBT, setStudentBT] = React.useState<number | null>(null);
  const [revealed, setRevealed] = React.useState(false);
  const [inputError, setInputError] = React.useState<string | null>(null);

  // A geometry tweak changes the givens, so a previous answer no longer applies.
  React.useEffect(() => {
    setStudentBT(null);
    setRevealed(false);
    setInputError(null);
  }, [airgapMm, magnetThicknessMm]);

  const submit = () => {
    const value = Number(draft);
    if (!Number.isFinite(value) || value <= 0) {
      setInputError('Enter your predicted B_gap in tesla (e.g. 0.95).');
      return;
    }
    setInputError(null);
    setStudentBT(value);
    setRevealed(true);
  };

  const studentErrPct = studentBT !== null
    ? ((studentBT - budget.predictedAirgapBT) / budget.predictedAirgapBT) * 100
    : null;
  const studentMatched = studentErrPct !== null && Math.abs(studentErrPct) <= MATCH_TOLERANCE * 100;

  const modelVsFemPct = solvedPeakT !== null && solvedPeakT > 1e-6
    ? ((budget.predictedAirgapBT - solvedPeakT) / solvedPeakT) * 100
    : null;

  const segments = [
    { id: 'magnets', label: 'Magnets x2', equivMm: budget.magnetEquivMm, fraction: budget.magnetFraction, color: '#f59e0b' },
    { id: 'airgaps', label: 'Airgaps x2', equivMm: budget.airgapEquivMm, fraction: budget.airgapFraction, color: '#22d3ee' },
    { id: 'iron', label: 'Iron path', equivMm: budget.ironEquivMm, fraction: budget.ironFraction, color: '#94a3b8' },
  ];

  const givens = [
    { label: 'Magnet (N42)', value: `B_r = ${LESSON_TWO_MAGNET_BR_T.toFixed(2)} T, mu_r = ${LESSON_TWO_MAGNET_MU_R}` },
    { label: 'Magnet thickness', value: `h_m = ${magnetThicknessMm.toFixed(1)} mm, crossed x2` },
    { label: 'Airgap', value: `g = ${airgapMm.toFixed(2)} mm, crossed x2` },
    { label: 'Iron path', value: `${LESSON_TWO_IRON_PATH_MM} mm at mu_r = ${LESSON_TWO_IRON_MU_R}` },
  ];

  return (
    <div className="tutorial-budget" aria-label="Reluctance budget hand-calc">
      <dl className="tutorial-budget-givens">
        {givens.map((given) => (
          <div key={given.label}>
            <dt>{given.label}</dt>
            <dd>{given.value}</dd>
          </div>
        ))}
      </dl>

      <div className="tutorial-budget-formula">
        <span>Recipe — convert each element to mm of equivalent air, then:</span>
        <div
          className="tutorial-budget-equation"
          role="img"
          aria-label="B gap equals B r times two h m over mu r, divided by two h m over mu r plus two g plus iron path length over iron mu"
        >
          <strong className="tutorial-budget-equation-lead" aria-hidden="true">
            B<sub>gap</sub> = B<sub>r</sub> &times;
          </strong>
          <span className="tutorial-budget-fraction" aria-hidden="true">
            <span>2 h<sub>m</sub> / &mu;<sub>r</sub></span>
            <span>
              2 h<sub>m</sub> / &mu;<sub>r</sub> + 2 g + {'\u2113'}<sub>iron</sub> / &mu;<sub>iron</sub>
            </span>
          </span>
        </div>
      </div>

      <div className="tutorial-budget-entry">
        <label htmlFor="budget-handcalc-input">Your hand-calc B_gap</label>
        <div className="tutorial-budget-entry-row">
          <input
            id="budget-handcalc-input"
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            placeholder="0.00"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submit();
            }}
          />
          <span className="tutorial-budget-unit">T</span>
          <button type="button" className="tutorial-budget-check" onClick={submit}>
            Check
          </button>
          {!revealed ? (
            <button
              type="button"
              className="tutorial-budget-reveal"
              onClick={() => setRevealed(true)}
            >
              Show worked solution
            </button>
          ) : null}
        </div>
        {inputError ? <p className="tutorial-budget-input-error">{inputError}</p> : null}
      </div>

      {revealed ? (
        <>
          {studentBT !== null ? (
            <p className={`tutorial-budget-feedback ${studentMatched ? 'is-match' : 'is-miss'}`}>
              {studentMatched
                ? `${formatTesla(studentBT)} — within ${Math.abs(studentErrPct ?? 0).toFixed(1)}% of the circuit model. Nailed it.`
                : `${formatTesla(studentBT)} is ${Math.abs(studentErrPct ?? 0).toFixed(0)}% ${(studentErrPct ?? 0) > 0 ? 'over' : 'under'} the model. ${diagnoseMiss(studentBT / budget.predictedAirgapBT)}`}
            </p>
          ) : null}

          <div className="tutorial-budget-source">
            <span>Magnet MMF source &middot; 2 &times; H_c &times; h_m</span>
            <strong>{(budget.magnetMmfAt / 1000).toFixed(1)} kA&middot;turns</strong>
          </div>

          <div className="tutorial-budget-bar" role="img" aria-label="Share of the total MMF each circuit element drops">
            {segments.map((segment) => (
              <span
                key={segment.id}
                style={{ width: `${Math.max(segment.fraction * 100, 2)}%`, background: segment.color }}
              />
            ))}
          </div>
          <dl className="tutorial-budget-legend">
            {segments.map((segment) => (
              <div key={segment.id}>
                <i className="tutorial-budget-swatch" style={{ background: segment.color }} aria-hidden="true" />
                <dt>{segment.label}</dt>
                <dd>
                  {formatPercent(segment.fraction)} of MMF &middot; {segment.equivMm.toFixed(2)} mm air-equiv.
                </dd>
              </div>
            ))}
          </dl>

          <div className="tutorial-budget-formula">
            <span>Worked solution</span>
            <strong>
              {`= ${LESSON_TWO_MAGNET_BR_T.toFixed(2)} x ${(2 * magnetThicknessMm / LESSON_TWO_MAGNET_MU_R).toFixed(2)} / (${budget.magnetEquivMm.toFixed(2)} + ${budget.airgapEquivMm.toFixed(2)} + ${budget.ironEquivMm.toFixed(3)}) = ${budget.predictedAirgapBT.toFixed(2)} T`}
            </strong>
          </div>

          <dl className="tutorial-airgap-gauge-stats tutorial-budget-compare">
            <div>
              <dt>Your hand-calc</dt>
              <dd>{studentBT !== null ? formatTesla(studentBT) : '—'}</dd>
            </div>
            <div>
              <dt>Circuit model</dt>
              <dd>{formatTesla(budget.predictedAirgapBT)}</dd>
            </div>
            <div>
              <dt>Solved peak B</dt>
              <dd>{solvedPeakT !== null ? formatTesla(solvedPeakT) : '—'}</dd>
            </div>
            <div>
              <dt>Model vs. FEM</dt>
              <dd className={modelVsFemPct !== null ? (modelVsFemPct >= 0 ? 'is-up' : 'is-down') : ''}>
                {modelVsFemPct !== null ? `${modelVsFemPct >= 0 ? '+' : ''}${modelVsFemPct.toFixed(0)}%` : '—'}
              </dd>
            </div>
          </dl>

          <p className="tutorial-budget-hint">
            {modelVsFemPct === null
              ? 'Run the balanced solve to compare your hand-calc against a solved frame.'
              : 'The 1-D loop overshoots because it ignores fringing at the 74%-embrace magnet edges, inter-pole leakage, and slotting — that gap is the honest error of a circuit model.'}
          </p>
        </>
      ) : (
        <p className="tutorial-budget-hint">
          Grab a calculator: convert all four lengths to mm of equivalent air, then apply the recipe.
          Your answer stays hidden from the worked solution until you check it.
        </p>
      )}
    </div>
  );
};
