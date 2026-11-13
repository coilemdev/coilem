import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { MotorConfig, RotorLayout } from './model';
import type { BuiltParts } from './progressiveDesign';

interface RequiredField { section: string; label: string; required: boolean }
export const entryKey = (section: string, label: string) => `${section}:${label}`;
export interface NewDesignEntry {
  layout: RotorLayout | null;
  topology: MotorConfig['topology'] | null;
  ready: boolean;
  fields: Record<string, boolean>;
  requirements: Record<string, RequiredField>;
  confirm: (section: string, label: string) => void;
  forget: (section: string, labels: string[]) => void;
  register: (section: string, label: string, required: boolean) => void;
  unregister: (section: string, label: string) => void;
  mountSection: (section: string) => () => void;
}
export const NewDesignEntryContext = createContext<NewDesignEntry | null>(null);
/** The guide shares Design's validation and completion gates. */
export const GuidedDesignProgressContext = createContext({ blocked: false, complete: false });
export const DesignSectionContext = createContext<string | null>(null);
export const hasEntry = (entry: NewDesignEntry, section: string, ...labels: string[]) => labels.every((label) => entry.fields[entryKey(section, label)]);
export function entrySectionComplete(entry: NewDesignEntry, section: string): boolean {
  const required = Object.values(entry.requirements).filter((field) => field.section === section && field.required);
  return required.length > 0 && required.every((field) => hasEntry(entry, section, field.label));
}

export function enteredDesignParts(config: MotorConfig, built: BuiltParts, entry: NewDesignEntry): BuiltParts {
  if (!entry.ready) return {};
  const outer = config.rotor_layout === 'outer';
  const stator = Boolean(built.stator && hasEntry(entry, 'stator', 'Outer Diameter', 'Yoke Thickness')
    && (!outer || hasEntry(entry, 'stator', 'Hub Bore (ID)')));
  const slots = Boolean(stator && built.slots && hasEntry(entry, 'stator', 'Slot Count', outer ? 'Hub Bore (ID)' : 'Bore Diameter (ID)'));
  const teeth = Boolean(slots && built.teeth && entrySectionComplete(entry, 'advanced'));
  const rotor = Boolean(slots && built.rotor && hasEntry(entry, 'rotor', 'Rotor OD') && (!outer || hasEntry(entry, 'rotor', 'Magnet Seat')));
  const vPocketReady = config.topology !== 'IPM' || config.rotor.ipm_topology !== 'v_shape'
    || hasEntry(entry, 'rotor', 'V Angle', 'V Depth');
  const magnets = Boolean(rotor && built.magnets && vPocketReady && hasEntry(entry, 'rotor', 'Pole Count', 'Magnet Thick.', 'Magnet Width'));
  const winding = Boolean(magnets && built.winding && hasEntry(entry, 'winding', 'Type', 'Turns / Coil', 'Parallel Paths'));
  return { stator, slots, teeth, rotor, magnets, winding };
}

export function useNewDesignEntry(designActive: boolean) {
  const [layout, setLayout] = useState<RotorLayout | null>(null);
  const [topology, setTopology] = useState<MotorConfig['topology'] | null>(null);
  const [fields, setFields] = useState<Record<string, boolean>>({});
  const [requirements, setRequirements] = useState<Record<string, RequiredField>>({});
  const designActiveRef = useRef(designActive);
  const mountedSections = useRef(new Set<string>());
  designActiveRef.current = designActive;
  const mountSection = useCallback((section: string) => {
    mountedSections.current.add(section);
    return () => { mountedSections.current.delete(section); };
  }, []);
  const confirm = useCallback((section: string, label: string) => {
    const key = entryKey(section, label);
    setFields((current) => current[key] ? current : { ...current, [key]: true });
  }, []);
  const forget = useCallback((section: string, labels: string[]) => {
    setFields((current) => {
      const next = { ...current };
      for (const label of labels) delete next[entryKey(section, label)];
      return next;
    });
  }, []);
  const register = useCallback((section: string, label: string, required: boolean) => {
    const key = entryKey(section, label);
    setRequirements((current) => current[key]?.required === required ? current : { ...current, [key]: { section, label, required } });
  }, []);
  const unregister = useCallback((section: string, label: string) => {
    // Keep requirements when a whole section is hidden by search or another
    // workflow stage; remove only conditional fields within a mounted section.
    if (!designActiveRef.current || !mountedSections.current.has(section)) return;
    const key = entryKey(section, label);
    setRequirements((current) => {
      if (!current[key]) return current;
      const next = { ...current }; delete next[key]; return next;
    });
  }, []);
  const entry: NewDesignEntry = { layout, topology, fields, requirements, confirm, forget, register, unregister, mountSection,
    ready: Boolean(layout && topology && (topology !== 'IPM' || fields[entryKey('topology', 'IPM rotor layout')])) };
  return { entry,
    chooseLayout: (value: RotorLayout) => { setLayout(value); setTopology(null); setFields({}); setRequirements({}); },
    chooseTopology: (value: MotorConfig['topology']) => { setTopology(value); setFields({}); },
  };
}

/** Untouched inputs stay empty; selecting an existing default still confirms it. */
export function useEntryField(label: string, required = true, alias?: string) {
  const entry = useContext(NewDesignEntryContext);
  const section = useContext(DesignSectionContext);
  const register = entry?.register; const unregister = entry?.unregister;
  useEffect(() => {
    if (!section || !register) return;
    register(section, label, required);
    return () => unregister?.(section, label);
  }, [section, label, required, register, unregister]);
  return {
    unset: Boolean(entry && section && !hasEntry(entry, section, alias ?? label)),
    confirm: () => { if (entry && section) { entry.confirm(section, label); if (alias) entry.confirm(section, alias); } },
    active: Boolean(entry && section),
    key: entryKey(section ?? '', label), required,
  };
}
