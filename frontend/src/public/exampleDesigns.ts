import hondaAccord2005 from './examples/honda_accord_2005.coilem?raw';
import ipm10pVShapeMedium from './examples/validation_ipm_10p_v_shape_medium.openem?raw';
import ipm14pFlatBuriedLarge from './examples/validation_ipm_14p_flat_buried_large.openem?raw';
import ornlPrius2004HoleM50 from './examples/ornl_prius_2004_holem50.coilem?raw';
import spm24pSmall from './examples/validation_spm_24p_small.openem?raw';
import rotatingField6p36s from './examples/rotating_field_6p36s.coilem?raw';
import spmOutrunner14p12s from './examples/spm_outrunner_14p12s.coilem?raw';
import jointOutrunner36s40p from './examples/joint_outrunner_36s40p.coilem?raw';
import droneOutrunner36s40pB from './examples/drone_outrunner_36s40p_b.coilem?raw';

import priusTutorial from './examples/prius-2004-tutorial-bemf-v1.coilem?raw';
import priusLoaded from './examples/prius-2004-loaded-torque-v1.coilem?raw';
import lrkSixStep from './examples/lrk-12s14p-six-step.coilem?raw';
import lrkFixedCurrent from './examples/lrk-12s14p-fixed-current-v1.coilem?raw';

import { parseDesignFile } from './designFile';
import { cloneDefaultConfig, type MotorConfig } from './model';

export type PublicExampleId =
  | 'prius-2004-tutorial-bemf-v1'
  | 'prius-2004-loaded-torque-v1'
  | 'spm-8p12s'
  | 'rotating-field-6p36s'
  | 'spm-outrunner-14p12s'
  | 'ipm-10p-v-shape-medium'
  | 'ipm-14p-flat-buried-large'
  | 'spm-24p-small'
  | 'ornl-prius-2004-holem50'
  | 'honda-accord-2005'
  | 'joint-outrunner-36s40p'
  | 'drone-outrunner-36s40p-b'
  | 'lrk-12s14p-six-step'
  | 'lrk-12s14p-fixed-current-v1';

export interface PublicExampleOption {
  id: PublicExampleId;
  label: string;
  detail: string;
  /** Needs the local app started with COILEM_EXPERIMENTAL_ROTORS=1. */
  experimental?: boolean;
  /**
   * A motor compared against published hardware or a published software model. Listed under Benchmarks. Its design file holds only public
   * facts from the cited source, never licensed or proprietary data.
   */
  benchmark?: boolean;
  /** Held back until the owner clears redistribution of its source data. */
  pendingDataRights?: boolean;
  /**
   * A motor example whose design Design Health rates experimental (backend/qualification.py): the menu tags it as it tags
   * every benchmark. tests/test_example_qualification_tags.py keeps these flags in line with that rating.
   */
  experimentalDesign?: boolean;
  /** Where the rotor sits, as in the design's rotor_layout: the menu lists inrunners and outrunners apart. */
  layout: 'inner' | 'outer';
}

// The LRK examples embed the source model's B-H curves, whose redistribution
// rights are unconfirmed (as for the quarantined M19 samples in material_catalog.py).
// A local build sets VITE_COILEM_LRK_EXAMPLES=1 to review them.
const PENDING_DATA_RIGHTS_SHOWN = import.meta.env.VITE_COILEM_LRK_EXAMPLES === '1';

