import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const { magnetTemperatureRange, magnetTemperatureView } = await importTypeScriptModule(
  new URL('../src/public/magnetTemperature.ts', import.meta.url),
);

// N42: −0.12 %/°C Br, −0.75 %/°C HcJ (Arnold), used to 120 °C where HcJ falls to a quarter.
assert.deepEqual(magnetTemperatureRange('N42'), [-40, 120]);
assert.equal(magnetTemperatureRange('Ferrite_Y30'), null);

const hot = magnetTemperatureView('N42', 1.315, 100);
assert.equal(hot.available, true);
assert.equal(hot.note, 'Br 1.189 T (−9.6%), HcJ about 382 kA/m at 100 °C. Range -40 to 120 °C.');
assert.match(hot.warning, /rated to 80 °C/);

const cold = magnetTemperatureView('N42', 1.315, 20);
assert.match(cold.note, /^20 °C: the catalogue values/);
assert.equal(cold.warning, null);

assert.equal(magnetTemperatureView('N48SH', 1.39, 120).warning, null, 'SH grades are rated to 150 °C');

const ferrite = magnetTemperatureView('Ferrite_Y30', 0.4, 20);
assert.equal(ferrite.available, false);
assert.match(ferrite.note, /No cited temperature coefficients for Ferrite_Y30/);

console.log('magnet temperature: range, derated Br and HcJ, rating warning pass');
