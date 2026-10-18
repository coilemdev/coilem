import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The Solve tab's waveform plots move the field view, and show where it is.
const { createFieldPositionLink } = await importTypeScriptModule(
  new URL('../src/public/fieldPositionLink.ts', import.meta.url),
);

const link = createFieldPositionLink();
assert.equal(link.getPlayhead(), null, 'no field shown yet');

// The plots hear each new field position once.
let heard = 0;
const stopListening = link.subscribePlayhead(() => { heard += 1; });
link.setPlayhead(15);
link.setPlayhead(15);
link.setPlayhead(22.5);
assert.equal(link.getPlayhead(), 22.5);
assert.equal(heard, 2, 'an unchanged position notifies nobody');
stopListening();
link.setPlayhead(30);
assert.equal(heard, 2, 'an unsubscribed plot hears nothing');

// A hovered or clicked angle reaches the field view; nothing else does.
const requested = [];
const stopRequests = link.subscribeRequests((angle) => requested.push(angle));
link.requestAngle(150);
link.requestAngle(Number.NaN);
stopRequests();
link.requestAngle(200);
assert.deepEqual(requested, [150]);

console.log('field position link checks passed');
