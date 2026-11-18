import { compareRunLosses, compareRunTiming, type ComparisonLossCell, type ComparisonResult } from './runComparison';

export const COMPARISON_STYLES = [
  { id: 'run-a', label: 'Run A', color: '#f59e0b', dashArray: undefined, phases: ['#f59e0b', '#fb7185', '#facc15'] },
  { id: 'run-b', label: 'Run B', color: '#22d3ee', dashArray: '7 5', phases: ['#22d3ee', '#60a5fa', '#2dd4bf'] },
  { id: 'run-c', label: 'Run C', color: '#c4b5fd', dashArray: '2 4', phases: ['#c4b5fd', '#e879f9', '#818cf8'] },
  { id: 'run-d', label: 'Run D', color: '#4ade80', dashArray: '12 4 2 4', phases: ['#4ade80', '#bef264', '#2dd4bf'] },
  { id: 'run-e', label: 'Run E', color: '#fb7185', dashArray: '12 4', phases: ['#fb7185', '#f9a8d4', '#fdba74'] },
  { id: 'run-f', label: 'Run F', color: '#60a5fa', dashArray: '8 3 2 3 2 3', phases: ['#60a5fa', '#a5b4fc', '#7dd3fc'] },
] as const;
export type ComparisonSlotId = typeof COMPARISON_STYLES[number]['id'];
export interface ComparisonSelection {
  baselineId: ComparisonSlotId;
  slots: Array<{ id: ComparisonSlotId; key: string }>;
}

export function initialComparisonSelection(baseline = '', candidate = ''): ComparisonSelection {
  return { baselineId: 'run-a', slots: [{ id: 'run-a', key: baseline }, { id: 'run-b', key: candidate !== baseline ? candidate : '' }] };
}

/** Letters/styles belong to slots, so pinning or removing another run never relabels a run. */
export function selectComparisonRun(selection: ComparisonSelection, id: ComparisonSlotId, key: string): ComparisonSelection {
  if (key && selection.slots.some(slot => slot.id !== id && slot.key === key)) return selection;
  return { ...selection, slots: selection.slots.map(slot => slot.id === id ? { ...slot, key } : slot) };
}

export function addComparisonRun(selection: ComparisonSelection, key: string): ComparisonSelection {
  const style = COMPARISON_STYLES.find(style => !selection.slots.some(slot => slot.id === style.id));
  if (!style || !key || selection.slots.some(slot => !slot.key || slot.key === key)) return selection;
  return { ...selection, slots: [...selection.slots, { id: style.id, key }] };
}

export function removeComparisonRun(selection: ComparisonSelection, id: ComparisonSlotId): ComparisonSelection {
  if (id === selection.baselineId || selection.slots.length <= 2) return selection;
  return { ...selection, slots: selection.slots.filter(slot => slot.id !== id) };
}

export function pinComparisonBaseline(selection: ComparisonSelection, id: ComparisonSlotId): ComparisonSelection {
  return selection.slots.some(slot => slot.id === id && slot.key) ? { ...selection, baselineId: id } : selection;
}

/** A removed stored run leaves a choice empty; never silently replace a pinned baseline. */
export function reconcileComparisonSelection(selection: ComparisonSelection, available: Set<string>): ComparisonSelection {
  if (selection.slots.every(slot => !slot.key || available.has(slot.key))) return selection;
  return { ...selection, slots: selection.slots.map(slot => available.has(slot.key) ? slot : { ...slot, key: '' }) };
}

/** Pairwise rules keep missing evidence and partial shaft outputs relative to the same baseline. */
export function compareMultipleLosses(results: ComparisonResult[]) {
  if (results.length < 2) return [];
  const pairs = results.slice(1).map(result => compareRunLosses(results[0], result, true));
  const rows = [...new Map(pairs.flatMap(pair => pair ?? []).map(row => [row.key, row])).values()];
  const missing: ComparisonLossCell = { value: null, missing: 'Not recorded' };
  return rows.map(row => ({ ...row,
    cells: [row.before, ...pairs.map(pair => pair?.find(candidate => candidate.key === row.key)?.after ?? missing)],
    comparable: [false, ...pairs.map(pair => pair?.find(candidate => candidate.key === row.key)?.comparable ?? false)],
    basisNotes: [null, ...pairs.map(pair => pair?.find(candidate => candidate.key === row.key)?.basisNote ?? null)],
  })).filter(row => !['total', 'subtotal'].includes(row.key) || row.cells.some(cell => cell.value !== null));
}

export function compareMultipleTiming(results: ComparisonResult[]) {
  if (results.length < 2) return { rows: [], recorded: [] };
  const pairs = results.slice(1).map(result => compareRunTiming(results[0], result));
  const rows = [...new Map(pairs.flatMap(pair => pair.rows).map(row => [row.key, row])).values()];
  return { recorded: [pairs[0].recordedBefore, ...pairs.map(pair => pair.recordedAfter)],
    rows: rows.map(row => ({ ...row, values: [row.before, ...pairs.map(pair => pair.rows.find(candidate => candidate.key === row.key)?.after ?? null)] })),
  };
}
