// Project-file schema versioning.
//
// Every saved `.openem` payload (and the localStorage draft/recent-project
// snapshots) carries an integer `openem_schema_version`. Loading routes through
// `migrateProjectFile()`, which upgrades the raw payload one version at a
// time until it reaches the current schema. Files written before the stamp
// existed (every file up to and including openem_version 0.1.1) are treated
// as version 0 — the loader's existing normalize fallbacks absorb them, so
// the v0 → v1 migration is the identity. v2 removes legacy Structured/Spade
// mesher choices by normalizing loaded config state to Gmsh. v3 re-references
// `tooth_width_mm` from the bore pitch to the slot-body pitch, which is a
// reinterpretation of an existing field and therefore needs a migration rather
// than a default. v4 makes flat-buried IPM magnets genuinely straight while
// tagging older saved flat-IPM designs with their legacy annular-sector shape.
//
// Compatibility policy lives in docs/schema_compatibility_policy.md. The
// short version: during beta, schema changes are additive-optional only and
// a new field's default must reproduce the previous behavior exactly. A
// schema change that needs more than that gets a new version number and a
// migration function here — never a silent reinterpretation of old files.

import { toothWidthBodyPitchShiftMm } from './statorDefaults';

export const COILEM_SCHEMA_VERSION = 4;
export type OpenEmProjectKind = 'motor' | 'halbach_array';

/**
 * Additive v3 discriminator. Every pre-Halbach file omitted the field, so
 * absence must continue to mean motor forever.
 */
export function projectKindFromFile(raw: unknown): OpenEmProjectKind {
  if (isObject(raw) && raw.project_kind === 'halbach_array') return 'halbach_array';
  return 'motor';
}

export interface MigratedProjectFile {
  /** The payload upgraded to COILEM_SCHEMA_VERSION. */
  data: any;
  /** Version the payload declared (0 = pre-stamp legacy file). */
  fromVersion: number;
  /** True when the file declares a NEWER schema than this build knows. */
  fromFuture: boolean;
}

function declaredVersion(raw: any): number {
  const value = raw?.openem_schema_version;
  if (typeof value === 'number' && Number.isInteger(value) && value >= 0) {
    return value;
  }
  return 0;
}

