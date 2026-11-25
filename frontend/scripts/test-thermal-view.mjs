import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';
const { thermalInputs, thermalCurvePath, THERMAL_STARTER, readThermalValues, changeThermalValue, thermalDesignKey, thermalKey } = await importTypeScriptModule(new URL('../src/public/thermal.ts', import.meta.url));
const values = {ambient_C:'20', housing_h_W_m2K:'10', end_space_h_W_m2K:'10', airgap_h_W_m2K:'20', housing_thickness_mm:'3',
  slot_liner_mm:'.1', contact_m2K_W:'.001', bearing_to_housing_K_W:'2', rotor_to_bearing_K_W:'3', hotspot_allowance_K:'15',
  cooling:'still_air', insulation_class:'F', coefficient_source:'Explicit test assumption'};
assert.throws(() => thermalInputs({}), /Enter/);
assert.throws(() => thermalInputs({...values, housing_h_W_m2K: ''}), /W\/m²K/, 'Units keep their capitals in a message');
assert.equal(thermalInputs(values).airgap_h_W_m2K,20);
assert.equal(thermalInputs(values).slot_k_model,'series_lower_bound');
assert.throws(() => thermalInputs(values,10), /mechanical-loss/);
assert.throws(() => thermalInputs({...values,calibration_multiplier:'2'}), /Calibration needs/);
assert.equal(thermalInputs({...values,mechanical_bearings:'25',mechanical_housing:'50',mechanical_rotor:'25'},10).mechanical_split.rotor,.25);
const path = thermalCurvePath({points:[{speed_rpm:0,status:'experimental',point:{torque_Nm:2}},
  {speed_rpm:1,status:'unavailable',point:null},{speed_rpm:2,status:'experimental',point:{torque_Nm:1}}]},x=>x,y=>y);
assert.equal(path,'M0,2  M2,1','Unavailable speeds split the plotted path');
console.log('thermal view contracts passed');

const starter = readThermalValues(null);
assert.equal(thermalInputs(starter).ambient_C, 25);
assert.equal(thermalInputs(starter).magnet_frequency_limit_Hz, undefined, 'Starter must not invent frequency qualification');
assert.equal(thermalInputs({...starter, magnet_frequency_limit_Hz:'1'}).magnet_frequency_limit_Hz, undefined, 'Legacy browser drafts must not resurrect the frequency gate');
assert.match(thermalInputs(starter).coefficient_source, /illustrative.*not measured/);
assert.throws(() => thermalInputs(starter, 10), /mechanical-loss/, 'Nonzero mechanical heat still needs allocation');
assert.deepEqual(readThermalValues(JSON.stringify({...starter, housing_h_W_m2K: '', ambient_C: '32'})), {...starter, housing_h_W_m2K: '', ambient_C: '32'}, 'Preserve deliberate blanks and edits');
for (const invalid of ['null', '[]', '{', '{"ambient_C":25}']) assert.deepEqual(readThermalValues(invalid), THERMAL_STARTER);
const forced = changeThermalValue(starter, 'cooling', 'forced_air');
assert.equal(forced.housing_h_W_m2K, '');
assert.equal(forced.end_space_h_W_m2K, '');
assert.equal(forced.airgap_h_W_m2K, '');
assert.equal(forced.coefficient_source, '');
assert.equal(forced.housing_thickness_mm, starter.housing_thickness_mm);
assert.throws(() => thermalInputs(forced), /housing heat/);
assert.deepEqual(changeThermalValue(starter, 'cooling', 'still_air'), starter);
assert.equal(thermalDesignKey({stator:{slots:12}, solve_params:{speed:100}}), thermalDesignKey({stator:{slots:12}, solve_params:{speed:200}}));
assert.notEqual(thermalDesignKey({stator:{slots:12}}), thermalDesignKey({stator:{slots:18}}));
{
  // Storage keys stay short however large the design: a design's JSON as a key would fill the browser's storage.
  const large = {topology: 'SPM', stator: {note: 'x'.repeat(50000)}, rotor: {}, winding: {}, materials: {}};
  assert.ok(thermalDesignKey(large).length < 60);
  const run = {solve_metadata: {}, summary: {avg_torque_Nm: 1, samples: Array(5000).fill(1.5)}};
  assert.ok(thermalKey(large, run).length < 60);
  assert.equal(thermalKey(large, run), thermalKey(large, run));
  assert.notEqual(thermalKey(large, run), thermalKey(large, {...run, summary: {avg_torque_Nm: 2}}));
  assert.notEqual(thermalKey(large, run), thermalKey({...large, rotor: {poles: 8}}, run));
  assert.notEqual(thermalKey(large, {solve_metadata: {timestamp: 'a'}, summary: {}}), thermalKey(large, {solve_metadata: {timestamp: 'b'}, summary: {}}));
}
// An aluminium winding sends aluminium's conductor conductivity, which the API requires; copper leaves the default.
assert.equal(thermalInputs(values, 0, 'inner', 'C', 'aluminum').conductor_k_W_mK, 235);
assert.equal(thermalInputs(values, 0, 'inner', 'C', 'copper').conductor_k_W_mK, undefined);

