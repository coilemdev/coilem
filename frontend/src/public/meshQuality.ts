import type { MeshPreview } from './model';

export type PublicMeshQualityBand = 'good' | 'acceptable' | 'marginal' | 'failing';

export interface PublicMeshQualitySummary {
  qualities: number[];
  minimum: number;
  minimumElementIndex: number | null;
  threshold: number;
  weakElementIndices: number[];
  counts: Record<PublicMeshQualityBand, number>;
}

export const PUBLIC_MESH_ACCEPTABLE_QUALITY = 0.3;
export const PUBLIC_MESH_MARGINAL_QUALITY = 0.1;
export const PUBLIC_MESH_FALLBACK_THRESHOLD = 0.01;

function finitePositive(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/**
 * Normalized equilateral-triangle quality in [0, 1]. This intentionally mirrors
 * backend.gmsh_solver._triangle_quality so the inspection view and solve gate
 * speak the same engineering language.
 */
export function publicTriangleQuality(
  nodes: MeshPreview['nodes_mm'],
  triangle: MeshPreview['triangles'][number],
): number {
  const [aIndex, bIndex, cIndex] = triangle;
  const a = nodes[aIndex];
  const b = nodes[bIndex];
  const c = nodes[cIndex];
  if (!a || !b || !c) return 0;
  const ab = Math.hypot(a[0] - b[0], a[1] - b[1]);
  const bc = Math.hypot(b[0] - c[0], b[1] - c[1]);
  const ca = Math.hypot(c[0] - a[0], c[1] - a[1]);
  const doubledArea = Math.abs(
    a[0] * (b[1] - c[1])
      + b[0] * (c[1] - a[1])
      + c[0] * (a[1] - b[1]),
  );
  const denominator = ab * ab + bc * bc + ca * ca;
  if (denominator <= 1e-18) return 0;
  return Math.max(0, Math.min(1, (2 * Math.sqrt(3) * doubledArea) / denominator));
}

export function publicMeshQualityBand(
  quality: number,
  threshold: number,
): PublicMeshQualityBand {
  if (quality < threshold) return 'failing';
  if (quality < PUBLIC_MESH_MARGINAL_QUALITY) return 'marginal';
  if (quality < PUBLIC_MESH_ACCEPTABLE_QUALITY) return 'acceptable';
  return 'good';
}

export function summarizePublicMeshQuality(mesh: MeshPreview | null): PublicMeshQualitySummary {
  const threshold = finitePositive(
    mesh?.mesh_qa.min_quality_threshold,
    PUBLIC_MESH_FALLBACK_THRESHOLD,
  );
  const qualities = mesh?.triangles.map((triangle) => publicTriangleQuality(mesh.nodes_mm, triangle)) ?? [];
  const counts: Record<PublicMeshQualityBand, number> = {
    good: 0,
    acceptable: 0,
    marginal: 0,
    failing: 0,
  };
  const weakElementIndices: number[] = [];
  let minimum = qualities.length > 0 ? Number.POSITIVE_INFINITY : 0;
  let minimumElementIndex: number | null = null;
  qualities.forEach((quality, index) => {
    const band = publicMeshQualityBand(quality, threshold);
    counts[band] += 1;
    if (band === 'marginal' || band === 'failing') weakElementIndices.push(index);
    if (quality < minimum) {
      minimum = quality;
      minimumElementIndex = index;
    }
  });
  return {
    qualities,
    minimum: Number.isFinite(minimum) ? minimum : 0,
    minimumElementIndex,
    threshold,
    weakElementIndices,
    counts,
  };
}
