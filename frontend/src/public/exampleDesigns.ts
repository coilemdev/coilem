import ipm10pVShapeMedium from './examples/validation_ipm_10p_v_shape_medium.openem?raw';
import ipm14pFlatBuriedLarge from './examples/validation_ipm_14p_flat_buried_large.openem?raw';
import spm24pSmall from './examples/validation_spm_24p_small.openem?raw';

import { parseDesignFile } from './designFile';
import { cloneDefaultConfig, type MotorConfig } from './model';

export type PublicExampleId =
  | 'spm-8p12s'
  | 'ipm-10p-v-shape-medium'
  | 'ipm-14p-flat-buried-large'
  | 'spm-24p-small';

export interface PublicExampleOption {
  id: PublicExampleId;
  label: string;
  detail: string;
}

export const PUBLIC_EXAMPLE_OPTIONS: readonly PublicExampleOption[] = [
  { id: 'spm-8p12s', label: 'SPM 8p/12s', detail: 'Starter motor' },
  { id: 'ipm-10p-v-shape-medium', label: 'IPM 10p V-shape', detail: 'Medium' },
  { id: 'ipm-14p-flat-buried-large', label: 'IPM 14p flat buried', detail: 'Large' },
  { id: 'spm-24p-small', label: 'SPM 24p', detail: 'Small' },
];

const BUNDLED_EXAMPLE_FILES: Record<Exclude<PublicExampleId, 'spm-8p12s'>, string> = {
  'ipm-10p-v-shape-medium': ipm10pVShapeMedium,
  'ipm-14p-flat-buried-large': ipm14pFlatBuriedLarge,
  'spm-24p-small': spm24pSmall,
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