// Availability controls the picture, colour range and margins even for malformed
// or older records that retain a temperature next to an unavailable status.
const { nodeTemperature, thermalRange, thermalColour, thermalMargin, temperatureText, differenceText } = await importTypeScriptModule(new URL('../src/public/thermalVisual.ts', import.meta.url));
const units = await importTypeScriptModule(new URL('../src/public/thermalUnits.ts', import.meta.url));
// A temperature moves its zero with the unit; a difference only changes its step.
assert.equal(units.temperatureIn(100, 'F'), 212);
assert.equal(units.temperatureIn(25, 'K'), 298.15);
assert.equal(units.differenceIn(15, 'F'), 27);
assert.equal(units.differenceIn(15, 'K'), 15);
for (const unit of ['C', 'F', 'K']) {
  assert.ok(Math.abs(units.temperatureFrom(units.temperatureIn(37.5, unit), unit) - 37.5) < 1e-9);
  assert.ok(Math.abs(units.differenceFrom(units.differenceIn(12.5, unit), unit) - 12.5) < 1e-9);
}
assert.deepEqual(units.TEMPERATURE_UNITS.map((unit) => unit.symbol), ['°C', '°F', 'K']);
assert.equal(temperatureText(164.1), '164.1 °C');
assert.equal(temperatureText(100, 'F'), '212 °F');
assert.equal(differenceText(24.12), '24.12 °C');
assert.equal(differenceText(10, 'F'), '18 °F');
const available = {status:'experimental',temperature_C:150,margin_K:-10};
const unavailable = {status:'unavailable',temperature_C:900,margin_K:10};
assert.equal(nodeTemperature(unavailable), null);
assert.deepEqual(thermalRange({winding:available, magnets:unavailable}), [150,150]);
assert.equal(thermalRange({magnets:unavailable}), null);
assert.equal(nodeTemperature({...available,temperature_C:NaN}), null);
assert.equal(thermalMargin(unavailable), 'No margin available');
// A margin is shown in the unit temperatures are shown in: Celsius unless another is chosen, never a mix of °C and K.
assert.equal(thermalMargin(available), '10 °C above limit');
assert.equal(thermalMargin({...available,margin_K:10}), '10 °C below limit');
assert.equal(thermalMargin(available, 'F'), '18 °F above limit');
assert.equal(thermalMargin({...available,margin_K:10}, 'K'), '10 K below limit');
assert.equal(thermalMargin({...available,margin_K:null}), 'No margin available');
assert.equal(thermalMargin({...available,margin_K:0}), 'At recorded limit');
assert.equal(thermalColour(150,[150,150]), 'rgb(238, 185, 82)');
assert.deepEqual(thermalRange({cold:{...available,temperature_C:-10},hot:available}),[-10,150]);

