import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, '..');
const source = await readFile(
  path.join(frontendRoot, 'src/public/motorAirgap.ts'),
  'utf8',
);
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
});
const tempDir = await mkdtemp(path.join(tmpdir(), 'coilem-public-airgap-'));

try {
  const modulePath = path.join(tempDir, 'motorAirgap.mjs');
  await writeFile(modulePath, transpiled.outputText, 'utf8');
  const airgap = await import(pathToFileURL(modulePath).href);
  const spm = {
    topology: 'SPM',
    stator: { ID_mm: 120 },
    rotor: {
      OD_mm: 110,
      ID_mm: 30,
      magnet_thickness_mm: 4,
    },
  };

  assert.equal(airgap.magneticAirgapMm(spm), 1);
  assert.equal(airgap.rotorAirgapBoundaryRadiusMm(spm), 59);

  const ipm = airgap.changeTopologyPreservingAirgap(spm, 'IPM');
  assert.equal(ipm.topology, 'IPM');
  assert.equal(ipm.rotor.OD_mm, 118);
  assert.equal(airgap.magneticAirgapMm(ipm), 1);
  assert.equal(airgap.rotorAirgapBoundaryRadiusMm(ipm), 59);

  const roundTrip = airgap.changeTopologyPreservingAirgap(ipm, 'SPM');
  assert.equal(roundTrip.rotor.OD_mm, 110);
  assert.equal(airgap.magneticAirgapMm(roundTrip), 1);

  const constrainedIpm = {
    ...ipm,
    stator: { ID_mm: 20 },
    rotor: {
      ...ipm.rotor,
      OD_mm: 15,
      ID_mm: 14.9,
      magnet_thickness_mm: 10,
    },
  };
  const constrainedSpm = airgap.changeTopologyPreservingAirgap(constrainedIpm, 'SPM');
  assert.equal(constrainedSpm.rotor.OD_mm, 15);
  assert.equal(constrainedSpm.rotor.magnet_thickness_mm, 2);
  assert.ok(constrainedSpm.rotor.magnet_thickness_mm <= constrainedSpm.rotor.OD_mm / 4);
  assert.ok(constrainedSpm.rotor.ID_mm < constrainedSpm.rotor.OD_mm);
  assert.ok(airgap.magneticAirgapMm(constrainedSpm) >= 0.3 - 1e-9);

  assert.equal(airgap.publicAirgapHealth(0.29).title, 'Airgap is below the launch minimum');
  assert.equal(airgap.publicAirgapHealth(0.4).title, 'Airgap is tighter than recommended');
  assert.equal(airgap.publicAirgapHealth(1).severity, 'positive');
  assert.equal(airgap.publicAirgapHealth(1.75).title, 'Airgap is larger than typical');
  assert.equal(airgap.publicAirgapHealth(5).title, 'Airgap is substantially oversized');
} finally {
  await rm(tempDir, { recursive: true, force: true });
}

console.log('Public airgap UX checks passed.');
