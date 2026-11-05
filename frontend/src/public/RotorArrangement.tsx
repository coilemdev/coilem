export function RotorArrangement({ value, disabled = false, onInrunner, onOutrunner }: {
  value: 'inrunner' | 'outrunner';
  disabled?: boolean;
  onInrunner?: () => void;
  onOutrunner?: () => void;
}) {
  return <div className="param-section param-primary-section public-rotor-arrangement">
    <div className="param-section-label">Rotor arrangement</div>
    <div className="topology-cards" role="group" aria-label="Rotor arrangement">
      {(['inrunner', 'outrunner'] as const).map((choice) => <button key={choice} type="button"
        className={`topo-card${value === choice ? ' active' : ''}`} aria-pressed={value === choice}
        disabled={disabled || (choice !== value && !(choice === 'inrunner' ? onInrunner : onOutrunner))}
        title={choice === 'outrunner' && !onOutrunner && value !== 'outrunner' ? 'Available in the local outrunner experiment' : undefined}
        onClick={choice === 'inrunner' ? onInrunner : onOutrunner}>
        <span className="topo-icon" aria-hidden="true">{choice === 'inrunner' ? '◉' : '◎'}</span>
        <span className="topo-text"><span className="topo-name">{choice === 'inrunner' ? 'Inrunner' : 'Outrunner'}</span>
          <span className="topo-sub">{choice === 'inrunner' ? 'Rotor inside stator' : 'Rotor outside stator'}</span></span>
      </button>)}
    </div>
  </div>;
}
