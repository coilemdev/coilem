import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const frontendRoot = path.resolve(import.meta.dirname, '..');
const publicRoot = path.join(frontendRoot, 'src', 'public');
const landingPreviewRoot = path.join(frontendRoot, 'src', 'components', 'landing-3d');
// The tutorial lessons are shared by the private workspace and the public app, the
// same way landing-3d is. Registering the tree here (rather than copying it under
// src/public) keeps one source of truth and puts the boundary audit ON the lessons,
// so a future lesson edit that reaches for a private module fails in CI.
const tutorialsRoot = path.join(frontendRoot, 'src', 'components', 'tutorials');
// The `.openem` file format is one contract shared with the private workspace, so
// the version and its migrations are imported rather than restated — they had
// drifted (public wrote v2 while the workspace read v3, which re-migrated a
// public save and never migrated an old file opened here). Registering the two
// modules keeps a single source of truth and puts this audit ON them, so neither
// can reach for a private module later. Both are dependency-free apart from each
// other; do NOT widen this to src/api, which is full of private surface.
const allowedSharedFiles = [
  path.join(frontendRoot, 'src', 'styles', 'variables.css'),
  path.join(frontendRoot, 'src', 'styles', 'templateselector.css'),
  path.join(frontendRoot, 'src', 'components', 'LandingWorkflowHero.tsx'),
  path.join(frontendRoot, 'src', 'api', 'projectSchema.ts'),
  path.join(frontendRoot, 'src', 'api', 'statorDefaults.ts'),
];
const allowedSourceRoots = [publicRoot, landingPreviewRoot, tutorialsRoot];
const allowedBareImports = new Set(['react', 'react-dom/client', 'three']);

function filesBelow(root) {
  return fs.readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(root, entry.name);
    return entry.isDirectory() ? filesBelow(target) : [target];
  });
}

const sourceFiles = [
  ...filesBelow(publicRoot),
  ...filesBelow(landingPreviewRoot),
  ...filesBelow(tutorialsRoot),
  ...allowedSharedFiles,
]
  .filter((file) => ['.ts', '.tsx', '.css', '.html'].includes(path.extname(file)));

function pathIsInside(target, root) {
  return target === root || target.startsWith(root + path.sep);
}

function isAllowedRelativeTarget(target) {
  if (allowedSourceRoots.some((root) => pathIsInside(target, root))) return true;
  return allowedSharedFiles.some((file) => target === file || target === file.slice(0, -path.extname(file).length));
}

function isAllowedBareImport(specifier) {
  return allowedBareImports.has(specifier) || specifier.startsWith('three/');
}

const forbiddenTerms = [
  ['account-sdk', /auth0/i],
  ['remote-service', /cloud/i],
  ['usage-reporting', /telemetry/i],
  ['private-solver', /femm/i],
  ['deferred-physics', /thermal/i],
  ['operations', /admin/i],
  ['payments', /billing/i],
  ['resource-limits', /quota/i],
];

const requiredPaths = [
  '/health',
  '/halbach/preview',
  '/halbach/mesh-preview',
  '/halbach/solve/validate',
  '/halbach/solve/stream',
  '/halbach/export/',
  '/materials',
  '/preview',
  '/runs',
  '/solver/mesh-preview',
  '/solve',
  '/solve/field-composition/armature',
  '/solve/field-composition/armature/stream',
  '/solve/field-frame/',
  '/solve/playback-frame/',
  '/solve/validate',
  '/solve/stream',
  '/solve/cancel',
];

const failures = [];
for (const file of sourceFiles) {
  const source = fs.readFileSync(file, 'utf8');
  for (const [label, pattern] of forbiddenTerms) {
    if (pattern.test(source)) {
      failures.push(`${path.relative(frontendRoot, file)} contains ${label} content`);
    }
  }
  if (['.ts', '.tsx'].includes(path.extname(file))) {
    // `from '…'`, `import('…')`, and bare side-effect `import '…'` (how every
    // lesson pulls in its stylesheet). Omitting the third form left a hole: nine
    // lessons imported ../../styles/learning.css from outside the allowed roots
    // and the audit reported a pass, because a side-effect import has no `from`.
    const relativeImports = [...source.matchAll(/(?:from\s+|import\s*\(\s*|import\s+)['"](\.\.?\/[^'"]+)['"]/g)];
    for (const match of relativeImports) {
      const target = path.resolve(path.dirname(file), match[1]);
      if (!isAllowedRelativeTarget(target)) {
        failures.push(`${path.relative(frontendRoot, file)} imports outside src/public: ${match[1]}`);
      }
    }
    const bareImports = [...source.matchAll(/(?:from\s+|import\s*\(\s*|import\s+)['"]([^.'"][^'"]*)['"]/g)];
    for (const match of bareImports) {
      if (!isAllowedBareImport(match[1])) {
        failures.push(`${path.relative(frontendRoot, file)} imports unapproved package: ${match[1]}`);
      }
    }
  }
}

const combinedSource = sourceFiles
  .map((file) => fs.readFileSync(file, 'utf8'))
  .join('\n');
for (const requiredPath of requiredPaths) {
  if (!combinedSource.includes(requiredPath)) {
    failures.push(`public API client is missing ${requiredPath}`);
  }
}
if (!combinedSource.includes('127.0.0.1:8000')) {
  failures.push('public API client has no loopback default');
}
if (failures.length > 0) {
  console.error(failures.join('\n'));
  process.exit(1);
}

console.log(`public boundary audit passed (${sourceFiles.length} source files)`);
