import type { PublicRunListRecord } from './api';
import { COMPARISON_METRICS, actualMeshProvenance, actualPositionsProvenance, actualTorqueProvenance, excitationProvenance } from './comparisonMetrics';
import { compareRunDq } from './dqComparison';
import { comparisonEnvelope, ENVELOPE_METRICS } from './envelopeComparison';
import { compareMultipleLosses, compareMultipleTiming } from './multiRunComparison';
import type { ComparisonFields, ComparisonResult } from './runComparison';
import { multipleInputChanges, type ComparisonInputs } from './runInputChanges';

type Value = string | number | null;
interface Cell { value: Value; missing?: string; status?: string; reason?: string; partial?: boolean }
export interface ComparisonCsvRun {
  id: string;
  label: string;
  record: PublicRunListRecord;
  result: ComparisonResult;
  inputs?: ComparisonInputs | null;
  fields?: ComparisonFields | null;
}
interface RowOptions {
  group?: string; unit?: string; deltaUnit?: string; noDelta?: boolean; comparable?: boolean[];
  notes?: Array<string | null>; coordinate?: number; coordinateUnit?: string; occurrence?: number;
  /** Baselines at or below this magnitude give no percentage change (see compareRunDq). */
  percentFloor?: number;
}
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const numeric = (value: unknown, missing = 'Not recorded'): Cell => ({ value: finite(value) ? value : null, missing });
const text = (value: string | number | null | undefined): Cell => ({ value: value ?? null, missing: 'Not recorded' });

/** Quote RFC 4180 text and keep spreadsheet formula-like text inert. Numbers remain numbers. */
function csvCell(value: Value): string {
  if (value === null || (typeof value === 'number' && !finite(value))) return '';
  if (typeof value === 'number') return String(value);
  const safe = /^[\s\uFEFF]*[=+\-@]/.test(value) || /^[\t\r\n]/.test(value) ? `'${value}` : value;
  return `"${safe.replace(/"/g, '""')}"`;
}

