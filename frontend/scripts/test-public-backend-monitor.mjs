import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(
  new URL('../src/public/backendMonitor.ts', import.meta.url),
  'utf8',
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
});
const monitor = await import(
  `data:text/javascript;base64,${Buffer.from(compiled.outputText).toString('base64')}`
);

const flushPromises = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

{
  let probeCount = 0;
  const onlinePayloads = [];
  const offlineErrors = [];
  const scheduled = new Map();
  const cancelled = [];
  let reconnectCount = 0;
  let nextTimerId = 1;

  const stop = monitor.startPublicBackendMonitor({
    probe: async () => {
      probeCount += 1;
      if (probeCount === 1) throw new TypeError('backend not started');
      return { elmer: 'ready' };
    },
    onOnline: (payload) => onlinePayloads.push(payload),
    onOffline: (error) => offlineErrors.push(error),
    onReconnect: () => { reconnectCount += 1; },
    intervalMs: 25,
    schedule: (callback, delayMs) => {
      assert.equal(delayMs, 25);
      const timerId = nextTimerId;
      nextTimerId += 1;
      scheduled.set(timerId, callback);
      return timerId;
    },
    cancel: (timerId) => {
      cancelled.push(timerId);
      scheduled.delete(timerId);
    },
  });

  await flushPromises();
  assert.equal(offlineErrors.length, 1, 'initial offline probe must be reported');
  assert.equal(onlinePayloads.length, 0);
  assert.equal(scheduled.size, 1, 'an offline probe must schedule a retry');

  const [retryTimerId, retry] = scheduled.entries().next().value;
  scheduled.delete(retryTimerId);
  retry();
  await flushPromises();

  assert.deepEqual(onlinePayloads, [{ elmer: 'ready' }]);
  assert.equal(reconnectCount, 1, 'offline startup must trigger recovery when the backend appears');
  assert.equal(scheduled.size, 1, 'an online probe must keep monitoring reconnects');

  const [healthyTimerId, healthyPoll] = scheduled.entries().next().value;
  scheduled.delete(healthyTimerId);
  healthyPoll();
  await flushPromises();
  assert.equal(reconnectCount, 1, 'healthy polls must not repeatedly refresh the user draft');

  const activeTimerId = scheduled.keys().next().value;
  stop();
  assert.deepEqual(cancelled, [activeTimerId]);
  assert.equal(scheduled.size, 0);
}

{
  let resolveProbe;
  const probe = new Promise((resolve) => { resolveProbe = resolve; });
  let onlineCount = 0;
  let scheduledCount = 0;

  const stop = monitor.startPublicBackendMonitor({
    probe: () => probe,
    onOnline: () => { onlineCount += 1; },
    onOffline: () => assert.fail('stopped probe must not report offline'),
    onReconnect: () => assert.fail('stopped probe must not trigger recovery'),
    schedule: () => {
      scheduledCount += 1;
      return 1;
    },
    cancel: () => {},
  });
  stop();
  resolveProbe({ elmer: 'ready' });
  await flushPromises();

  assert.equal(onlineCount, 0, 'cleanup must suppress an in-flight probe result');
  assert.equal(scheduledCount, 0, 'cleanup must not leave a retry timer');
}

{
  let nextPoll;
  let offline = false;
  let reconnects = 0;
  const stop = monitor.startPublicBackendMonitor({
    probe: async () => { if (offline) throw new TypeError('disconnected'); return {}; },
    onOnline: () => {},
    onOffline: () => {},
    onReconnect: () => { reconnects += 1; },
    schedule: (callback) => { nextPoll = callback; return 1; },
    cancel: () => {},
  });
  await flushPromises();
  assert.equal(reconnects, 0, 'initial healthy startup is not a reconnect');
  for (let cycle = 1; cycle <= 2; cycle += 1) {
    offline = true;
    nextPoll();
    await flushPromises();
    nextPoll();
    await flushPromises();
    offline = false;
    nextPoll();
    await flushPromises();
    assert.equal(reconnects, cycle, 'each outage should trigger exactly one recovery');
  }
  stop();
}

assert.equal(monitor.PUBLIC_BACKEND_POLL_INTERVAL_MS, 3_000);
console.log('public backend reconnect monitor checks passed');
