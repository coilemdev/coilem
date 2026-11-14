import { useEffect, useId, useState } from 'react';
import type { MotorConfig, PublicSolverId } from './model';
import { applyProfile, captureProfile, profileCompatible, profileMatches, saveProfile,
  type SolveProfile, type SolveProfileDocument } from './solveProfiles';

export function RunSetupControl({ config, solver, document, builtins, disabled, onChange, onApply }: {
  config: MotorConfig; solver: PublicSolverId; document: SolveProfileDocument; builtins: SolveProfile[];
  disabled: boolean; onChange: (next: SolveProfileDocument) => void;
  onApply: (config: MotorConfig, solver?: PublicSolverId) => boolean;
}) {
  const nameId = useId(), numericalId = useId();
  const [editing, setEditing] = useState<'new' | 'rename' | null>(null);
  const [name, setName] = useState('');
  const [includeNumerics, setIncludeNumerics] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const all = [...builtins, ...document.profiles];
  const active = all.find(p => p.id === document.activeId);
  const unchanged = Boolean(active && active.version === document.activeVersion && profileMatches(active, config, solver));
  useEffect(() => { setEditing(null); setDeleting(null); setError(null); }, [document.scope]);
  const change = (work: () => void) => {
    try { work(); setError(null); } catch (e) { setError(e instanceof Error ? e.message : 'The setup could not be saved.'); }
  };
  const beginSave = () => {
    setEditing('new'); setName(active ? `${active.name} copy` : '');
    setIncludeNumerics(Boolean(active?.includesNumerics)); setDeleting(null); setError(null);
  };
  const select = (id: string) => change(() => {
    setEditing(null); setDeleting(null);
    if (!id) { onChange({ ...document, activeId: null, activeVersion: null }); return; }
    const profile = all.find(p => p.id === id);
    if (!profile) throw new Error('This setup is no longer available.');
    const next = applyProfile(config, profile);
    if (onApply(next, profile.includesNumerics ? profile.solver : undefined)) {
      onChange({ ...document, activeId: id, activeVersion: profile.version });
    }
  });
  return <section className="public-run-setups" aria-label="Saved run setups">
    <label>Run setup<select aria-label="Run setup" value={active?.id ?? ''} disabled={disabled}
      onChange={e => select(e.target.value)}>
      <option value="">Custom</option>
      {builtins.some(p => profileCompatible(p, config)) && <optgroup label="Published reference setups">
        {builtins.filter(p => profileCompatible(p, config)).map(p => <option key={p.id} value={p.id}>{p.name}{p.id === active?.id && !unchanged ? ' (Modified)' : ''}</option>)}
      </optgroup>}
      {document.profiles.length > 0 && <optgroup label="Your setups">
        {document.profiles.map(p => <option key={p.id} value={p.id} disabled={!profileCompatible(p, config)}>
          {p.name}{!profileCompatible(p, config) ? ' (different model)' : p.id === active?.id && !unchanged ? ' (Modified)' : ''}
        </option>)}
      </optgroup>}
    </select></label>
    <p className="public-design-notice" aria-live="polite">
      {active ? !unchanged ? `Modified from ${active.name}. The next run uses the values shown below.`
        : active.includesNumerics ? 'Includes operating conditions, outputs, accuracy and solver settings.'
        : 'Includes operating conditions and outputs. Accuracy and solver settings stay separately selectable.'
        : 'Save an operating point and its requested outputs for this design.'}
    </p>
    <div className="public-run-setup-actions">
      <button type="button" disabled={disabled} onClick={beginSave}>{active?.builtin ? 'Save a copy…' : 'Save setup…'}</button>
      {active && !active.builtin && <>
        <button type="button" disabled={disabled || !profileCompatible(active, config)} onClick={() => change(() => {
          onChange(saveProfile(document, captureProfile(config, active.name, active.includesNumerics, solver, active.id, active.version + 1)));
          setEditing(null);
        })}>Update setup</button>
        <button type="button" disabled={disabled} onClick={() => { setEditing('rename'); setName(active.name); setDeleting(null); }}>Rename setup</button>
        <button type="button" disabled={disabled} onClick={() => { setDeleting(active.id); setEditing(null); }}>Delete setup</button>
      </>}
    </div>
    {editing && <form onSubmit={e => { e.preventDefault(); change(() => {
      const profile = editing === 'rename' && active && !active.builtin
        ? { ...active, name: name.trim(), version: active.version + 1 }
        : captureProfile(config, name, includeNumerics, solver);
      if (!profile.name || profile.name.length > 100) throw new Error('Give the setup a name of 1–100 characters.');
      onChange(saveProfile(document, profile)); setEditing(null);
    }); }}>
      <label htmlFor={nameId}>Setup name</label><input id={nameId} value={name} maxLength={100} disabled={disabled}
        onChange={e => setName(e.target.value)} autoFocus />
      {editing === 'new' && <label className="public-run-setup-checkbox" htmlFor={numericalId}>
        <input id={numericalId} type="checkbox" checked={includeNumerics} disabled={disabled}
          onChange={e => setIncludeNumerics(e.target.checked)} />Include accuracy and solver settings
      </label>}
      <div className="public-run-setup-actions"><button type="submit" disabled={disabled}>{editing === 'rename' ? 'Save name' : 'Save setup'}</button>
        <button type="button" onClick={() => { setEditing(null); setError(null); }}>Cancel</button></div>
    </form>}
    {deleting && <div role="group" aria-label="Confirm setup deletion">
      <p>Delete “{all.find(p => p.id === deleting)?.name}”?</p>
      <button type="button" disabled={disabled} onClick={() => {
        onChange({ ...document, profiles: document.profiles.filter(p => p.id !== deleting),
          ...(document.activeId === deleting ? { activeId: null, activeVersion: null } : {}) }); setDeleting(null);
      }}>Confirm delete setup</button><button type="button" onClick={() => setDeleting(null)}>Keep setup</button>
    </div>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