// Mesh-derived geometry: preserve cavities, remove internal element edges, and
// never colour pocket air or shafts as magnets/rotor.
const {thermalCrossSection, thermalNodeForRegion} = await importTypeScriptModule(new URL('../src/public/thermalCrossSection.ts', import.meta.url));
for (const region of ['magnet_pocket_air','magnet_pocket_air_2','flux_barrier','shaft','exterior_air','unknown']) assert.equal(thermalNodeForRegion(region), null);
assert.equal(thermalNodeForRegion('magnet_2'), 'magnets');
assert.equal(thermalNodeForRegion('slot_winding_2_layer1'), 'winding');
const ringMesh = {nodes_mm:[[-2,-2],[2,-2],[2,2],[-2,2],[-1,-1],[1,-1],[1,1],[-1,1]],
  triangles:[[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]], regions:Array(8).fill('rotor_core')};
const section = thermalCrossSection(ringMesh);
assert.equal(section.parts.length,1);
assert.equal(section.parts[0].outlinePath.match(/M/g).length,8,'Keep four outer and four shaft-hole edges, without triangle seams');
assert.equal(section.parts[0].fillPath.match(/Z/g).length,8,'Use all actual mesh triangles, leaving the shaft hole empty');
assert.equal(section.parts[0].node,'rotor');
assert.ok(section.anchors.rotor[0] > 95,'Callout lands on the rotor, outside its shaft hole');
const split = thermalCrossSection({...ringMesh,regions:['magnet','magnet_pocket_air',...Array(6).fill('rotor_core')]});
assert.equal(split.parts.find(p=>p.region==='magnet_pocket_air').node,null);
assert.notEqual(split.parts[0].fillPath,section.parts[0].fillPath,'The picture must follow the supplied geometry');
assert.equal(thermalCrossSection(null),null);
assert.equal(thermalCrossSection({...ringMesh,regions:[]}),null);
assert.equal(thermalCrossSection({...ringMesh,triangles:[[0,1,99]],regions:['magnet']}),null);
assert.equal(thermalCrossSection({...ringMesh,nodes_mm:[[NaN,1]]}),null);

