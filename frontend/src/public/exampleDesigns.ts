import hondaAccord2005 from './examples/honda_accord_2005.coilem?raw';
import ipm10pVShapeMedium from './examples/validation_ipm_10p_v_shape_medium.openem?raw';
import ipm14pFlatBuriedLarge from './examples/validation_ipm_14p_flat_buried_large.openem?raw';
import ornlPrius2004HoleM50 from './examples/ornl_prius_2004_holem50.coilem?raw';
import spm24pSmall from './examples/validation_spm_24p_small.openem?raw';
import rotatingField6p36s from './examples/rotating_field_6p36s.coilem?raw';

import { parseDesignFile } from './designFile';
import { cloneDefaultConfig, type MotorConfig } from './model';

export type PublicExampleId =
  | 'spm-8p12s'
  | 'rotating-field-6p36s'
  | 'ipm-10p-v-shape-medium'
  | 'ipm-14p-flat-buried-large'
  | 'spm-24p-small'
  | 'ornl-prius-2004-holem50'
  | 'honda-accord-2005';

export interface PublicExampleOption {
  id: PublicExampleId;
  label: string;
  detail: string;
  /** Needs the local app started with COILEM_EXPERIMENTAL_ROTORS=1. */
  experimental?: boolean;
  /**
   * A real motor that coilEM has been compared against published hardware
   * measurements. Listed under Benchmarks. Its design file holds only public
   * facts from the cited source, never licensed or proprietary data.
   */
  benchmark?: boolean;
}

export const PUBLIC_EXAMPLE_OPTIONS: readonly PublicExampleOption[] = [
  { id: 'spm-8p12s', label: 'SPM 8p/12s', detail: 'Starter motor' },
  { id: 'rotating-field-6p36s', label: 'Rotating field 6p/36s', detail: 'Three pole pairs · distributed winding' },
  { id: 'ipm-10p-v-shape-medium', label: 'IPM 10p V-shape', detail: 'Medium' },
  { id: 'ipm-14p-flat-buried-large', label: 'IPM 14p flat buried', detail: 'Large' },
  { id: 'spm-24p-small', label: 'SPM 24p', detail: 'Small' },
  {
    id: 'ornl-prius-2004-holem50',
    label: 'ORNL 2004 Prius',
    detail: 'ORNL hardware data · experimental rotor',
    experimental: true,
    benchmark: true,
  },
  {
    id: 'honda-accord-2005',
    label: '2005 Honda Accord',
    detail: 'ORNL hardware data · tooth coils',
    benchmark: true,
  },
];

export type PublicExampleGroup = 'motor' | 'benchmark';

/** The examples this launch can open in one menu group: experimental rotors only when switched on. */
export function publicExampleOptions(
  experimentalRotors: boolean,
  group: PublicExampleGroup = 'motor',
): readonly PublicExampleOption[] {
  return PUBLIC_EXAMPLE_OPTIONS.filter(
    (option) => (experimentalRotors || !option.experimental) && Boolean(option.benchmark) === (group === 'benchmark'),
  );
}

const BUNDLED_EXAMPLE_FILES: Record<Exclude<PublicExampleId, 'spm-8p12s'>, string> = {
  'rotating-field-6p36s': rotatingField6p36s,
  'ipm-10p-v-shape-medium': ipm10pVShapeMedium,
  'ipm-14p-flat-buried-large': ipm14pFlatBuriedLarge,
  'spm-24p-small': spm24pSmall,
  'ornl-prius-2004-holem50': ornlPrius2004HoleM50,
  'honda-accord-2005': hondaAccord2005,
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
