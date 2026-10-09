import React from 'react';
import type { KnowledgeCheckQuestion } from './magneticCircuit';

interface KnowledgeCheckProps {
  questions: KnowledgeCheckQuestion[];
  onPassedChange?: (passed: boolean) => void;
}

export const KnowledgeCheck: React.FC<KnowledgeCheckProps> = ({ questions, onPassedChange }) => {
  const [answers, setAnswers] = React.useState<Record<string, number>>({});

  const passed = questions.length > 0
    && questions.every((question) => answers[question.id] === question.correctIndex);

  React.useEffect(() => {
    onPassedChange?.(passed);
  }, [passed, onPassedChange]);

  return (
    <div className="tutorial-knowledge-check" aria-label="Knowledge check">
      {questions.map((question, questionIndex) => {
        const selected = answers[question.id];
        const answered = selected !== undefined;
        const correct = answered && selected === question.correctIndex;
        return (
          <fieldset key={question.id} className="tutorial-knowledge-question">
            <legend>
              <span className="tutorial-knowledge-number">{questionIndex + 1}</span>
              {question.prompt}
            </legend>
            <div className="tutorial-knowledge-options" role="group">
              {question.options.map((option, optionIndex) => {
                const isSelected = selected === optionIndex;
                const stateClass = isSelected
                  ? (optionIndex === question.correctIndex ? ' is-correct' : ' is-wrong')
                  : '';
                return (
                  <button
                    key={option}
                    type="button"
                    className={`tutorial-knowledge-option${stateClass}`}
                    aria-pressed={isSelected}
                    onClick={() => setAnswers((prev) => ({ ...prev, [question.id]: optionIndex }))}
                  >
                    {option}
                  </button>
                );
              })}
            </div>
            {answered ? (
              <p className={`tutorial-knowledge-feedback${correct ? ' is-correct' : ' is-wrong'}`}>
                {correct ? question.explanation : 'Not quite — try another answer.'}
              </p>
            ) : null}
          </fieldset>
        );
      })}
      <p className={`tutorial-knowledge-result${passed ? ' is-passed' : ''}`}>
        {passed ? 'Knowledge check passed ✓' : `Answer all ${questions.length} to pass the check.`}
      </p>
    </div>
  );
};