// Setup presentation: every required input has a plain name and an explanation,
// and each section says in one line what it holds and whether it needs attention.
const { THERMAL_FIELDS, THERMAL_FIELD_META, INSULATION_CLASSES, windingLimitC, thermalSectionSummary, thermalProblemSection } = await importTypeScriptModule(new URL('../src/public/thermal.ts', import.meta.url));
for (const [name] of THERMAL_FIELDS) assert.ok(THERMAL_FIELD_META[name]?.help.length > 20, `${name} needs an explanation`);
assert.deepEqual(INSULATION_CLASSES.map((row) => [row.value, row.limit_C]), [['A', 105], ['B', 130], ['F', 155], ['H', 180]]);
assert.equal(windingLimitC(starter), 140, 'Class F less the 15 K starter allowance');
assert.equal(windingLimitC({...starter, hotspot_allowance_K: ''}), null);
assert.equal(windingLimitC({...starter, insulation_class: ''}), null);
assert.equal(thermalSectionSummary('cooling', starter), 'Still air · 25 °C');
assert.equal(thermalSectionSummary('insulation', starter), 'Class F · winding limit 140 °C');
assert.equal(thermalSectionSummary('cooling', starter, 'inner', 'F'), 'Still air · 77 °F');
assert.equal(thermalSectionSummary('insulation', starter, 'inner', 'F'), 'Class F · winding limit 284 °F');
assert.equal(thermalSectionSummary('insulation', starter, 'inner', 'K'), 'Class F · winding limit 413.15 K');
assert.equal(thermalSectionSummary('construction', starter), '3 mm housing · 0.1 mm liner');
assert.equal(thermalSectionSummary('rotor', starter), 'Heat from the stator only');
assert.equal(thermalSectionSummary('rotor', {...starter, extra_rotor_heat_W: '12'}), '12 W added');
assert.equal(thermalSectionSummary('advanced', starter), 'Defaults');
assert.equal(thermalSectionSummary('advanced', {...starter, slot_k_model: 'user'}), 'Edited');
// The boxes show the model's defaults. A default, or an emptied box, is not an edit; another value is.
assert.equal(starter.steel_k_W_mK, '20');
assert.equal(starter.calibration_multiplier, '1');
assert.equal(starter.extra_rotor_heat_W, '0');
assert.equal(starter.extra_rotor_heat_to_magnets_fraction, '0');
assert.equal(thermalSectionSummary('advanced', {...starter, steel_k_W_mK: ''}), 'Defaults');
assert.equal(thermalSectionSummary('advanced', {...starter, steel_k_W_mK: '20.0'}), 'Defaults');
assert.equal(thermalSectionSummary('advanced', {...starter, steel_k_W_mK: '30'}), 'Edited');
assert.equal(thermalSectionSummary('advanced', {...starter, calibration_multiplier: '1.2'}), 'Edited');
{
  const sent = thermalInputs(starter);
  assert.equal(sent.steel_k_W_mK, 20);
  assert.equal(sent.calibration_multiplier, 1);
  assert.equal(sent.calibration_source, undefined, 'a multiplier of 1 is not a calibration');
  assert.equal(sent.extra_rotor_heat_W, 0);
  assert.equal(thermalInputs({...starter, steel_k_W_mK: ''}).steel_k_W_mK, undefined, 'an emptied box leaves the default to the model');
  // Inputs the form no longer offers are neither sent nor kept from an earlier draft.
  const old = {...starter, conductor_k_W_mK: '237', housing_k_W_mK: '50', magnet_k_W_mK: '5', end_winding_exposed_fraction: '0.5'};
  for (const key of ['conductor_k_W_mK', 'housing_k_W_mK', 'magnet_k_W_mK', 'end_winding_exposed_fraction']) {
    assert.equal(thermalInputs(old)[key], undefined);
    assert.equal(key in readThermalValues(JSON.stringify(old)), false);
  }
  // A draft saved before the defaults were shown gets them; a box its owner emptied stays empty.
  const before = Object.fromEntries(Object.entries(starter).filter(([key]) => !['steel_k_W_mK', 'calibration_multiplier', 'extra_rotor_heat_W', 'extra_rotor_heat_to_magnets_fraction'].includes(key)));
  assert.equal(readThermalValues(JSON.stringify(before)).steel_k_W_mK, '20');
  assert.equal(readThermalValues(JSON.stringify({...before, steel_k_W_mK: ''})).steel_k_W_mK, '');
  // The mechanical split is placed only when the run has a mechanical loss.
  const split = {...starter, mechanical_bearings: '25', mechanical_housing: '50', mechanical_rotor: '25'};
  assert.equal(thermalInputs(split).mechanical_split, undefined);
  assert.equal(thermalInputs(split, 10).mechanical_split.housing, 0.5);
}
assert.equal(thermalProblemSection(starter), null);
assert.equal(thermalProblemSection(forced), 'cooling', 'A new cooling type needs its heat-transfer values');
assert.equal(thermalProblemSection({...starter, insulation_class: ''}), 'insulation');
assert.equal(thermalProblemSection({...starter, slot_liner_mm: ''}), 'construction');
assert.equal(thermalProblemSection(starter, 10), 'advanced', 'A mechanical loss needs its split, which sits under Advanced');