/** One fixed-width CSV, with baseline-first run columns and the same pairwise comparison rules as the UI. */
export function comparisonCsv(runs: ComparisonCsvRun[]): string {
  if (runs.length < 2 || runs.length > 6) throw new Error('Choose two to six completed runs before exporting.');
  if (new Set(runs.map(run => run.id)).size !== runs.length || new Set(runs.map(run => `${run.record.project_slug}/${run.record.run_id}`)).size !== runs.length
    || runs.some(run => run.record.status !== 'complete')) throw new Error('Only distinct completed runs can be exported.');
  const rows: Value[][] = [[
    'Section', 'Group', 'Metric', 'Record', 'Unit', 'Delta unit', 'Coordinate', 'Coordinate unit', 'Occurrence',
    ...runs.map(run => run.label), ...runs.slice(1).map(run => `Δ ${run.label} − ${runs[0].label}`),
    ...runs.slice(1).map(run => `% change ${run.label} vs ${runs[0].label}`),
  ]];
  const add = (section: string, metric: string, cells: Cell[], options: RowOptions = {}) => {
    const prefix = (record: string): Value[] => [section, options.group ?? '', metric, record, options.unit ?? '', options.deltaUnit ?? options.unit ?? '',
      options.coordinate ?? null, options.coordinateUnit ?? '', options.occurrence ?? null];
    const comparable = cells.map((cell, index) => !options.noDelta && finite(cells[0].value) && finite(cell.value) && (options.comparable?.[index] ?? true));
    const absolute = cells.slice(1).map((cell, index) => comparable[index + 1] ? (cell.value as number) - (cells[0].value as number) : null);
    const percent = cells.slice(1).map((cell, index) => {
      if (!comparable[index + 1]) return null;
      const baseline = cells[0].value as number, difference = (cell.value as number) - baseline;
      return Math.abs(baseline) <= Math.max(options.percentFloor ?? 0, 1e-12) ? Math.abs(difference) <= 1e-12 ? 0 : null : difference / Math.abs(baseline) * 100;
    });
    const secondary = (record: string, values: Value[]) => rows.push([...prefix(record), ...values, ...runs.slice(1).flatMap(() => [null, null])]);
    rows.push([...prefix('value'), ...cells.map(cell => cell.value ?? cell.missing ?? 'Not recorded'), ...absolute, ...percent]);
    if (cells.some(cell => cell.value === null)) secondary('availability', cells.map(cell => cell.value === null ? cell.missing ?? 'Not recorded' : 'Available'));
    if (cells.some(cell => cell.status)) secondary('status', cells.map(cell => cell.status || 'Not recorded'));
    if (cells.some(cell => cell.reason)) secondary('reason', cells.map(cell => cell.reason || ''));
    if (cells.some(cell => cell.partial)) secondary('basis', cells.map(cell => cell.value === null ? cell.missing || 'Not recorded' : cell.partial ? 'Partial: excludes unavailable iron loss' : 'Complete'));
    const notes = cells.map((cell, index) => options.notes?.[index]
      || (index > 0 && comparable[index] && percent[index - 1] === null ? 'Percentage change is undefined for a zero or near-zero baseline.' : ''));
    if (notes.some(Boolean)) secondary('comparison note', notes);
  };
  const meta = (metric: string, values: Array<string | number | null | undefined>, group = '') => add('Run details', metric, values.map(text), { noDelta: true, group });
  meta('Export schema', runs.map(() => 'coilem.compare.csv.v1'));
  meta('Role', runs.map((_, index) => index === 0 ? 'Pinned baseline' : 'Candidate'));
  meta('Design', runs.map(run => run.record.project_name || run.record.project_slug));
  meta('Project slug', runs.map(run => run.record.project_slug));
  meta('Run ID', runs.map(run => run.record.run_id));
  meta('Completed (recorded timestamp)', runs.map(run => run.record.completed_at));
  meta('Setup name', runs.map(run => run.inputs?.run_setup?.name ?? run.result.solve_metadata.run_setup?.name ?? run.record.run_setup?.name));
  meta('Setup ID', runs.map(run => run.inputs?.run_setup?.id ?? run.result.solve_metadata.run_setup?.id ?? run.record.run_setup?.id));
  meta('Setup version', runs.map(run => run.inputs?.run_setup?.version ?? run.result.solve_metadata.run_setup?.version ?? run.record.run_setup?.version));
  meta('Solver version', runs.map(run => run.result.solve_metadata.solver_name || run.record.solver_name));
  meta('Physics contract', runs.map(run => run.result.solve_metadata.physics_contract_version));
  meta('Actual mesh', runs.map(run => actualMeshProvenance(run.result)));
  meta('Rotor positions', runs.map(run => actualPositionsProvenance(run.result)));
  meta('Torque extraction', runs.map(run => actualTorqueProvenance(run.result)));
  meta('Excitation identity', runs.map(run => excitationProvenance(run.result)));
  meta('Input snapshot', runs.map(run => run.inputs?.config ? 'Recorded' : 'Not recorded'));
  const inputChanges = multipleInputChanges(runs.map(run => run.inputs));
  if (!inputChanges.length) add('What changed?', 'Recorded input differences', runs.map(() => ({ value: runs.every(run => run.inputs?.config) ? 'No differences in the recorded inputs' : 'No recorded inputs available to compare' })), { noDelta: true });
  for (const change of inputChanges) {
    add('What changed?', change.label, change.values.map(value => ({ value })), { group: change.group, noDelta: true });
  }
  const results = runs.map(run => run.result);
  for (const metric of COMPARISON_METRICS.filter(metric => !metric.optional || results.some(result => finite(metric.value(result))))) {
    add('Results comparison', metric.label, results.map(result => {
      const cell = numeric(metric.value(result), 'Unavailable');
      if (metric.label.startsWith('Cogging')) Object.assign(cell, { status: result.summary.cogging?.status ?? undefined, reason: result.summary.cogging?.status_reason ?? undefined });
      return cell;
    }), { unit: metric.unit, deltaUnit: metric.deltaUnit });
  }
  const dq = compareRunDq(results);
  add('Inductance & d/q', 'D-axis reference', dq.references.map(value => ({ value })), { noDelta: true });
  for (const row of dq.rows) add('Inductance & d/q', row.label, row.cells.map(cell => ({ ...cell, status: cell.status?.status, reason: cell.reason || cell.status?.reason })), {
    unit: row.unit, comparable: row.comparable, percentFloor: row.percentFloor, notes: dq.notes.map((note, index) => row.frameDependent || !row.comparable[index] ? note : null),
  });
  const losses = compareMultipleLosses(results);
  if (!losses.length) add('Losses & efficiency', 'Analysis', runs.map(() => ({ value: null, missing: 'Not recorded' })), { noDelta: true });
  for (const row of losses) add('Losses & efficiency', row.label, row.cells, { unit: row.unit, deltaUnit: row.unit === '%' ? 'pp' : row.unit, comparable: row.comparable,
    notes: row.cells.map((cell, index) => index > 0 && cell.value !== null && row.cells[0].value !== null && !row.comparable[index] ? row.basisNotes[index] ?? 'Deltas require the same loss basis as the pinned baseline.' : null) });
  for (const row of compareMultipleTiming(results).rows) add('Solve time breakdown', row.label, row.values.map(value => numeric(value)), { group: row.group, unit: row.unit });
  const envelopes = results.map(comparisonEnvelope);
  for (const limit of ['peak', 'continuous'] as const) {
    const group = limit === 'peak' ? 'Peak' : 'Continuous';
    const curves = envelopes.map(item => item.curves.find(curve => curve.limit === limit));
    add('Torque–speed envelopes', 'Envelope status', envelopes.map(item => ({ value: item.status?.status ?? item.missing, reason: item.reason || item.status?.reason })), { group, noDelta: true });
    add('Torque–speed envelopes', 'Map grid / control', envelopes.map(item => ({ value: item.settings ? `${item.settings.preset} · ${item.settings.control}` : null })), { group, noDelta: true });
    for (const metric of ENVELOPE_METRICS) add('Torque–speed envelopes', metric.label, envelopes.map((item, index) => {
      const raw = item.envelope && item.status?.status !== 'unavailable' ? metric.value(item.envelope, curves[index]) : null;
      return { ...numeric(raw, item.envelope ? metric.label === 'Continuous current limit' && item.envelope.limits?.continuous_current_A === null ? 'Not set' : 'Unavailable' : item.missing), reason: item.reason || undefined };
    }), { group, unit: metric.unit });
  }

  interface Samples { coordinates: number[]; values: Array<number | string>; missing?: string; status?: string; reason?: string }
  const sampleRows = (section: string, metric: string, unit: string, sources: Samples[], coordinateUnit: string, group = '') => {
    const indexed = sources.map(source => {
      const occurrences = new Map<number, number>();
      const samples = new Map<string, { coordinate: number; occurrence: number; index: number; value: Value }>();
      if (!source.values.length) return samples;
      source.coordinates.forEach((coordinate, index) => {
        if (!finite(coordinate)) return;
        const occurrence = occurrences.get(coordinate) ?? 0;
        occurrences.set(coordinate, occurrence + 1);
        const value = source.values[index];
        samples.set(`${coordinate}:${occurrence}`, { coordinate, occurrence, index, value: typeof value === 'string' || finite(value) ? value : null });
      });
      return samples;
    });
    const positions = [...new Map(indexed.flatMap(samples => [...samples.entries()])).entries()]
      .sort(([, a], [, b]) => a.coordinate - b.coordinate || a.occurrence - b.occurrence);
    add(section, `${metric} sample count`, indexed.map((samples, index) => ({ value: samples.size || null, missing: sources[index].missing || 'Not recorded' })), { group, noDelta: true });
    for (const [key, position] of positions) {
      const cells = indexed.map((samples, index) => ({ value: samples.get(key)?.value ?? null,
        missing: samples.has(key) ? 'Unavailable' : samples.size ? 'Not sampled' : sources[index].missing || 'Not recorded',
        status: sources[index].status, reason: sources[index].reason }));
      add(section, metric, cells, { group, unit, coordinate: position.coordinate, coordinateUnit, occurrence: position.occurrence });
      rows.push([section, group, metric, 'sample index', '', '', position.coordinate, coordinateUnit, position.occurrence,
        ...indexed.map(samples => samples.get(key)?.index ?? null), ...runs.slice(1).flatMap(() => [null, null])]);
    }
  };
  sampleRows('Torque samples', 'Torque', 'N·m', results.map(result => ({ coordinates: result.torque_waveform.electrical_angle_deg, values: result.torque_waveform.torque_Nm })), '° electrical');
  for (const [field, label] of [['phase_a_V', 'Phase A'], ['phase_b_V', 'Phase B'], ['phase_c_V', 'Phase C'], ['line_ab_V', 'Line A–B'], ['line_bc_V', 'Line B–C'], ['line_ca_V', 'Line C–A']] as const) {
    if (field.startsWith('line_') && !results.some(result => result.back_emf_waveform[field]?.length)) continue;
    sampleRows('Back EMF samples', label, 'V', results.map(result => ({ coordinates: result.back_emf_waveform.electrical_angle_deg, values: result.back_emf_waveform[field] ?? [] })), '° electrical');
  }
  add('Cogging samples', 'Output status', results.map(result => ({ value: result.summary.cogging?.status ?? null, reason: result.summary.cogging?.status_reason ?? undefined })), { noDelta: true });
  sampleRows('Cogging samples', 'Cogging torque', 'N·m', results.map(result => ({ coordinates: result.cogging_torque_waveform?.electrical_angle_deg ?? [], values: result.cogging_torque_waveform?.torque_Nm ?? [],
    status: result.summary.cogging?.status ?? undefined, reason: result.summary.cogging?.status_reason ?? undefined })), '° electrical');
  if (results.some(result => result.cogging_torque_waveform?.mechanical_angle_deg?.length)) sampleRows('Cogging samples', 'Mechanical angle', '° mechanical',
    results.map(result => ({ coordinates: result.cogging_torque_waveform?.electrical_angle_deg ?? [], values: result.cogging_torque_waveform?.mechanical_angle_deg ?? [] })), '° electrical');
  for (const limit of ['peak', 'continuous'] as const) {
    const curves = envelopes.map(item => item.curves.find(curve => curve.limit === limit));
    for (const [field, label, unit, scale] of [
      ['torque_Nm', 'Torque', 'N·m', 1], ['power_W', 'Power', 'kW', 0.001], ['i_d_A', 'id', 'A peak', 1], ['i_q_A', 'iq', 'A peak', 1],
      ['phase_voltage_peak_V', 'Phase voltage', 'V peak', 1], ['region', 'Operating region', '', 1],
    ] as const) sampleRows('Torque–speed samples', label, unit, curves.map((curve, index) => ({ coordinates: curve?.speed_rpm ?? [],
      values: curve && Array.isArray(curve[field]) ? curve[field].map(value => typeof value === 'number' ? value * scale : value) : [], missing: envelopes[index].envelope ? 'Not recorded' : envelopes[index].missing,
      status: envelopes[index].status?.status, reason: envelopes[index].status?.reason })), 'rpm', limit);
  }
  meta('Retained numerical field frames', runs.map(run => run.fields ? run.fields.frames.length : null), 'Fields');
  meta('Stored field snapshot', runs.map(run => run.fields ? run.fields.snapshot_available ? 'Available' : 'Not recorded' : null), 'Fields');
  meta('Snapshot angle (° electrical)', runs.map(run => run.fields?.snapshot_angle_deg), 'Fields');
  meta('Field playback removed', runs.map(run => run.fields ? run.fields.playback_removed ? 'Yes' : 'No' : null), 'Fields');
  return '\uFEFF' + rows.map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

export function comparisonCsvFilename(runs: ComparisonCsvRun[]): string {
  const id = runs[0]?.record.run_id.replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 90) || 'runs';
  return `coilem-comparison-${id}.csv`;
}
