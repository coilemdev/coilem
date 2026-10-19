import * as THREE from 'three';
import type { PreviewRegion } from './model';
import { previewContours } from './previewContours';

/** Use the solver preview's independent outer/hole loops, never its legacy joined polygon. */
export function extrudePreviewRegion(region: PreviewRegion, depth: number): THREE.ExtrudeGeometry {
  if (!region.loops?.length) throw new Error('Reference preview requires separate boundary contours. Restart the local backend.');
  const [outer, ...holes] = previewContours(region);
  const shape = new THREE.Shape(outer.map(([x, y]) => new THREE.Vector2(x, y)));
  shape.holes = holes.map((loop) => new THREE.Path(loop.map(([x, y]) => new THREE.Vector2(x, y))));
  const geometry = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, steps: 1 });
  geometry.translate(0, 0, -depth / 2);
  return geometry;
}
