import { useId, useMemo } from 'react';
import type { PublicFieldLinePlot } from './model';
import { ringPath, schematicThermalParts, thermalCrossSection } from './thermalCrossSection';
import type { ThermalEstimate } from './thermal';
import { nodeTemperature, thermalColour, thermalNodeLabel, temperatureText, thermalRange } from './thermalVisual';
import { useTemperatureUnit } from './useTemperatureUnit';

/**
 * The solved cross-section coloured by each component's estimated temperature.
 *
 * It is a picture, not the data: the numbers live in the table beside it, in
 * ordinary page text, so the drawing can stay small and nothing scales with it.
 * One colour per component; this is not a spatial temperature field.
 */
export function ThermalCrossSection({ result, plot, selected, onSelect }: {
  result: ThermalEstimate; plot?: PublicFieldLinePlot | null; selected: string | null; onSelect: (name: string) => void;
}) {
  const mesh = useMemo(() => thermalCrossSection(plot), [plot]);
  const [unit] = useTemperatureUnit();
  const id = useId().replace(/:/g, '');
  const range = thermalRange(result.nodes);
  if (!mesh) return <p className="thermal-visual-note">No solved cross-section is stored with this run, so only the table is shown.</p>;
  const fill = (name: string) => {
    const temperature = nodeTemperature(result.nodes[name]);
    return temperature === null || !range ? `url(#${id}-missing)` : thermalColour(temperature, range);
  };
  const over = (name: string) => nodeTemperature(result.nodes[name]) !== null && (result.nodes[name]?.margin_K ?? 0) < 0;
  // Parts the estimate has but the solved section does not: mount, bearings, shaft or housing.
  const schematic = schematicThermalParts(mesh, result.nodes, typeof result.inputs.housing_thickness_mm === 'number' ? result.inputs.housing_thickness_mm : null);
  return <figure className="thermal-section">
    <svg className="thermal-diagram" viewBox="195 15 410 410" role="img" aria-label="Motor thermal cross-section">
      <defs><pattern id={`${id}-missing`} width="7" height="7" patternUnits="userSpaceOnUse"><rect width="7" height="7" fill="#292f3c" /><path d="M-1 1l8 8M5-1l4 4" stroke="#697487" strokeWidth="1" /></pattern></defs>
      <g transform="translate(400 220)" className="thermal-solved-geometry">
        {mesh.parts.map((part) => <g key={part.region} data-mesh-region={part.region} data-thermal-node={part.node ?? undefined}
          className={part.node ? `thermal-node-marker${part.node === selected ? ' is-selected' : ''}${over(part.node) ? ' is-over-limit' : ''}` : undefined}
          onClick={part.node ? () => onSelect(part.node!) : undefined}>
          <path d={part.fillPath} fill={part.node ? fill(part.node) : '#111923'} />
          <path className="thermal-part-outline" d={part.outlinePath} fill="none" pointerEvents="none" />
          <title>{part.node ? `${thermalNodeLabel(part.node)}${nodeTemperature(result.nodes[part.node]) === null ? '' : ` · ${temperatureText(nodeTemperature(result.nodes[part.node])!, unit)}`}` : `${part.region.replace(/_/g, ' ')} · not in the thermal model`}</title>
        </g>)}
        {schematic.map((part) => <g key={part.key} data-schematic-part={part.key} data-thermal-node={part.node ?? undefined}
          className={`thermal-schematic-part${part.node ? ` thermal-node-marker${part.node === selected ? ' is-selected' : ''}` : ''}`}
          onClick={part.node ? () => onSelect(part.node!) : undefined}>
          <path d={ringPath(part.inner, part.outer)} fillRule="evenodd" fill={part.node ? fill(part.node) : '#1b2330'} />
          <path className="thermal-part-outline" d={ringPath(part.inner, part.outer)} fill="none" pointerEvents="none" />
          <title>{part.node && nodeTemperature(result.nodes[part.node]) !== null ? `${part.label} · ${temperatureText(nodeTemperature(result.nodes[part.node])!, unit)}` : part.label}</title>
        </g>)}
      </g>
    </svg>
    <figcaption className="thermal-temperature-legend" aria-label="Temperature colour scale">
      {range ? range[0] === range[1] ? <span>All parts {temperatureText(range[0], unit)}</span> : <><span>{temperatureText(range[0], unit)}</span><i /><span>{temperatureText(range[1], unit)}</span></> : <span>No temperatures available</span>}
      {!range && <span className="thermal-unavailable-key"><b /> Unavailable</span>}
    </figcaption>
    <p className="thermal-visual-note">One colour per part, from the coolest to the hottest in this result. It is not a temperature field.
      {schematic.length > 0 && ` The ${schematic.some((part) => part.key === 'mount') ? 'mount, bearings and shaft' : schematic.some((part) => part.key === 'bearings') ? 'housing, bearings and shaft' : 'housing'} ${schematic.length > 1 ? 'are' : 'is'} drawn as a sketch (dashed): ${schematic.length > 1 ? 'their sizes are' : 'its size is'} not part of the design.`}</p>
  </figure>;
}