export const PUBLIC_EXAMPLE_OPTIONS: readonly PublicExampleOption[] = [
  { id: 'prius-2004-tutorial-bemf-v1', label: 'Pyleecan Prius 8p48s · BEMF', detail: '1000 rpm · 20°C · no load · software reference', benchmark: true, layout: 'inner' },
  { id: 'prius-2004-loaded-torque-v1', label: 'Pyleecan Prius 8p48s · Loaded torque', detail: '2000 rpm · 60°C · 250 A peak · software reference', benchmark: true, layout: 'inner' },
  { id: 'spm-8p12s', label: 'SPM 8p/12s', detail: 'Starter motor', layout: 'inner' },
  { id: 'rotating-field-6p36s', label: 'SPM 6p/36s', detail: 'Three pole pairs · distributed winding', layout: 'inner' },
  { id: 'spm-outrunner-14p12s', label: 'SPM outrunner 14p/12s', detail: 'Outer rotor · drone class · tooth coils', experimentalDesign: true, layout: 'outer' },
  { id: 'ipm-10p-v-shape-medium', label: 'IPM 10p V-shape', detail: 'Medium', experimentalDesign: true, layout: 'inner' },
  { id: 'ipm-14p-flat-buried-large', label: 'IPM 14p flat buried', detail: 'Large', layout: 'inner' },
  { id: 'spm-24p-small', label: 'SPM 24p', detail: 'Small', experimentalDesign: true, layout: 'inner' },
  {
    id: 'ornl-prius-2004-holem50',
    label: 'ORNL 2004 Prius',
    detail: 'ORNL hardware data · experimental rotor',
    experimental: true,
    benchmark: true,
    layout: 'inner',
  },
  {
    id: 'honda-accord-2005',
    label: '2005 Honda Accord',
    detail: 'ORNL hardware data · tooth coils',
    benchmark: true,
    layout: 'inner',
  },
  {
    id: 'joint-outrunner-36s40p',
    label: 'Robot-joint outrunner 40p / 36s',
    detail: 'Published hardware data · outer rotor · tooth shoes',
    benchmark: true,
    layout: 'outer',
  },
  {
    id: 'drone-outrunner-36s40p-b',
    label: 'Drone outrunner 40p / 36s · B',
    detail: 'Published hardware data · outer rotor · delta',
    benchmark: true,
    layout: 'outer',
  },
  { id: 'lrk-12s14p-six-step', label: 'LRK outrunner 14p / 12s', detail: 'Outer rotor · six-step 4 A · software reference', pendingDataRights: true, experimentalDesign: true, layout: 'outer' },
  {
    id: 'lrk-12s14p-fixed-current-v1',
    label: 'LRK 14p / 12s · Fixed current',
    detail: 'Published comparison · 0 / −4 / +4 A · software reference',
    benchmark: true,
    pendingDataRights: true,
    layout: 'outer',
  },
];

export type PublicExampleGroup = 'motor' | 'benchmark';

/** The examples this launch can open in one menu group: experimental rotors only when switched on. */
export function publicExampleOptions(
  experimentalRotors: boolean,
  group: PublicExampleGroup = 'motor',
): readonly PublicExampleOption[] {
  return PUBLIC_EXAMPLE_OPTIONS.filter(
    (option) => (experimentalRotors || !option.experimental)
      && (PENDING_DATA_RIGHTS_SHOWN || !option.pendingDataRights)
      && Boolean(option.benchmark) === (group === 'benchmark'),
  );
}

export interface PublicExampleLayoutGroup {
  layout: 'inner' | 'outer';
  label: string;
  options: readonly PublicExampleOption[];
}

/** One menu group's examples split by rotor layout, inrunners first; empty layouts are left out. */
export function examplesByLayout(options: readonly PublicExampleOption[]): PublicExampleLayoutGroup[] {
  return ([['inner', 'Inrunner'], ['outer', 'Outrunner']] as const)
    .map(([layout, label]) => ({ layout, label, options: options.filter((option) => option.layout === layout) }))
    .filter((group) => group.options.length > 0);
}

const BUNDLED_EXAMPLE_FILES: Record<Exclude<PublicExampleId, 'spm-8p12s'>, string> = {
  'prius-2004-tutorial-bemf-v1': priusTutorial,
  'prius-2004-loaded-torque-v1': priusLoaded,
  'rotating-field-6p36s': rotatingField6p36s,
  'spm-outrunner-14p12s': spmOutrunner14p12s,
  'ipm-10p-v-shape-medium': ipm10pVShapeMedium,
  'ipm-14p-flat-buried-large': ipm14pFlatBuriedLarge,
  'spm-24p-small': spm24pSmall,
  'ornl-prius-2004-holem50': ornlPrius2004HoleM50,
  'honda-accord-2005': hondaAccord2005,
  'joint-outrunner-36s40p': jointOutrunner36s40p,
  'drone-outrunner-36s40p-b': droneOutrunner36s40pB,
  'lrk-12s14p-six-step': lrkSixStep,
  'lrk-12s14p-fixed-current-v1': lrkFixedCurrent,
};

export function createPublicExampleDesign(exampleId: PublicExampleId): { name: string; config: MotorConfig } {
  if (exampleId === 'spm-8p12s') {
    return { name: 'Example SPM 8p/12s', config: cloneDefaultConfig() };
  }
  const parsed = parseDesignFile(BUNDLED_EXAMPLE_FILES[exampleId]);
  const option = PUBLIC_EXAMPLE_OPTIONS.find((candidate) => candidate.id === exampleId);
  return {
    name: parsed.name || option?.label || 'Example motor',
    config: parsed.config,
  };
}
