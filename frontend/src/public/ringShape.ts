import * as THREE from 'three';

export function ringShape(outerRadius: number, innerRadius: number): THREE.Shape {
  const shape = new THREE.Shape();
  shape.absarc(0, 0, outerRadius, 0, Math.PI * 2, false);
  // A zero-radius path collapses to an empty contour and crashes Earcut.
  if (innerRadius > 0) {
    const hole = new THREE.Path();
    hole.absarc(0, 0, innerRadius, 0, Math.PI * 2, true);
    shape.holes.push(hole);
  }
  return shape;
}
