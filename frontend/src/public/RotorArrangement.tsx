import { useMotorHoverPreview } from './useMotorHoverPreview';
import type { RotorLayout } from './model';
import { RotorArrangementPreview } from './RotorArrangementPreview';

/** Inrunner (rotor inside the stator) or outrunner (rotor outside), above the magnet topology. */
export function RotorArrangement({ value, disabled = false, onChange }: {
  value: RotorLayout | null;
  disabled?: boolean;
  onChange: (layout: RotorLayout) => void;
}) {
  const hover = useMotorHoverPreview<RotorLayout>(disabled);

  return <div className="param-section param-primary-section public-rotor-arrangement" data-guide="arrangement-selector">
    <div className="param-section-label">Rotor arrangement</div>
    <div ref={hover.groupRef} className="topology-cards" role="group" aria-label="Rotor arrangement">
      {(['inner', 'outer'] as const).map((layout) => <button key={layout} type="button"
        className={`topo-card${value === layout ? ' active' : ''}`} aria-pressed={value === layout}
        {...hover.triggerProps(layout)}
        disabled={disabled} onClick={() => { hover.dismiss(); if (layout !== value) onChange(layout); }}>
        <span className="topo-icon" aria-hidden="true">{value === layout ? '◉' : '○'}</span>
        <span className="topo-text"><span className="topo-name">{layout === 'inner' ? 'Inrunner' : 'Outrunner'}</span>
          <span className="topo-sub">{layout === 'inner' ? 'Rotor inside stator' : 'Rotor outside stator'}</span></span>
      </button>)}
    </div>
    {hover.renderPreview((layout) => <RotorArrangementPreview layout={layout} />)}
  </div>;
}