// A value the API would refuse is named before it is sent, in the section that holds it.
assert.throws(() => thermalInputs({...starter, extra_rotor_heat_to_magnets_fraction: '2'}), /Share of that heat in the magnets must be between 0 and 1/);
assert.throws(() => thermalInputs({...starter, extra_rotor_heat_W: '-1'}), /cannot be negative/);
assert.throws(() => thermalInputs({...starter, calibration_multiplier: '0'}), /must be above 0/);
assert.throws(() => thermalInputs({...starter, ambient_C: '250'}), /between -273 and 200/);
assert.equal(thermalProblemSection({...starter, extra_rotor_heat_to_magnets_fraction: '2'}), 'rotor');
assert.equal(thermalInputs({...starter, slot_k_W_mK: '0.6'}).slot_k_W_mK, undefined, 'A conductivity left over from "My own value" is not sent');
assert.throws(() => thermalInputs({...starter, slot_k_model: 'user', slot_k_W_mK: '0.6'}), /value and its source/);
assert.equal(thermalInputs({...starter, slot_k_model: 'user', slot_k_W_mK: '0.6', slot_k_source: 'measured'}).slot_k_W_mK, 0.6);

// A request the API refuses lists its fields; the message names them instead of saying only "422".
const { validationErrorMessage } = await importTypeScriptModule(new URL('../src/public/apiErrors.ts', import.meta.url));
const refused = [{type:'less_than_equal', loc:['body','inputs','extra_rotor_heat_to_magnets_fraction'], msg:'Input should be less than or equal to 1', input:2}];
assert.equal(validationErrorMessage(refused), 'The request was not accepted. inputs → extra_rotor_heat_to_magnets_fraction: Input should be less than or equal to 1.');
assert.equal(validationErrorMessage(refused, (path) => path[0] === 'inputs' ? THERMAL_FIELD_META[path[1]].label : null),
  'The request was not accepted. Share of that heat in the magnets: Input should be less than or equal to 1.');
assert.equal(validationErrorMessage([1, 2, 3, 4, 5].map((n) => ({loc:['body', `f${n}`], msg:'bad'}))), 'The request was not accepted. f1: bad; f2: bad; f3: bad; and 2 more.');
for (const other of ['text', {message:'x'}, [], null, [{loc:['body']}]]) assert.equal(validationErrorMessage(other), null);

// An estimate that came back without temperatures gives its reason instead of silence.
const { unavailableEstimateReason } = await importTypeScriptModule(new URL('../src/public/thermal.ts', import.meta.url));
assert.equal(unavailableEstimateReason(null), null);
assert.equal(unavailableEstimateReason({result: {kind: 'steady_state_thermal', status: 'experimental', status_reason: 'ok', nodes: {winding: available}}}), null);
assert.equal(unavailableEstimateReason({result: {kind: 'steady_state_thermal', status: 'unavailable', status_reason: 'Too hot.', nodes: {}}}), 'Too hot.');
assert.equal(unavailableEstimateReason({result: {kind: 'thermally_limited_rating', status: 'experimental', status_reason: 'x', points: []}}), null);

