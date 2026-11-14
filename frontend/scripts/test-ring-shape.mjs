import assert from 'node:assert/strict';
import * as THREE from 'three';
import { ringShape } from '../src/public/ringShape.ts';

// A solid disc is a valid end state while a model loads. An empty hole used to
// throw inside Earcut and unmount the workspace. Check actual triangulation.
for (const innerRadius of [0, 3]) {
  const geometry = new THREE.ExtrudeGeometry(ringShape(10, innerRadius), { depth: 1, bevelEnabled: false });
  const positions = geometry.attributes.position;
  assert.ok(positions.count > 0);
  assert.ok(Array.from(positions.array).every(Number.isFinite));
  let area = 0;
  for (let i = 0; i < positions.count; i += 3) {
    if ([0, 1, 2].every(j => Math.abs(positions.getZ(i + j)) < 1e-6)) {
      area += Math.abs((positions.getX(i + 1) - positions.getX(i)) * (positions.getY(i + 2) - positions.getY(i))
        - (positions.getY(i + 1) - positions.getY(i)) * (positions.getX(i + 2) - positions.getX(i))) / 2;
    }
  }
  assert.ok(Math.abs(area / (Math.PI * (100 - innerRadius ** 2)) - 1) < 0.03);
  geometry.dispose();
}
console.log('3D rings: solid discs and annular holes triangulate without losing their area');
