/**
 * The shared shell for the tutorial lessons.
 *
 * Every lesson step uses the motor workspace's three cards: what the student
 * does on the left, the canvas (or the questions) in the middle, measurements
 * and reference on the right. A lesson supplies its own content; the layout,
 * the panel chrome and the canvas dock live here and in lesson-lab.css, so the
 * ten lessons stay consistent and a change to the shell is made once.
 */
import React from 'react';

import './lesson-lab.css';

type Children = { children?: React.ReactNode };

/** The page: three cards on the app canvas. */
export function LessonLab({ className = '', children }: Children & { className?: string }) {
  return <main className={`learning-shell learning-lesson-shell lesson-lab ${className}`.trim()}>{children}</main>;
}

interface LessonLabPanelProps extends Children {
  /** 'do' is the left card (the experiment); 'inspect' is the right card. */
  side: 'do' | 'inspect';
  /** Small uppercase label above the title, e.g. "Experiment · Open air". */
  kicker: string;
  title: React.ReactNode;
  /** One or two sentences under the title. */
  summary?: React.ReactNode;
  /** Accessible name of the panel. */
  label: string;
  /** Pinned to the foot of the card, below the scrolling content. */
  footer?: React.ReactNode;
  /** Briefly ring the card to draw the eye to it. */
  flash?: boolean;
  titleId?: string;
  /**
   * Scroll the card back to its top whenever this value changes, e.g. the
   * number of solved runs, so new measurements are not left out of sight
   * above a student who had scrolled down to the terms.
   */
  scrollTopKey?: string | number;
}

export const LessonLabPanel = React.forwardRef<HTMLElement, LessonLabPanelProps>(function LessonLabPanel(
  { side, kicker, title, summary, label, footer, flash = false, titleId, scrollTopKey, children },
  ref,
) {
  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(() => {
    if (scrollTopKey !== undefined) scrollRef.current?.scrollTo({ top: 0 });
  }, [scrollTopKey]);
  return (
    <aside ref={ref} className={`lesson-lab-panel is-${side}${flash ? ' is-flash' : ''}`} aria-label={label}>
      <div ref={scrollRef} className="lesson-lab-panel-scroll">
        <header className="lesson-lab-panel-header">
          <p className="lesson-lab-kicker">{kicker}</p>
          <h2 id={titleId}>{title}</h2>
          {summary ? <p className="lesson-lab-panel-summary">{summary}</p> : null}
        </header>
        <div className="lesson-lab-panel-body">{children}</div>
      </div>
      {footer}
    </aside>
  );
});

/** The middle card. `plain` drops the canvas background for a page of questions. */
export function LessonLabStage({ className = '', children }: Children & { className?: string }) {
  return <section className={`learning-main-stage lesson-lab-stage ${className}`.trim()}>{children}</section>;
}

/** Canvas above, dock below. */
export function LessonLabCanvas({ className = '', children }: Children & { className?: string }) {
  return <div className={`lesson-lab-canvas ${className}`.trim()}>{children}</div>;
}

/** The part of the canvas card the picture is drawn in. */
export function LessonLabViewport({ label, hint, className = '', children }: Children & {
  /** Chip at the top-left naming what is drawn, like "SPM 8p/12s" on the motor canvas. */
  label?: React.ReactNode;
  /** A short line beside the chip. */
  hint?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`lesson-lab-viewport ${className}`.trim()}>
      {label ? (
        <div className="lesson-lab-viewport-heading">
          <span className="lesson-lab-viewport-label">{label}</span>
          {hint ? <span className="lesson-lab-viewport-hint">{hint}</span> : null}
        </div>
      ) : null}
      {children}
    </div>
  );
}

/** "Step 3 of 5" and the goal of the step. */
export function LessonGoal({ step, total, title, detail }: { step: number; total: number; title: string; detail: string }) {
  return (
    <section className="lesson-lab-goal" aria-label="Current lesson goal">
      <span>{step}/{total}</span>
      <div>
        <p>Step {step} of {total} · Goal</p>
        <strong>{title}</strong>
        <small>{detail}</small>
      </div>
    </section>
  );
}

/** The foot of the left card: one line of guidance, then the next action. */
export function LessonNextStep({ hint, tone, children }: Children & { hint?: React.ReactNode; tone?: 'good' | 'warn' }) {
  return (
    <footer className="lesson-lab-next" aria-label="Next step">
      {hint ? <p className={tone ? `is-${tone}` : undefined} aria-live="polite">{hint}</p> : null}
      {children}
    </footer>
  );
}

/** A quiet text button for the foot of a card ("← All lessons"). */
export function LessonLink({ onClick, children }: Children & { onClick: () => void }) {
  return <button type="button" className="lesson-lab-link" onClick={onClick}>{children}</button>;
}

