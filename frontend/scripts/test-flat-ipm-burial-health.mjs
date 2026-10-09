import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, '..');
const source = await readFile(
  path.join(frontendRoot, 'src/public/flatIpmBurialHealth.ts'),
  'utf8',
);
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
});
const tempDir = await mkdtemp(path.join(tmpdir(), 'coilem-flat-ipm-health-'));

try {
  const modulePath = path.join(tempDir, 'flatIpmBurialHealth.mjs');
  await writeFile(modulePath, transpiled.outputText, 'utf8');
  const health = await import(pathToFileURL(modulePath).href);
  const config = {
    topology: 'IPM',
    rotor: {
      OD_mm: 118,
      ID_mm: 70,
      magnet_thickness_mm: 4,
      magnet_width_mm: 31.4,
      bridge_thickness_mm: 4,
      pocket_clearance_mm: 0.25,
      ipm_topology: 'flat_buried',
      flat_buried_magnet_shape: 'straight',
    },
  };

  const healthy = health.publicFlatIpmBurialHealth(config);
  const centerRadius = health.publicFlatIpmMagnetCenterRadiusMm(config);
  const expectedRemainingInnerWeb = centerRadius
    - config.rotor.magnet_thickness_mm / 2
    - config.rotor.pocket_clearance_mm
    - config.rotor.ID_mm / 2;
  assert.equal(healthy.severity, 'positive');
  assert.equal(healthy.blocking, false);
  assert.equal(healthy.remainingInnerWebMm, expectedRemainingInnerWeb);
  assert.equal(healthy.advisoryInnerWebMm, 1.5);
  assert.match(
    healthy.copy,
    new RegExp(`4\\.00 mm outer bridge leaves ${expectedRemainingInnerWeb.toFixed(2).replace('.', '\\.')} mm inner web`),
  );

  const pocketHalfWidth = config.rotor.magnet_width_mm / 2 + config.rotor.pocket_clearance_mm;
  const pocketHalfDepth = config.rotor.magnet_thickness_mm / 2 + config.rotor.pocket_clearance_mm;
  assert.ok(Math.abs(
    Math.hypot(centerRadius + pocketHalfDepth, pocketHalfWidth)
      - (config.rotor.OD_mm / 2 - config.rotor.bridge_thickness_mm),
  ) < 1e-9,
  'the closest 3D pocket corner must preserve the configured outer bridge',
  );
  const deeperCenterRadius = health.publicFlatIpmMagnetCenterRadiusMm({
    ...config,
    rotor: { ...config.rotor, bridge_thickness_mm: 8 },
  });
  assert.ok(
    deeperCenterRadius < centerRadius - 4,
    'increasing the minimum corner bridge must move the flat magnet inward',
  );

  const outerBridgeForInnerWeb = (remainingInnerWebMm) => {
    const targetCenterRadius = config.rotor.ID_mm / 2
      + pocketHalfDepth
      + remainingInnerWebMm;
    const targetCornerRadius = Math.hypot(
      targetCenterRadius + pocketHalfDepth,
      pocketHalfWidth,
    );
    return config.rotor.OD_mm / 2 - targetCornerRadius;
  };
  const narrow = health.publicFlatIpmBurialHealth({
    ...config,
    rotor: { ...config.rotor, bridge_thickness_mm: outerBridgeForInnerWeb(1.4) },
  });
  assert.equal(narrow.title, 'Outer bridge leaves a narrow inner web');
  assert.equal(narrow.blocking, false);
  assert.ok(Math.abs(narrow.remainingInnerWebMm - 1.4) < 1e-9);

  const invalid = health.publicFlatIpmBurialHealth({
    ...config,
    rotor: { ...config.rotor, bridge_thickness_mm: outerBridgeForInnerWeb(0.5) },
  });
  assert.equal(invalid.title, 'Outer bridge reaches the inner rotor margin');
  assert.equal(invalid.blocking, true);
  assert.ok(Math.abs(invalid.remainingInnerWebMm - 0.5) < 1e-9);

  const noBridge = health.publicFlatIpmBurialHealth({
    ...config,
    rotor: { ...config.rotor, bridge_thickness_mm: 0 },
  });
  assert.equal(noBridge.title, 'Outer bridge must be positive');
  assert.equal(noBridge.blocking, true);

  const advisoryBoundary = health.publicFlatIpmBurialHealth({
    ...config,
    rotor: { ...config.rotor, bridge_thickness_mm: outerBridgeForInnerWeb(1.5) },
  });
  assert.equal(advisoryBoundary.severity, 'positive');
  assert.equal(advisoryBoundary.blocking, false);

  const solidRotor = health.publicFlatIpmBurialHealth({
    ...config,
    rotor: { ...config.rotor, ID_mm: null },
  });
  assert.equal(solidRotor.severity, 'positive');
  assert.ok(solidRotor.remainingInnerWebMm > healthy.remainingInnerWebMm);

  assert.equal(health.publicFlatIpmBurialHealth({ ...config, topology: 'SPM' }), null);
  assert.equal(health.publicFlatIpmBurialHealth({
    ...config,
    rotor: { ...config.rotor, ipm_topology: 'v_shape' },
  }), null);
  assert.equal(health.publicFlatIpmBurialHealth({
    ...config,
    rotor: { ...config.rotor, flat_buried_magnet_shape: 'legacy_arc' },
  }), null, 'straight-pocket health must not describe compatibility arc geometry');
} finally {
  await rm(tempDir, { recursive: true, force: true });
}

console.log('Flat-IPM outer-bridge health checks passed.');