function isObject(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeLegacySolveParams(solveParams: unknown): unknown {
  if (!isObject(solveParams)) return solveParams;
  if (solveParams.mesher !== 'structured' && solveParams.mesher !== 'spade') {
    return solveParams;
  }
  return {
    ...solveParams,
    mesher: 'gmsh',
    slot_sidewall_refinement: false,
  };
}

function normalizeLegacySolveOptions(solveOptions: unknown): unknown {
  if (!isObject(solveOptions)) return solveOptions;
  if (solveOptions.mesher !== 'structured' && solveOptions.mesher !== 'spade') {
    return solveOptions;
  }
  return {
    ...solveOptions,
    mesher: 'gmsh',
    slotSidewallRefinement: false,
    slot_sidewall_refinement: false,
  };
}

function migrateLegacyMeshersToGmsh(data: any): any {
  if (!isObject(data)) return data;
  const next = { ...data };
  if ('solve_params' in next) {
    next.solve_params = normalizeLegacySolveParams(next.solve_params);
  }
  if ('solveOptions' in next) {
    next.solveOptions = normalizeLegacySolveOptions(next.solveOptions);
  }
  if (isObject(next.openem_config)) {
    next.openem_config = {
      ...next.openem_config,
      solve_params: normalizeLegacySolveParams(next.openem_config.solve_params),
    };
  }
  return next;
}

/**
 * v2 -> v3: `tooth_width_mm` now means the tooth width at the slot body.
 *
 * The slot body used to be sized as `bore pitch - tooth_width_mm` even though the
 * body sits out beside the yoke at `ID/2 + slot depth`, where the pitch arc is larger — 31.4mm
 * against 42.9mm on the shipped 8p/12s example. The field moved the tooth without
 * ever equalling it: 14.1 drew a 25.6mm tooth. The subtraction now happens at the
 * body radius, so an unmigrated file would silently get a much narrower tooth and a
 * wider slot than it was designed with.
 *
 * Rewriting the stored value keeps every saved design's geometry byte-identical:
 *
 *   new = old + (2*pi / slots) * slot_depth      slot_depth = (OD - ID)/2 - yoke
 *
 * which is exactly the difference between the two pitch arcs. On the shipped
 * example that turns 14.1 into 25.62 — the value that reproduces its 17.3mm slot.
 */
function migrateToothWidthToBodyPitch(data: any): any {
  if (!isObject(data)) return data;

  // Backend shape: snake_case MotorConfig stator.
  const convertStator = (stator: any): any => {
    if (!isObject(stator)) return stator;
    const toothWidth = Number(stator.tooth_width_mm);
    const geometry = {
      outerDiameter: Number(stator.OD_mm),
      innerDiameter: Number(stator.ID_mm),
      slotCount: Number(stator.slot_count),
      yokeThickness: Number(stator.yoke_thickness_mm),
    };
    if (!Number.isFinite(toothWidth)) return stator;
    if (!Object.values(geometry).every((value) => Number.isFinite(value))) return stator;
    if (geometry.slotCount <= 0) return stator;
    const shifted = toothWidth + toothWidthBodyPitchShiftMm(geometry);
    return { ...stator, tooth_width_mm: Number(shifted.toFixed(4)) };
  };

  // Frontend shape: the camelCase statorGeometry inside a ProjectSnapshot, which
  // is what autosave, recent projects, the baseline and the compare runs persist.
  // `yokeThickness` is optional there, and mapFrontendToBackend falls back to
  // defaultYokeThicknessMm, so the shift has to use the same effective yoke —
  // slotRadialDepthMm applies that fallback. A snapshot with no `toothWidth` is
  // left alone: it has no stored value to reinterpret and picks up
  // defaultToothWidthMm, which carries the same shift.
  const convertStatorGeometry = (geometry: any): any => {
    if (!isObject(geometry)) return geometry;
    const toothWidth = Number(geometry.toothWidth);
    if (!Number.isFinite(toothWidth)) return geometry;
    const outer = Number(geometry.outerDiameter);
    const inner = Number(geometry.innerDiameter);
    const slots = Number(geometry.slotCount);
    if (![outer, inner, slots].every((value) => Number.isFinite(value))) return geometry;
    if (slots <= 0) return geometry;
    const yoke = Number(geometry.yokeThickness);
    const shifted = toothWidth + toothWidthBodyPitchShiftMm({
      outerDiameter: outer,
      innerDiameter: inner,
      slotCount: slots,
      yokeThickness: Number.isFinite(yoke) ? yoke : undefined,
    });
    return { ...geometry, toothWidth: Number(shifted.toFixed(4)) };
  };

  const convertParams = (params: any): any => {
    if (!isObject(params) || !('statorGeometry' in params)) return params;
    return { ...params, statorGeometry: convertStatorGeometry(params.statorGeometry) };
  };

  // Shape-tolerant, like the v1 -> v2 step: the same pipeline runs for `.openem`
  // files, the autosave snapshot and recent-project entries, so the stator can be
  // at the root, under `config`, or under `openem_config`, and the snapshot's
  // frontend params can be at the root or under `config`.
  const next = { ...data };
  if ('stator' in next) next.stator = convertStator(next.stator);
  if ('params' in next) next.params = convertParams(next.params);
  if ('statorGeometry' in next) next.statorGeometry = convertStatorGeometry(next.statorGeometry);
  if (isObject(next.config)) {
    // Only rewrite keys the payload actually has, so a config without a stator
    // does not come back with an explicit `stator: undefined`.
    const config = { ...next.config };
    if ('stator' in config) config.stator = convertStator(config.stator);
    if ('params' in config) config.params = convertParams(config.params);
    next.config = config;
  }
  if (isObject(next.openem_config) && 'stator' in next.openem_config) {
    next.openem_config = { ...next.openem_config, stator: convertStator(next.openem_config.stator) };
  }
  return next;
}

/**
 * v3 -> v4: new flat-buried IPM designs use straight rectangular magnet bars.
 *
 * Before v4 the `flat_buried` name produced annular sectors. Preserve that
 * solver-visible geometry for already-saved projects by stamping the hidden
 * compatibility selector. New v4 files omit it or write `straight`.
 */
function preserveLegacyFlatIpmArcGeometry(data: any): any {
  if (!isObject(data)) return data;

  const convertRotor = (rotor: any, topology: unknown): any => {
    if (!isObject(rotor) || topology !== 'IPM') return rotor;
    const ipmTopology = rotor.ipm_topology;
    if (ipmTopology !== undefined && ipmTopology !== 'flat_buried') return rotor;
    if ('flat_buried_magnet_shape' in rotor) return rotor;
    return { ...rotor, flat_buried_magnet_shape: 'legacy_arc' };
  };

  const convertRotorMagnets = (rotor: any, topology: unknown): any => {
    if (!isObject(rotor) || topology !== 'IPM') return rotor;
    const ipmTopology = rotor.ipmRotorTopology;
    if (ipmTopology !== undefined && ipmTopology !== 'flat_buried') return rotor;
    if ('flatBuriedMagnetShape' in rotor) return rotor;
    return { ...rotor, flatBuriedMagnetShape: 'legacy_arc' };
  };

  const convertParams = (params: any, topology: unknown): any => {
    if (!isObject(params) || !('rotorMagnets' in params)) return params;
    return {
      ...params,
      rotorMagnets: convertRotorMagnets(params.rotorMagnets, topology),
    };
  };

  const next = { ...data };
  if ('rotor' in next) next.rotor = convertRotor(next.rotor, next.topology);
  if ('rotorMagnets' in next) {
    next.rotorMagnets = convertRotorMagnets(next.rotorMagnets, next.topology);
  }
  if ('params' in next) next.params = convertParams(next.params, next.topology);
  if (isObject(next.config)) {
    const config = { ...next.config };
    if ('rotor' in config) config.rotor = convertRotor(config.rotor, config.topology);
    if ('rotorMagnets' in config) {
      config.rotorMagnets = convertRotorMagnets(config.rotorMagnets, config.topology);
    }
    if ('params' in config) config.params = convertParams(config.params, config.topology);
    next.config = config;
  }
  if (isObject(next.openem_config) && 'rotor' in next.openem_config) {
    next.openem_config = {
      ...next.openem_config,
      rotor: convertRotor(next.openem_config.rotor, next.openem_config.topology),
    };
  }
  return next;
}

// Each entry upgrades a payload FROM its key version to key + 1. Keep these
// pure and shape-tolerant: the same pipeline runs for `.openem` files, the
// autosave snapshot, and recent-project entries.
const MIGRATIONS: Record<number, (data: any) => any> = {
  // v0 (no stamp) -> v1: identity. The pre-stamp shapes — backend MotorConfig
  // JSON, snapshot-shaped exports, and `openem_config` wrappers — are exactly
  // what the loader's normalize fallbacks already accept.
  0: (data) => data,
  // v1 -> v2: legacy native meshers are retired. Old saved projects that carry
  // `structured` or `spade` now load through the supported Gmsh native mesher.
  1: migrateLegacyMeshersToGmsh,
  // v2 -> v3: tooth_width_mm re-referenced to the slot-body pitch.
  2: migrateToothWidthToBodyPitch,
  // v3 -> v4: retain annular-sector geometry only for already-saved flat IPM.
  3: preserveLegacyFlatIpmArcGeometry,
};

export function migrateProjectFile(raw: any): MigratedProjectFile {
  const fromVersion = declaredVersion(raw);
  if (fromVersion > COILEM_SCHEMA_VERSION) {
    // A newer build wrote this file. Don't guess at downgrades — pass it
    // through (additive-only policy means it usually still loads) and let
    // the caller surface a warning.
    return { data: raw, fromVersion, fromFuture: true };
  }
  let data = raw;
  for (let version = fromVersion; version < COILEM_SCHEMA_VERSION; version += 1) {
    const step = MIGRATIONS[version];
    if (step) data = step(data);
  }
  return { data, fromVersion, fromFuture: false };
}

/** Stamp an outgoing payload with the current schema version. */
export function stampSchemaVersion<T extends Record<string, unknown>>(payload: T): T & { openem_schema_version: number } {
  return { ...payload, openem_schema_version: COILEM_SCHEMA_VERSION };
}