export interface LessonTerm { term: React.ReactNode; definition: React.ReactNode }

/** The lesson's vocabulary, kept beside whatever is being read or measured. */
export function LessonTerms({ terms, heading = 'Terms' }: { terms: readonly LessonTerm[]; heading?: string }) {
  return (
    <section className="lesson-lab-card lesson-lab-terms" aria-label="Terms used in this lesson">
      <h3>{heading}</h3>
      <dl>
        {terms.map((item, index) => (
          <div key={index}><dt>{item.term}</dt><dd>{item.definition}</dd></div>
        ))}
      </dl>
    </section>
  );
}

/** The steps of the lesson, with the current one marked. */
export function LessonOutline({ steps, currentId }: {
  steps: ReadonlyArray<{ id: string; label: string; detail: string }>;
  currentId: string;
}) {
  return (
    <section className="lesson-lab-card" aria-label="Steps in this lesson">
      <h3>In this lesson</h3>
      <ol className="lesson-lab-outline">
        {steps.map((step) => (
          <li key={step.id} className={step.id === currentId ? 'is-current' : ''}>
            <strong>{step.label}</strong>
            <span>{step.detail}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Numbered answers, one per row. */
export function LessonChoices<Id extends string>({ options, value, onChange, correctId, label }: {
  options: ReadonlyArray<{ id: Id; label: React.ReactNode; detail?: React.ReactNode }>;
  value: Id | null;
  onChange: (id: Id) => void;
  /** Marks the selected answer green when it is this one. */
  correctId?: Id;
  label: string;
}) {
  return (
    <div className="lesson-lab-choices" role="radiogroup" aria-label={label}>
      {options.map((option, index) => {
        const selected = value === option.id;
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={selected}
            className={`${selected ? 'is-selected' : ''}${selected && option.id === correctId ? ' is-correct' : ''}`}
            onClick={() => onChange(option.id)}
          >
            <span>{index + 1}</span>
            <strong>{option.label}{option.detail ? <small>{option.detail}</small> : null}</strong>
          </button>
        );
      })}
    </div>
  );
}

/** One choice at a time, on a shared track (frames, drawing modes). */
export function LessonSegmented<Id extends string>({ options, value, onChange, label, stretch = false }: {
  options: ReadonlyArray<{ id: Id; label: React.ReactNode; disabled?: boolean; title?: string }>;
  value: Id | null;
  onChange: (id: Id) => void;
  label: string;
  /** Fill the width of the card, one equal column per option. */
  stretch?: boolean;
}) {
  return (
    <span className={`lesson-lab-segmented${stretch ? ' is-stretch' : ''}`} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={value === option.id}
          disabled={option.disabled}
          title={option.title}
          onClick={() => onChange(option.id)}
        >
          {option.label}
        </button>
      ))}
    </span>
  );
}

/**
 * The dock under the canvas, laid out like the motor workspace's: view tabs on
 * the left of the title bar and `end` (zoom, a note) on the right, then one
 * row of labelled controls. A view with no layers to switch passes no children
 * and gets the title bar alone.
 */
export function LessonDock<Tab extends string>({ tabs, tab, onTab, end, children }: Children & {
  tabs: ReadonlyArray<{ id: Tab; label: string; disabled?: boolean; title?: string }>;
  tab: Tab;
  onTab: (tab: Tab) => void;
  end?: React.ReactNode;
}) {
  return (
    <div className="lesson-lab-dock" aria-label="View controls">
      <div className="lesson-lab-dock-strip">
        <div className="lesson-lab-dock-tabs" role="group" aria-label="View">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-pressed={tab === item.id}
              disabled={item.disabled}
              title={item.title}
              onClick={() => onTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <span className="lesson-lab-dock-end">{end}</span>
      </div>
      {React.Children.count(children) > 0 ? <div className="lesson-lab-dock-controls">{children}</div> : null}
    </div>
  );
}

/** A labelled group of dock controls ("FIELD", "SHOW"). */
export function LessonDockGroup({ label, children }: Children & { label: string }) {
  return (
    <span className="lesson-lab-dock-group" role="group" aria-label={label}>
      <span className="lesson-lab-dock-group-label" aria-hidden="true">{label}</span>
      {children}
    </span>
  );
}

/** A layer switched on or off on its own. */
export function LessonDockToggle({ pressed, onChange, disabled, title, children }: Children & {
  pressed: boolean;
  onChange: (pressed: boolean) => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      className="lesson-lab-dock-toggle"
      aria-pressed={pressed}
      disabled={disabled}
      title={title}
      onClick={() => onChange(!pressed)}
    >
      {children}
    </button>
  );
}
