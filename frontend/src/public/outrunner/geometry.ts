import type { GeometryPreview, PreviewRegion } from '../model';
import { PUBLIC_PHASE_COLORS } from '../motorPalette';
import type { OutrunnerProject } from './project';

export interface ReferenceRegion {
  id: string; kind: string; loops: number[][][]; phase: 'A' | 'B' | 'C' | null; signed_turns: number; material: string;
}
export interface ReferencePreview { regions: ReferenceRegion[] }
interface SourceLabel { theta_deg: number; magnetization_angle_deg_raw: number }

/** Feed the existing motor renderers exact independent reference contours. */
export function referenceGeometry(preview: ReferencePreview, project: OutrunnerProject): GeometryPreview {
  const labels = project.fixture_data.labels as SourceLabel[];
  let magnetIndex = 0, slotIndex = 0;
  const regions: PreviewRegion[] = preview.regions.map((region) => {
    let type = region.kind === 'StatorYoke' ? 'stator_yoke' : 'rotor_core';
    let fill: string | undefined;
    if (region.kind === 'Magnet') {
      const label = labels[Number(region.id.replace('source_block_', ''))];
      // The gap-facing surface normal points INWARD for the outer magnets.
      const north = Math.cos((label.magnetization_angle_deg_raw-label.theta_deg)*Math.PI/180) < 0;
      type = `magnet_${north ? 'n' : 's'}_${magnetIndex++}`;
    } else if (region.kind === 'SlotWinding' && region.phase) {
      type = `slot_${++slotIndex} (${region.phase}${region.signed_turns > 0 ? '+' : '-'})`;
      fill = PUBLIC_PHASE_COLORS[region.phase];
    }
    const loops = region.loops as Array<Array<[number, number]>>;
    return { region_type: type, points: loops[0], loops, fill, label: `${region.material}${region.phase ? ` · ${region.phase} · ${region.signed_turns} turns` : ''}` };
  });
  // A visual clearance cue for the main physical gap; numerical meshing still
  // uses the full connected air region from the exact shared geometry IR.
  const circle = (radius: number) => Array.from({ length: 360 }, (_, i): [number, number] => [radius*Math.cos(i*Math.PI/180), radius*Math.sin(i*Math.PI/180)]);
  const outer = circle(13), inner = circle(12.8).reverse();
  regions.push({ region_type: 'airgap', points: [...outer, ...inner], loops: [outer, inner], label: 'Main air gap · 0.2 mm' });
  return { regions, metadata: { topology: 'SPM', radial_layout: 'outer_rotor', outer_radius_mm: 15.39,
    stator_od_mm: 25.6, stack_length_mm: 10, pole_count: 14, slot_count: 12, fixture_id: project.fixture_id },
    validation_errors: [], generation_time_ms: 0 };
}