// Outer-rotor motors: the stator sits on a hub, so the estimate needs the mount's
// resistance, and the outside coefficient belongs to the rotor shell.
const { rotorLayoutOf, thermalFieldMeta } = await importTypeScriptModule(new URL('../src/public/thermal.ts', import.meta.url));
assert.equal(rotorLayoutOf({}), 'inner');
assert.equal(rotorLayoutOf({rotor_layout: 'outer'}), 'outer');
assert.equal(thermalInputs(starter).mount_to_ambient_K_W, undefined, 'An inner-rotor request does not carry the mount');
assert.equal(thermalInputs(starter, 0, 'outer').mount_to_ambient_K_W, 10);
assert.throws(() => thermalInputs({...starter, mount_to_ambient_K_W: ''}, 0, 'outer'), /Enter mount to surroundings/);
assert.throws(() => thermalInputs({...starter, mount_to_ambient_K_W: '0'}, 0, 'outer'), /Check mount to surroundings/);
assert.equal(thermalInputs({...starter, mount_to_ambient_K_W: ''}).ambient_C, 25, 'An inner rotor ignores a blank mount value');
const { mount_to_ambient_K_W: _mount, ...olderDraft } = starter;
assert.equal(readThermalValues(JSON.stringify(olderDraft)).mount_to_ambient_K_W, '10', 'A draft saved before the mount input gets its starter value');
assert.equal(readThermalValues(JSON.stringify({...starter, mount_to_ambient_K_W: ''})).mount_to_ambient_K_W, '', 'A value the person cleared stays cleared');
assert.equal(thermalFieldMeta('housing_h_W_m2K').label, 'Housing to surroundings');
assert.equal(thermalFieldMeta('housing_h_W_m2K', 'outer').label, 'Rotor shell to surroundings');
assert.equal(thermalFieldMeta('bearing_to_housing_K_W', 'outer').label, 'Bearings to mount');
assert.equal(thermalFieldMeta('slot_liner_mm', 'outer').label, 'Slot liner thickness', 'Inputs that mean the same keep their name');
assert.equal(thermalSectionSummary('construction', starter, 'outer'), '10 K/W mount · 0.1 mm liner');
assert.equal(thermalProblemSection(starter, 0, 'outer'), null);
assert.equal(thermalProblemSection({...starter, mount_to_ambient_K_W: ''}, 0, 'outer'), 'construction');
assert.equal(thermalProblemSection({...starter, mount_to_ambient_K_W: ''}), null);

// Parts the estimate has but the solved section lacks are sketched as rings, so
// the picture shows what the table lists: hub, bearings and shaft inside an
// outer-rotor stator; a housing and bearings for an inner rotor.
const { schematicThermalParts, ringPath } = await importTypeScriptModule(new URL('../src/public/thermalCrossSection.ts', import.meta.url));
assert.equal(section.scale, 95);
assert.ok(Math.abs(section.innerRadius - Math.hypot(95, 95)) < 1e-6 && Math.abs(section.outerRadius - Math.hypot(190, 190)) < 1e-6);
const extent = {scale: 4, innerRadius: 40, outerRadius: 190};
const outerSketch = schematicThermalParts(extent, {mount: {}, bearings: {}, rotor: {}});
assert.deepEqual(outerSketch.map((part) => [part.key, part.node]), [['mount', 'mount'], ['bearings', 'bearings'], ['shaft', null]]);
assert.equal(outerSketch[0].outer, 40, 'The hub fills the stator bore');
assert.equal(outerSketch[1].outer, outerSketch[0].inner, 'Rings meet without gaps or overlap');
assert.equal(outerSketch[2].outer, outerSketch[1].inner);
const innerSketch = schematicThermalParts(extent, {housing: {}, bearings: {}}, 3);
assert.deepEqual(innerSketch.map((part) => part.key), ['housing', 'bearings', 'shaft']);
assert.equal(innerSketch[0].inner, 190);
assert.equal(innerSketch[0].outer, 202, 'The housing takes its entered thickness at the drawing scale');
assert.equal(schematicThermalParts(extent, {housing: {}, bearings: {}}, 100)[0].outer, 204, 'A thick housing stays inside the picture');
assert.deepEqual(schematicThermalParts({...extent, innerRadius: 0}, {housing: {}, bearings: {}}).map((part) => part.key), ['housing'], 'No shaft hole, no bearing sketch');
assert.deepEqual(schematicThermalParts(extent, {}), []);
assert.equal(ringPath(0, 10).match(/Z/g).length, 1);
assert.equal(ringPath(5, 10).match(/Z/g).length, 2);
const withAir = thermalCrossSection({nodes_mm: [...ringMesh.nodes_mm, [-4, -4], [4, -4], [4, 4]], triangles: [...ringMesh.triangles, [8, 9, 10]], regions: [...Array(8).fill('rotor_core'), 'exterior_air']});
assert.ok(withAir.outerRadius < Math.hypot(190, 190) * 0.6, 'Surrounding air does not set where the housing is drawn');

