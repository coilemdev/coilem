import type { RotorLayout } from './model';

/** Inrunner (rotor inside the stator) or outrunner (rotor outside), above the magnet topology. */
export function RotorArrangement({ value, disabled = false, onChange }: {
  value: RotorLayout;
  disabled?: boolean;
  onChange: (layout: RotorLayout) => void;
}) {
  return <div className="param-section param-primary-section public-rotor-arrangement">
    <div className="param-section-label">Rotor arrangement</div>
    <div className="topology-cards" role="group" aria-label="Rotor arrangement">
      {(['inner', 'outer'] as const).map((layout) => <button key={layout} type="button"
        className={`topo-card${value === layout ? ' active' : ''}`} aria-pressed={value === layout}
        disabled={disabled} onClick={() => { if (layout !== value) onChange(layout); }}>
        <span className="topo-icon" aria-hidden="true">{layout === 'inner' ? '◉' : '◎'}</span>
        <span className="topo-text"><span className="topo-name">{layout === 'inner' ? 'Inrunner' : 'Outrunner'}</span>
          <span className="topo-sub">{layout === 'inner' ? 'Rotor inside stator' : 'Rotor outside stator'}</span></span>
      </button>)}
    </div>
  </div>;
}
