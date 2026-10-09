import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, '..');

async function loadTypeOnlyModule(sourcePath, moduleName) {
  const source = await readFile(path.join(frontendRoot, sourcePath), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const tempDir = await mkdtemp(path.join(tmpdir(), 'coilem-public-geometry-'));
  const modulePath = path.join(tempDir, moduleName);
  await writeFile(modulePath, compiled, 'utf8');
  return {
    module: await import(pathToFileURL(modulePath).href),
    dispose: () => rm(tempDir, { recursive: true, force: true }),
  };
}

const qualityModule = await loadTypeOnlyModule(
  'src/public/meshQuality.ts',
  'meshQuality.mjs',
);
const dimensionsModule = await loadTypeOnlyModule(
  'src/public/dimensionAnnotations.ts',
  'dimensionAnnotations.mjs',
);

try {
  const {
    publicMeshQualityBand,
    publicTriangleQuality,
    summarizePublicMeshQuality,
  } = qualityModule.module;
  const { deriveStatorSectionWidths } = dimensionsModule.module;
  const equilateralNodes = [[0, 0], [1, 0], [0.5, Math.sqrt(3) / 2]];

  assert.ok(Math.abs(publicTriangleQuality(equilateralNodes, [0, 1, 2]) - 1) < 1e-12);
  assert.equal(publicTriangleQuality([[0, 0], [1, 0], [2, 0]], [0, 1, 2]), 0);
  assert.equal(publicTriangleQuality(equilateralNodes, [0, 1, 99]), 0);
  assert.equal(publicMeshQualityBand(0.009, 0.01), 'failing');
  assert.equal(publicMeshQualityBand(0.05, 0.01), 'marginal');
  assert.equal(publicMeshQualityBand(0.2, 0.01), 'acceptable');
  assert.equal(publicMeshQualityBand(0.8, 0.01), 'good');

  const summary = summarizePublicMeshQuality({
    nodes_mm: [...equilateralNodes, [2, 0]],
    triangles: [[0, 1, 2], [0, 1, 3]],
    mesh_qa: { min_quality_threshold: 0.01 },
  });
  assert.equal(summary.minimum, 0);
  assert.equal(summary.minimumElementIndex, 1);
  assert.deepEqual(summary.weakElementIndices, [1]);
  assert.deepEqual(summary.counts, {
    good: 1,
    acceptable: 0,
    marginal: 0,
    failing: 1,
  });

  const config = {
    stator: {
      OD_mm: 200,
      ID_mm: 120,
      slot_count: 12,
      slot_opening_mm: 8,
      tooth_width_mm: 20,
      yoke_thickness_mm: 20,
      tooth_shoe_enabled: true,
      tooth_shoe_overhang_mm: 1.5,
    },
  };
  const withShoe = deriveStatorSectionWidths(config);
  const borePitch = Math.PI * 120 / 12;
  assert.ok(Math.abs(withShoe.boreToothWidthMm - (borePitch - 8 + 3)) < 1e-12);
  const withoutShoe = deriveStatorSectionWidths({
    ...config,
    stator: { ...config.stator, tooth_shoe_enabled: false },
  });
  assert.ok(Math.abs(withoutShoe.boreToothWidthMm - (borePitch - 8)) < 1e-12);
} finally {
  await Promise.all([qualityModule.dispose(), dimensionsModule.dispose()]);
}

console.log('Public mesh-quality and stator-width checks passed.');
