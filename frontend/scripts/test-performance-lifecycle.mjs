import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { finishRuntime, writeReceipt } = await importTypeScriptModule(new URL('../tests/performance-lifecycle.ts', import.meta.url));
const runtime = mkdtempSync(join(tmpdir(), 'acceptance-lifecycle-'));
try {
  const receipt = join(runtime, 'failure.json');
  writeReceipt(receipt, { status: 'timedOut', elapsed_s: 123 });
  assert.deepEqual(JSON.parse(readFileSync(receipt)), { status: 'timedOut', elapsed_s: 123 });
  assert.equal(finishRuntime(runtime, undefined, true), false, 'caller-owned directories are never removed');
  assert.equal(finishRuntime(runtime, runtime, true), false, 'an ownership marker is required');
  writeFileSync(join(runtime, '.acceptance-owned'), runtime);
  assert.equal(finishRuntime(runtime, runtime, false), false, 'failed attempts retain caches');
  assert.equal(finishRuntime(runtime, `${runtime}-other`, true), false, 'ownership must match the exact directory');
  assert.ok(existsSync(receipt));
  assert.equal(finishRuntime(runtime, runtime, true), true, 'successful owned runtimes are removed');
  assert.equal(existsSync(runtime), false);
} finally { rmSync(runtime, { recursive: true, force: true }); }
console.log('Performance runtime ownership and failure retention passed');

// Exercise the actual reporter path for a timeout, including its last attempt
// phase and wall duration. These diagnostics must survive runtime cleanup.
const { default: AcceptanceReporter } = await importTypeScriptModule(new URL('../tests/performance-reporter.ts', import.meta.url));
const { mkdirSync } = await import('node:fs');
const work = mkdtempSync(join(tmpdir(), 'acceptance-reporter-'));
const originalCwd = process.cwd();
const originalRuntime = process.env.COILEM_ACCEPTANCE_RUNTIME;
const originalOwned = process.env.COILEM_ACCEPTANCE_OWNED_RUNTIME;
const originalRecheck = process.env.COILEM_ACCEPTANCE_RECHECK_DIR;
let reporter;
try {
  process.chdir(work);
  const output = join(work, 'test-results/performance-evidence/spm-8p12s');
  mkdirSync(output, { recursive: true });
  const owned = join(work, 'runtime');
  mkdirSync(owned);
  writeFileSync(join(owned, '.acceptance-owned'), owned);
  process.env.COILEM_ACCEPTANCE_RUNTIME = owned;
  process.env.COILEM_ACCEPTANCE_OWNED_RUNTIME = owned;
  delete process.env.COILEM_ACCEPTANCE_RECHECK_DIR;
  writeReceipt(join(output, 'attempt.json'), { phase: 'request_started', started_utc: '2026-11-05T12:00:00Z' });
  reporter = new AcceptanceReporter();
  reporter.onBegin();
  reporter.onTestEnd({ title: 'Standard map and Performance view: spm-8p12s' }, {
    status: 'timedOut', duration: 123456, errors: [{ message: 'request exceeded its budget' }],
  });
  reporter.onEnd({ status: 'timedout' });
  await reporter.onExit();
  const diagnostic = JSON.parse(readFileSync(join(output, 'attempt-result.json')));
  assert.equal(diagnostic.status, 'timedOut');
  assert.equal(diagnostic.duration_s, 123.456);
  assert.equal(diagnostic.attempt.phase, 'request_started');
  assert.deepEqual(diagnostic.errors, ['request exceeded its budget']);
  assert.ok(existsSync(owned), 'failed owned runtime remains available');
  const summary = JSON.parse(readFileSync(join(work, 'test-results/performance-run.json')));
  assert.equal(summary.status, 'timedout');
  assert.equal(summary.owned_runtime_removed, false);
} finally {
  reporter?.onEnd({ status: 'failed' }); // Clear heartbeat if an assertion failed.
  process.chdir(originalCwd);
  for (const [key, value] of Object.entries({
    COILEM_ACCEPTANCE_RUNTIME: originalRuntime, COILEM_ACCEPTANCE_OWNED_RUNTIME: originalOwned,
    COILEM_ACCEPTANCE_RECHECK_DIR: originalRecheck,
  })) {
    if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
  rmSync(work, { recursive: true, force: true });
}
console.log('Performance timeout reporter retained phase, duration, error and runtime');
