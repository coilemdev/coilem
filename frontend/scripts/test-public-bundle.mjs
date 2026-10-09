import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const frontendRoot = path.resolve(import.meta.dirname, '..');
const bundleRoot = path.join(frontendRoot, 'dist-public-boundary');

function filesBelow(root) {
  return fs.readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(root, entry.name);
    return entry.isDirectory() ? filesBelow(target) : [target];
  });
}

const bundleFiles = filesBelow(bundleRoot)
  .filter((file) => ['.js', '.css', '.html'].includes(path.extname(file)));

const forbiddenPatterns = [
  /auth0/i,
  /cloud/i,
  /telemetry/i,
  /femm/i,
  /thermal/i,
  /admin/i,
  /billing/i,
  /quota/i,
];

const failures = [];
for (const file of bundleFiles) {
  const source = fs.readFileSync(file, 'utf8');
  for (const pattern of forbiddenPatterns) {
    if (pattern.test(source)) {
      failures.push(`${path.relative(frontendRoot, file)} contains ${pattern}`);
    }
  }
}
if (bundleFiles.length === 0) {
  failures.push('public boundary build produced no JavaScript bundle');
}
if (failures.length > 0) {
  console.error(failures.join('\n'));
  process.exit(1);
}

console.log(`public bundle audit passed (${bundleFiles.length} emitted files)`);