// A torque curve holds a speed only when neither its search nor its direct solve rejected it. A speed whose
// direct solve could not run comes back from the API unavailable, with its map point kept for the record.
const { isHeldSpeed, readRatingRow, directSolveFailed } = await importTypeScriptModule(new URL('../src/public/thermal.ts', import.meta.url));
// A direct solve that ran to its comparison says so at the start of its verification reason, pass or fail.
const compared = (failures) => `Direct limiting-point comparison: ${failures}`;
const mapPoint = (status, verification, reason = compared(verification === 'PASS' ? 'within registered bands' : 'iron loss')) =>
  ({status, status_reason: 'Coupled estimate.', torque_Nm: 9.1, winding_temperature_C: 80, magnet_temperature_C: 70, verification_status: verification, verification_reason: reason});
const curveRows = [
  {speed_rpm: 0, status: 'experimental', status_reason: 'Coupled estimate.', point: mapPoint('experimental', 'PASS')},
  {speed_rpm: 500, status: 'experimental', status_reason: 'Coupled estimate. The direct solve differs from the maps beyond the registered band in: iron loss.', point: mapPoint('experimental', 'FAIL')},
  {speed_rpm: 1000, status: 'unavailable', status_reason: 'A direct solve at this point puts the magnets past the temperature limit, so the value read from the maps is not reported.', point: mapPoint('unavailable', 'FAIL')},
  {speed_rpm: 1500, status: 'unavailable', status_reason: 'A direct solve at this point could not run (Magneto2D stopped), so the value read from the maps is not reported.', point: mapPoint('unavailable', 'FAIL')},
  {speed_rpm: 2000, status: 'unavailable', status_reason: 'voltage', point: null},
  // A point its direct solve rejected is not held even if the row around it says otherwise.
  {speed_rpm: 2500, status: 'experimental', status_reason: 'x', point: mapPoint('unavailable', 'FAIL')},
];
assert.deepEqual(curveRows.filter(isHeldSpeed).map((row) => row.speed_rpm), [0, 500], 'Only confirmed speeds are counted as held');
assert.equal(thermalCurvePath({points: curveRows}, (x) => x, (y) => y), 'M0,9.1 L500,9.1    ', 'Rejected speeds leave the plotted curve');
for (const row of curveRows) assert.equal(readRatingRow(row), row, 'A row saved by this build reads as it was saved');

// Earlier builds saved a speed whose direct solve raised as experimental: the exception became the verification
// reason, a sentence was added to the status reason, and the speed counted as held. It reads as a new run saves it.
const raisedSentences = [' Direct verification failed.', ' The direct solve of this point failed.'];
const savedEarlier = (sentence, verificationReason) => {
  const point = {...mapPoint('experimental', 'FAIL', verificationReason), status_reason: `Coupled estimate.${sentence}`};
  return {speed_rpm: 1000, status: 'experimental', status_reason: point.status_reason, limiting_constraint: 'voltage', point};
};
for (const sentence of raisedSentences) {
  const saved = savedEarlier(sentence, 'Magneto2D stopped');
  const before = JSON.stringify(saved);
  assert.ok(directSolveFailed(saved.point) && !isHeldSpeed(saved), 'An older speed whose direct solve raised is not held');
  const read = readRatingRow(saved);
  assert.equal(JSON.stringify(saved), before, 'Reading a saved row does not change it');
  assert.equal(read.status, 'unavailable');
  assert.equal(read.point.status, 'unavailable');
  // The reason and the verification text new runs give, so the table labels it as it labels a new run's speed.
  assert.equal(read.status_reason, curveRows[3].status_reason);
  assert.equal(read.point.status_reason, read.status_reason);
  assert.equal(read.point.verification_reason, 'Direct limiting-point solve failed: Magneto2D stopped');
  assert.equal(read.point.torque_Nm, 9.1, 'The map point stays on record');
  assert.equal(readRatingRow(read), read);
}
assert.match(readRatingRow(savedEarlier(raisedSentences[1], '')).status_reason, /could not run \(no reason was saved\)/);
// A completed direct solve that only missed a band, as the same builds saved it, keeps its result.
for (const sentence of [' Direct verification failed: iron loss.', ' The direct solve differs from the maps beyond the registered band in: iron loss.']) {
  const saved = savedEarlier(sentence, compared('iron loss'));
  assert.ok(!directSolveFailed(saved.point) && isHeldSpeed(saved) && readRatingRow(saved) === saved);
}
const withOlder = [...curveRows.slice(0, 2), savedEarlier(raisedSentences[1], 'Magneto2D stopped')];
assert.deepEqual(withOlder.filter(isHeldSpeed).map((row) => row.speed_rpm), [0, 500], 'The count leaves the older failure out');
assert.equal(thermalCurvePath({points: withOlder}, (x) => x, (y) => y), 'M0,9.1 L500,9.1 ', 'And so does the plotted curve');

