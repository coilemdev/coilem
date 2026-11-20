import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { advisories, compareVersions, evaluateAudit, insideRange } from './audit-dependencies.mjs';

// The shape of `npm audit --json` for the picomatch advisory reached through Vite.
const via = { source: 1247710, name: 'picomatch', title: 'picomatch vulnerable to ReDoS through single-branch repeated extglobs',
  url: 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf', severity: 'high', range: '<=4.0.7' };
const report = { vulnerabilities: {
  picomatch: { name: 'picomatch', severity: 'high', via: [via] },
  fdir: { name: 'fdir', severity: 'high', via: ['picomatch'] },
  vite: { name: 'vite', severity: 'high', via: ['fdir', 'picomatch', 'tinyglobby'] },
} };
const exception = { id: 'GHSA-fc5q-39xc-vjpf', package: 'picomatch', vulnerable_range: '<=4.0.7', review_by: '2027-01-31', reason: 'Reviewed.' };
const today = '2026-11-17';

assert.deepEqual(advisories(report).map(item => item.id), ['GHSA-fc5q-39xc-vjpf'], 'paths to an advisory are not advisories');
assert.equal(compareVersions('4.0.7', '4.0.10'), -1);
assert.equal(compareVersions('4.1.0', '4.0.9'), 1);
assert.equal(insideRange('4.0.7', '<=4.0.7'), true);
assert.equal(insideRange('4.0.8', '<=4.0.7'), false);
assert.equal(insideRange('4.0.7', '<4.0.7'), false);
assert.throws(() => insideRange('4.0.7', '>=1.0.0'), /unsupported vulnerable_range/);

// A reviewed advisory with no fix published passes, and says why.
let verdict = evaluateAudit({ report, exceptions: [exception], latest: { picomatch: '4.0.7' }, today });
assert.deepEqual(verdict.failures, []);
assert.equal(verdict.accepted[0].id, exception.id);

// Without the exception it fails, as `npm audit --audit-level=high` did.
verdict = evaluateAudit({ report, exceptions: [], latest: {}, today });
assert.equal(verdict.failures.length, 1);
assert.match(verdict.failures[0], /GHSA-fc5q-39xc-vjpf \(picomatch, high\)/);

// A moderate advisory does not block; a critical one does.
const moderate = { vulnerabilities: { vite: { via: [{ name: 'vite', title: 'm', url: 'https://github.com/advisories/GHSA-aaaa-bbbb-cccc', severity: 'moderate' }] } } };
assert.deepEqual(evaluateAudit({ report: moderate, exceptions: [], latest: {}, today }).failures, []);
const critical = { vulnerabilities: { x: { via: [{ name: 'x', title: 'c', url: 'https://github.com/advisories/GHSA-cccc-dddd-eeee', severity: 'critical' }] } } };
assert.equal(evaluateAudit({ report: critical, exceptions: [], latest: {}, today }).failures.length, 1);

// The exception lapses: a fixed release is published, npm stops reporting it, or the review date passes.
assert.match(evaluateAudit({ report, exceptions: [exception], latest: { picomatch: '4.0.8' }, today }).failures[0],
  /picomatch 4\.0\.8 is published, outside .* update the lock/);
assert.match(evaluateAudit({ report: { vulnerabilities: {} }, exceptions: [exception], latest: { picomatch: '4.0.8' }, today }).failures[0],
  /no longer reported by npm audit: remove its exception/);
assert.match(evaluateAudit({ report, exceptions: [exception], latest: { picomatch: '4.0.7' }, today: '2027-02-01' }).failures[0],
  /passed its review date 2027-01-31/);

// Every committed exception carries what the review needs.
const committed = JSON.parse(readFileSync(new URL('../audit-exceptions.json', import.meta.url), 'utf8'));
assert.equal(committed.schema, 'coilem.npm_audit_exceptions/v1');
for (const item of committed.exceptions) {
  assert.match(item.id, /^GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}$/);
  assert.ok(item.package && item.reason && item.reviewed && /^\d{4}-\d{2}-\d{2}$/.test(item.review_by), `${item.id} is complete`);
  insideRange('0.0.0', item.vulnerable_range);
}

console.log('dependency audit: reviewed exceptions pass, unreviewed and lapsed ones fail');
