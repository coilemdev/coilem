import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

// The Examples menu lists inrunners and outrunners apart, by each example's declared
// layout, so every example must declare one and it must match its bundled design file.
const source = await readFile(new URL('../src/public/exampleDesigns.ts', import.meta.url), 'utf8');
const optionsBlock = source.slice(source.indexOf('export const PUBLIC_EXAMPLE_OPTIONS'), source.indexOf('export type PublicExampleGroup'));
const ids = [...optionsBlock.matchAll(/id: '([^']+)'/g)].map((match) => match[1]);
// Pairs each id with the next layout, so an option without one shifts the pairs and fails below.
const declared = new Map([...optionsBlock.matchAll(/id: '([^']+)'[\s\S]*?layout: '(inner|outer)'/g)].map((match) => [match[1], match[2]]));
assert.deepEqual([...declared.keys()], ids, 'every example declares its rotor layout');

const fileByImport = new Map([...source.matchAll(/import (\w+) from '\.\/examples\/([^']+)\?raw';/g)].map((match) => [match[1], match[2]]));
const filesBlock = source.slice(source.indexOf('const BUNDLED_EXAMPLE_FILES'), source.indexOf('export function createPublicExampleDesign'));
const fileById = new Map([...filesBlock.matchAll(/'([^']+)': (\w+),/g)].map((match) => [match[1], fileByImport.get(match[2])]));

for (const id of ids) {
  if (id === 'spm-8p12s') {
    // The starter motor is the default design, an inrunner.
    assert.equal(declared.get(id), 'inner');
    continue;
  }
  const file = fileById.get(id);
  assert.ok(file, `${id} has a bundled design file`);
  const design = JSON.parse(await readFile(new URL(`../src/public/examples/${file}`, import.meta.url), 'utf8'));
  assert.equal(declared.get(id), design.rotor_layout ?? 'inner', `${id}: declared layout matches ${file}`);
}
assert.ok([...declared.values()].includes('outer') && [...declared.values()].includes('inner'), 'both layouts have examples');

console.log(`example layouts: ok (${ids.length} examples)`);
