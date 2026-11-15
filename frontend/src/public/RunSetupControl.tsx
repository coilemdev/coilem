import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { MotorConfig, PublicSolverId } from './model';
import { InfoTip } from './Popover';
import { RunSetupMenu, type RunSetupOption } from './RunSetupMenu';
import { applyProfile, captureProfile, profileCompatible, profileMatches, saveProfile,
  type SolveProfile, type SolveProfileDocument } from './solveProfiles';

function SetupIcon({ kind }: { kind: 'save' | 'delete' | 'cancel' }) {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    {kind === 'save' ? <><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2Z" /><path d="M7 3v6h10V3M7 21v-8h10v8" /></>
      : kind === 'delete' ? <><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7" /></>
        : <path d="m6 6 12 12M6 18 18 6" />}
  </svg>;
}

export function RunSetupControl({ config, solver, document, builtins, disabled, onChange, onApply }: {
  config: MotorConfig; solver: PublicSolverId; document: SolveProfileDocument; builtins: SolveProfile[];
  disabled: boolean; onChange: (next: SolveProfileDocument) => void;
  onApply: (config: MotorConfig, solver?: PublicSolverId) => boolean;
}) {
  const nameId = useId(), numericalId = useId(), hintId = useId();
  const nameInput = useRef<HTMLInputElement>(null);
  const typedName = useRef(false);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const [editing, setEditing] = useState<'new' | 'rename' | null>(null);
  const [name, setName] = useState('');
  const [includeNumerics, setIncludeNumerics] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  // The workspace re-renders on every solve progress update; compare setups only when their inputs change.
  const all = useMemo(() => [...builtins, ...document.profiles], [builtins, document.profiles]);
  const compatibleIds = useMemo(() => new Set(all.filter(p => profileCompatible(p, config)).map(p => p.id)), [all, config]);
  const active = all.find(p => p.id === document.activeId);
  const compatible = Boolean(active && compatibleIds.has(active.id));
  const unchanged = useMemo(() => Boolean(active && active.version === document.activeVersion && profileMatches(active, config, solver)),
    [active, document.activeVersion, config, solver]);
  const nameChanged = editing === 'rename' && Boolean(active && name.trim() !== active.name);
  const saveDisabled = disabled || Boolean(editing !== 'new' && active && unchanged && !nameChanged);
  useEffect(() => { setEditing(null); setDeleting(false); setError(null); setFeedback(null); }, [document.scope]);
  useEffect(() => { setFeedback(null); }, [config, solver]);
  useEffect(() => {
    if (typedName.current) { typedName.current = false; return; }
    if (editing) { nameInput.current?.focus(); nameInput.current?.select(); }
  }, [editing]);
  const change = (work: () => void) => {
    try { work(); setError(null); } catch (e) { setError(e instanceof Error ? e.message : 'The setup could not be saved.'); }
  };
  const validName = () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed.length > 100) throw new Error('Give the setup a name of 1–100 characters.');
    return trimmed;
  };
  const beginNew = () => {
    setEditing('new'); setName(active ? `${active.name} copy` : '');
    setIncludeNumerics(true); setDeleting(false); setError(null); setFeedback(null);
  };
  const beginRename = () => {
    if (disabled || !active || active.builtin) return;
    setEditing('rename'); setName(active.name); setDeleting(false); setError(null); setFeedback(null);
  };
  const cancel = () => { setEditing(null); setDeleting(false); setError(null); setFeedback(null); };
  const finishRename = () => {
    if (editing !== 'rename' || !active || active.builtin) return;
    change(() => {
      const nextName = validName();
      if (nextName !== active.name) {
        onChange(saveProfile(document, { ...active, name: nextName, version: active.version + 1 }));
        setFeedback(`Renamed setup to “${nextName}”.`);
      }
      setEditing(null);
    });
  };
  const save = () => change(() => {
    if (editing === 'new') {
      const profile = captureProfile(config, validName(), includeNumerics, solver);
      onChange(saveProfile(document, profile)); setEditing(null); setFeedback(`Saved new setup “${profile.name}”.`);
      return;
    }
    if (!active || active.builtin || !compatible) { beginNew(); return; }
    const nextName = editing === 'rename' ? validName() : active.name;
    if (unchanged && nextName === active.name) return;
    onChange(saveProfile(document, captureProfile(config, nextName, active.includesNumerics, solver, active.id, active.version + 1)));
    setEditing(null); setFeedback(`Updated setup “${nextName}”.`);
  });
  const select = (id: string, focusName = true) => change(() => {
    setEditing(null); setDeleting(false); setFeedback(null);
    if (!id) { onChange({ ...document, activeId: null, activeVersion: null }); if (focusName) requestAnimationFrame(() => nameInput.current?.focus()); return; }
    const profile = all.find(p => p.id === id);
    if (!profile) throw new Error('This setup is no longer available.');
    const next = applyProfile(config, profile);
    if (onApply(next, profile.includesNumerics ? profile.solver : undefined)) {
      onChange({ ...document, activeId: id, activeVersion: profile.version });
    }
  });
  const hint = editing === 'new' ? 'Enter a name, then Save. Escape or Cancel discards the name.'
    : active?.builtin ? 'Published references are read-only. Change settings, then Save a personal copy. Choose New setup… to copy the current values.'
    : active && !compatible ? 'This setup belongs to a different model. Save creates a copy for this design.'
    : active ? 'Save enables when captured settings change. Double-click the name or press F2 to rename. Choose New setup… to save another setup.'
    : 'Type a name, then Save to keep the current settings.';
  const capturesNumerics = editing === 'new' ? includeNumerics : active?.includesNumerics ?? true;
  const menuOptions: RunSetupOption[] = [
    { value: '', label: 'New setup…' },
    ...builtins.filter(profile => compatibleIds.has(profile.id)).map(profile => ({ value: profile.id,
      label: `${profile.name}${profile.id === active?.id && !unchanged ? ' (Modified)' : ''}`, group: 'Published references' })),
    ...document.profiles.map(profile => ({ value: profile.id, group: 'Your setups', disabled: !compatibleIds.has(profile.id),
      label: `${profile.name}${!compatibleIds.has(profile.id) ? ' (different model)' : profile.id === active?.id && !unchanged ? ' (Modified)' : ''}` })),
  ];
  return <section className="public-run-setups" aria-label="Saved run setups">
    <div className="public-run-setup-heading">
      <label htmlFor={nameId}>Run setup</label>
      <InfoTip label="Run setup help">
        <p>{capturesNumerics ? 'Includes operating conditions, outputs, accuracy and solver settings.'
          : 'Includes operating conditions and outputs. Accuracy and solver settings stay separately selectable.'}</p>
        <p id={hintId}>{hint}</p>
      </InfoTip>
    </div>
    <div className="public-run-setup-toolbar">
      <div className="public-run-setup-picker">
        <input id={nameId} ref={nameInput} aria-label="Setup name" aria-describedby={hintId}
          value={editing ? name : active ? `${active.name}${!unchanged ? ' (Modified)' : ''}` : ''} readOnly={!editing && Boolean(active)} disabled={disabled || deleting}
          maxLength={100} placeholder="Setup name" onDoubleClick={beginRename}
          title={active && !active.builtin ? 'Double-click or press F2 to rename this setup' : !active ? 'Type a name, then Save the current settings' : undefined}
          onChange={e => {
            if (!editing && !active) { typedName.current = true; setEditing('new'); setIncludeNumerics(true); }
            setName(e.target.value); setError(null); setFeedback(null);
          }}
          onKeyDown={e => {
            if (!editing && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { e.preventDefault(); menuTrigger.current?.focus(); menuTrigger.current?.click(); }
            if (e.key === 'F2' && !editing) { e.preventDefault(); if (active) beginRename(); else beginNew(); }
            if (e.key === 'Escape' && editing) { e.preventDefault(); cancel(); }
            if (e.key === 'Enter' && editing) { e.preventDefault(); if (editing === 'rename') finishRename(); else save(); }
          }}
          onBlur={e => {
            // Save commits an edited name and operating settings together.
            if (e.relatedTarget instanceof HTMLElement && e.relatedTarget.hasAttribute('data-setup-save')) return;
            finishRename();
          }} />
        <RunSetupMenu options={menuOptions} value={active?.id ?? ''} disabled={disabled || deleting || editing === 'new'} triggerRef={menuTrigger} onChange={select} />
      </div>
      {deleting && active ? <div className="public-run-setup-actions" role="group" aria-label="Confirm setup deletion">
        <button type="button" aria-label="Cancel" title="Cancel deletion" disabled={disabled} onClick={cancel}><SetupIcon kind="cancel" /></button>
        <button type="button" className="danger" aria-label="Confirm delete setup" title={`Delete “${active.name}”`} disabled={disabled} onClick={() => {
          onChange({ ...document, profiles: document.profiles.filter(p => p.id !== active.id), activeId: null, activeVersion: null });
          setDeleting(false); setFeedback('Setup deleted. The current operating settings are kept.');
        }}><SetupIcon kind="delete" /></button>
      </div> : <div className="public-run-setup-actions">
        <button type="button" className="primary" data-setup-save aria-label="Save" disabled={saveDisabled}
          onMouseDown={e => { if (editing === 'rename') e.preventDefault(); }} onClick={save}
          // The name field leaves a rename open while focus is on Save; leaving Save elsewhere ends it.
          onBlur={e => { if (editing === 'rename' && e.relatedTarget !== nameInput.current) finishRename(); }}
          title={saveDisabled && !disabled ? 'No changes to save'
            : active && !active.builtin && compatible && editing !== 'new' ? 'Update this setup with the current settings'
              : 'Save the current settings as a new setup'}><SetupIcon kind="save" /></button>
        {editing === 'new' ? <button type="button" aria-label="Cancel" title="Cancel new setup" disabled={disabled} onClick={cancel}><SetupIcon kind="cancel" /></button>
          : <button type="button" className="danger" aria-label="Delete" title={active ? `Delete “${active.name}”` : 'Select a saved setup to delete'}
            disabled={disabled || !active || Boolean(active.builtin)}
            onClick={() => { setDeleting(true); setEditing(null); setError(null); setFeedback(null); }}><SetupIcon kind="delete" /></button>}
      </div>}
    </div>
    {deleting && active && <p className="public-run-setup-hint" role="alert">Delete “{active.name}”? Confirm with the trash icon, or cancel.</p>}
    {active && !unchanged && <p className="public-design-notice" aria-live="polite">
      Modified from {active.name}. The next run uses the values shown below.
    </p>}
    {editing === 'new' && <label className="public-run-setup-checkbox" htmlFor={numericalId}>
      <input id={numericalId} type="checkbox" checked={includeNumerics} disabled={disabled}
        onChange={e => setIncludeNumerics(e.target.checked)} />Include accuracy and solver settings
    </label>}
    {(feedback || editing === 'new') && <p className="public-run-setup-hint" role="status">{feedback ?? hint}</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