// A saved estimate belongs to the thermal inputs it recorded. Both sides are compared as the API records
// them, with its defaults filled in, so only an edit that changes the calculation marks it as from the previous inputs.
const { sameThermalInputs, recordedThermalInputs, THERMAL_REQUEST_DEFAULTS } = await importTypeScriptModule(new URL('../src/public/thermal.ts', import.meta.url));
const request = thermalInputs(starter);
const recorded = JSON.parse(JSON.stringify({...THERMAL_REQUEST_DEFAULTS, ...request}));
assert.ok(sameThermalInputs(request, recorded), 'The inputs an estimate was run with match its record');
assert.ok(sameThermalInputs(thermalInputs({...starter, ambient_C: '25.0'}), recorded), 'Retyping the same value is not a change');
assert.ok(sameThermalInputs(thermalInputs({...starter, ambient_C: '25.000000000000004'}), recorded), 'A unit round trip is not a change');
assert.ok(sameThermalInputs(thermalInputs({...starter, steel_k_W_mK: ''}), recorded), 'An emptied box takes the default it already had');
assert.ok(sameThermalInputs(request, {...recorded, a_later_api_input: 3}), 'An input the app does not know is not compared');
assert.ok(!sameThermalInputs(thermalInputs({...starter, ambient_C: '40'}), recorded), 'A new ambient temperature is a change');
assert.ok(!sameThermalInputs(thermalInputs({...starter, housing_h_W_m2K: '12'}), recorded), 'New cooling is a change');
assert.ok(!sameThermalInputs(thermalInputs({...starter, insulation_class: 'H'}), recorded));
assert.ok(!sameThermalInputs(thermalInputs({...starter, steel_k_W_mK: ''}), {...recorded, steel_k_W_mK: 30}), 'An emptied box that takes another default is a change');
assert.ok(!sameThermalInputs(request, {...recorded, conductor_k_W_mK: 300}), 'An input the form no longer offers still counts when the record differs from its default');
const splitValues = {...starter, mechanical_bearings: '25', mechanical_housing: '50', mechanical_rotor: '25'};
const recordedSplit = JSON.parse(JSON.stringify({...THERMAL_REQUEST_DEFAULTS, ...thermalInputs(splitValues, 10)}));
assert.ok(sameThermalInputs(thermalInputs(splitValues, 10), recordedSplit));
assert.ok(!sameThermalInputs(thermalInputs({...splitValues, mechanical_bearings: '50', mechanical_housing: '25'}, 10), recordedSplit), 'A new mechanical split is a change');
assert.ok(sameThermalInputs(request, null), 'A record without inputs is not reported as changed');
assert.deepEqual(recordedThermalInputs({inputs: {ambient_C: 1}, result: {inputs: {ambient_C: 2}}}), {ambient_C: 1});
assert.deepEqual(recordedThermalInputs({result: {inputs: {ambient_C: 2}}}), {ambient_C: 2});
assert.equal(recordedThermalInputs(null), null);
console.log('thermal held-speed and stale-input contracts passed');
