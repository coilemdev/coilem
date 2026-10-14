import ipm10pVShapeMedium from './examples/validation_ipm_10p_v_shape_medium.openem?raw';
import ipm14pFlatBuriedLarge from './examples/validation_ipm_14p_flat_buried_large.openem?raw';
import ornlPrius2004HoleM50 from './examples/ornl_prius_2004_holem50.coilem?raw';
import spm24pSmall from './examples/validation_spm_24p_small.openem?raw';

import { parseDesignFile } from './designFile';
import { cloneDefaultConfig, type MotorConfig } from './model';

export type PublicExampleId =
  | 'spm-8p12s'
  | 'ipm-10p-v-shape-medium'
  | 'ipm-14p-flat-buried-large'
  | 'spm-24p-small'
  | 'ornl-prius-2004-holem50';

export interface PublicExampleOption {
  id: PublicExampleId;
  label: string;
  detail: string;
  /** Needs the local app started with COILEM_EXPERIMENTAL_ROTORS=1. */
  experimental?: boolean;
}

export const PUBLIC_EXAMPLE_OPTIONS: readonly PublicExampleOption[] = [
  { id: 'spm-8p12s', label: 'SPM 8p/12s', detail: 'Starter motor' },
  { id: 'ipm-10p-v-shape-medium', label: 'IPM 10p V-shape', detail: 'Medium' },
  { id: 'ipm-14p-flat-buried-large', label: 'IPM 14p flat buried', detail: 'Large' },
  { id: 'spm-24p-small', label: 'SPM 24p', detail: 'Small' },
  { id: 'ornl-prius-2004-holem50', label: 'ORNL 2004 Prius', detail: 'HoleM50 · experimental', experimental: true },
];

/** The examples this launch can open: experimental rotors only when switched on. */
export function publicExampleOptions(experimentalRotors: boolean): readonly PublicExampleOption[] {
  return PUBLIC_EXAMPLE_OPTIONS.filter((option) => experimentalRotors || !option.experimental);
}

const BUNDLED_EXAMPLE_FILES: Record<Exclude<PublicExampleId, 'spm-8p12s'>, string> = {
  'ipm-10p-v-shape-medium': ipm10pVShapeMedium,
  'ipm-14p-flat-buried-large': ipm14pFlatBuriedLarge,
  'spm-24p-small': spm24pSmall,
  'ornl-prius-2004-holem50': ornlPrius2004HoleM50,
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
